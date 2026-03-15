import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .lsa_service import (
    AGENT_IDENTITY_DOCUMENT_TYPES,
    build_lsa_identity_requirement,
    get_agent_identity_documents,
    verify_lsa_response_token,
)
from .models import CaseDocument, LsaAgentRequest, LsaAgentResponse, LsaAgentResponseItem


def _validate_agent_lsa_access(request, request_id, token):
    payload = verify_lsa_response_token(token)
    if not payload:
        return None
    token_req_id, token_agent_id = payload
    if token_req_id != request_id:
        return None
    if not request.user.is_authenticated or request.user.id != token_agent_id:
        return None
    req = get_object_or_404(LsaAgentRequest, pk=request_id)
    if req.target_agent_id != request.user.id:
        return None
    return req


def _parse_iso(value):
    if value in (None, ''):
        return None, None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return None, 'invalid_datetime'
    else:
        return None, 'invalid_datetime'
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt, None


def _parse_request_payload(request):
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body or '{}')
        except Exception:
            return {}

    payload = request.POST.copy()
    raw_items = payload.get('items')
    if raw_items:
        try:
            payload['items'] = json.loads(raw_items)
        except Exception:
            payload['items'] = []
    return payload


def _build_identity_requirement_context(lsa_req):
    requirement = build_lsa_identity_requirement(lsa_req.target_agent, lsa_req.batch.submission)
    labels = dict(CaseDocument.DocumentType.choices)
    rows = []
    for document_type in requirement['required_document_types']:
        uploaded = requirement['uploaded_documents'].get(document_type)
        rows.append({
            'document_type': document_type,
            'label': labels.get(document_type, document_type),
            'input_name': 'id_front' if document_type == CaseDocument.DocumentType.AGENT_ID_FRONT else 'id_back',
            'uploaded': bool(uploaded),
            'uploaded_document_id': getattr(uploaded, 'id', None),
            'uploaded_filename': getattr(uploaded, 'original_filename', '') if uploaded else '',
        })
    requirement['rows'] = rows
    return requirement


def _create_agent_identity_document(lsa_req, uploaded_by, upload_file, document_type):
    latest = (
        CaseDocument.objects.filter(
            submission=lsa_req.batch.submission,
            owner_user=uploaded_by,
            document_type=document_type,
        )
        .order_by('-version', '-created_at')
        .first()
    )
    version = ((latest.version if latest else 0) or 0) + 1
    return CaseDocument.objects.create(
        submission=lsa_req.batch.submission,
        document_type=document_type,
        document_scope=CaseDocument.DocumentScope.CASE,
        visibility_level=CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
        uploaded_by=uploaded_by,
        owner_user=uploaded_by,
        file=upload_file,
        original_filename=(getattr(upload_file, 'name', '') or '')[:255],
        status=CaseDocument.Status.UPLOADED,
        version=version,
        replaces=latest,
        metadata={
            'identity_verification_document': True,
            'lsa_request_id': lsa_req.id,
            'lsa_batch_id': lsa_req.batch_id,
            'agent_user_id': uploaded_by.id,
            'restricted_roles': ['SUPER_ADMIN', 'ADMIN', 'SUPERVISOR'],
        },
    )


@require_GET
@login_required
@ensure_csrf_cookie
def agent_lsa_response_input(request, request_id):
    token = (request.GET.get('token') or '').strip()
    if not token:
        return render(request, 'app/agent_lsa_response.html', {'error': 'invalid_link', 'request_id': request_id})
    lsa_req = _validate_agent_lsa_access(request, request_id, token)
    if not lsa_req:
        return render(request, 'app/agent_lsa_response.html', {'error': 'forbidden', 'request_id': request_id})

    proposed = (lsa_req.payload_snapshot or {}).get('proposed_schedule') or []
    latest = lsa_req.responses.order_by('-revision').first()
    existing = {
        'decision': latest.decision,
        'note': latest.note,
        'items': [
            {
                'service_code': it.service_code,
                'proposed_starts_at': it.proposed_starts_at.isoformat() if it.proposed_starts_at else None,
                'proposed_ends_at': it.proposed_ends_at.isoformat() if it.proposed_ends_at else None,
                'action': it.action,
                'suggested_starts_at': it.suggested_starts_at.isoformat() if it.suggested_starts_at else None,
                'suggested_ends_at': it.suggested_ends_at.isoformat() if it.suggested_ends_at else None,
                'note': it.note,
            }
            for it in latest.items.all()
        ],
    } if latest else None
    identity_requirement = _build_identity_requirement_context(lsa_req)

    return render(request, 'app/agent_lsa_response.html', {
        'error': None,
        'lsa_request': lsa_req,
        'proposed_schedule_json': json.dumps(proposed),
        'existing_response_json': json.dumps(existing or {}),
        'identity_requirement': identity_requirement,
    })


@require_POST
@login_required
@ensure_csrf_cookie
def agent_lsa_response_submit(request, request_id):
    body = _parse_request_payload(request)

    token = (body.get('token') or request.POST.get('token') or '').strip()
    if not token:
        return JsonResponse({'ok': False, 'error': 'invalid_link'}, status=400)

    lsa_req = _validate_agent_lsa_access(request, request_id, token)
    if not lsa_req:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    decision = (body.get('decision') or '').strip().upper()
    valid_decisions = {
        LsaAgentResponse.Decision.ACCEPT_AS_IS,
        LsaAgentResponse.Decision.PARTIAL,
        LsaAgentResponse.Decision.DECLINE,
    }
    if decision not in valid_decisions:
        return JsonResponse({'ok': False, 'error': 'invalid decision'}, status=400)

    note = (body.get('note') or '')[:1000]
    items = body.get('items') or []
    if not isinstance(items, list):
        return JsonResponse({'ok': False, 'error': 'items must be list'}, status=400)

    identity_requirement = build_lsa_identity_requirement(lsa_req.target_agent, lsa_req.batch.submission)
    upload_by_type = {
        CaseDocument.DocumentType.AGENT_ID_FRONT: request.FILES.get('id_front'),
        CaseDocument.DocumentType.AGENT_ID_BACK: request.FILES.get('id_back'),
    }
    if identity_requirement['required']:
        existing_docs = get_agent_identity_documents(lsa_req.batch.submission, lsa_req.target_agent)
        missing_document_types = [
            document_type
            for document_type in AGENT_IDENTITY_DOCUMENT_TYPES
            if document_type not in existing_docs and not upload_by_type.get(document_type)
        ]
        if missing_document_types:
            return JsonResponse(
                {
                    'ok': False,
                    'error': 'identity_documents_required',
                    'missing_document_types': missing_document_types,
                },
                status=400,
            )

    with transaction.atomic():
        for document_type, upload_file in upload_by_type.items():
            if upload_file:
                _create_agent_identity_document(lsa_req, request.user, upload_file, document_type)

        next_revision = (lsa_req.responses.order_by('-revision').values_list('revision', flat=True).first() or 0) + 1
        response = LsaAgentResponse.objects.create(
            request=lsa_req,
            responded_by=request.user,
            decision=decision,
            note=note,
            revision=next_revision,
        )

        for row in items:
            if not isinstance(row, dict):
                continue
            action = (row.get('action') or LsaAgentResponseItem.Action.ACCEPT).strip().upper()
            if action not in {
                LsaAgentResponseItem.Action.ACCEPT,
                LsaAgentResponseItem.Action.SUGGEST_CHANGE,
                LsaAgentResponseItem.Action.UNAVAILABLE,
            }:
                action = LsaAgentResponseItem.Action.ACCEPT

            p_start, err1 = _parse_iso(row.get('proposed_starts_at'))
            p_end, err2 = _parse_iso(row.get('proposed_ends_at'))
            if err1 or err2:
                continue

            s_start, s_err1 = _parse_iso(row.get('suggested_starts_at'))
            s_end, s_err2 = _parse_iso(row.get('suggested_ends_at'))
            if s_err1 or s_err2:
                return JsonResponse({'ok': False, 'error': 'invalid suggested datetime'}, status=400)
            if action == LsaAgentResponseItem.Action.SUGGEST_CHANGE:
                if not s_start or not s_end:
                    return JsonResponse({'ok': False, 'error': 'suggested times required for suggest-change'}, status=400)
                if s_end <= s_start:
                    return JsonResponse({'ok': False, 'error': 'suggested end must be after start'}, status=400)

            LsaAgentResponseItem.objects.create(
                response=response,
                service_code=(row.get('service_code') or '')[:50],
                service_label=(row.get('service_label') or '')[:200],
                proposed_starts_at=p_start,
                proposed_ends_at=p_end,
                action=action,
                suggested_starts_at=s_start,
                suggested_ends_at=s_end,
                note=(row.get('note') or '')[:1000],
            )

        if decision == LsaAgentResponse.Decision.DECLINE:
            lsa_req.status = LsaAgentRequest.Status.DECLINED
        else:
            lsa_req.status = LsaAgentRequest.Status.RESPONDED
        lsa_req.responded_at = timezone.now()
        lsa_req.save(update_fields=['status', 'responded_at'])

        if identity_requirement['required'] and request.user.agent_identity_verification_status == request.user.AgentIdentityVerificationStatus.REQUIRED:
            if get_agent_identity_documents(lsa_req.batch.submission, request.user).keys() >= set(AGENT_IDENTITY_DOCUMENT_TYPES):
                request.user.agent_identity_verification_status = request.user.AgentIdentityVerificationStatus.SUBMITTED
                request.user.save(update_fields=['agent_identity_verification_status'])

    return JsonResponse({'ok': True, 'response_id': response.id, 'revision': response.revision})

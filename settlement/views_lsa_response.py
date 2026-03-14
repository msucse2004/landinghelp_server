import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .lsa_service import verify_lsa_response_token
from .models import LsaAgentRequest, LsaAgentResponse, LsaAgentResponseItem


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

    return render(request, 'app/agent_lsa_response.html', {
        'error': None,
        'lsa_request': lsa_req,
        'proposed_schedule_json': json.dumps(proposed),
        'existing_response_json': json.dumps(existing or {}),
    })


@require_POST
@login_required
@ensure_csrf_cookie
def agent_lsa_response_submit(request, request_id):
    try:
        body = json.loads(request.body or '{}')
    except Exception:
        body = {}

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

    return JsonResponse({'ok': True, 'response_id': response.id, 'revision': response.revision})

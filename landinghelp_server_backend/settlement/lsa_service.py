from django.db import transaction
from django.utils import timezone
from urllib.parse import urlencode
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.conf import settings
from django.urls import reverse

from .models import (
    CaseDocument,
    LsaAgentContract,
    LsaSourcingBatch,
    LsaAgentRequest,
    LsaAgentResponse,
    ServiceSchedulePlan,
    ServiceScheduleItem,
    UserSettlementPlan,
    ServiceStatePrice,
    SettlementService,
)
from .schedule_utils import serialize_schedule_items_for_calendar, plan_to_legacy_schedule
from survey.quote_input import get_quote_input_data


LSA_RESPONSE_TOKEN_MAX_AGE = 7 * 24 * 3600
AGENT_IDENTITY_DOCUMENT_TYPES = (
    CaseDocument.DocumentType.AGENT_ID_FRONT,
    CaseDocument.DocumentType.AGENT_ID_BACK,
)


def _lsa_signer():
    return TimestampSigner(key=settings.SECRET_KEY)


def build_lsa_response_token(request_id, agent_id):
    return _lsa_signer().sign(f"{request_id}:{agent_id}")


def verify_lsa_response_token(token):
    try:
        raw = _lsa_signer().unsign(token, max_age=LSA_RESPONSE_TOKEN_MAX_AGE)
        parts = raw.split(':', 1)
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        pass
    return None


def build_lsa_response_link(request_id, agent_id, request=None):
    token = build_lsa_response_token(request_id, agent_id)
    path = reverse('agent_lsa_response_input', kwargs={'request_id': request_id})
    url = path + '?' + urlencode({'token': token})
    if request and getattr(settings, 'SITE_URL', None):
        base = (settings.SITE_URL or '').strip().rstrip('/')
        if base:
            return base + url
    return url


def _has_schedule_finalize_override(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    try:
        if user.has_perm('settlement.can_finalize_schedule'):
            return True
    except Exception:
        pass
    return bool(getattr(user, 'schedule_finalize_override', False))


def _can_finalize_schedule_actor(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    role = getattr(user, 'role', None)
    role_cls = getattr(user, 'Role', None)
    if role in {
        getattr(role_cls, 'SUPER_ADMIN', 'SUPER_ADMIN'),
        getattr(role_cls, 'ADMIN', 'ADMIN'),
        getattr(role_cls, 'SUPERVISOR', 'SUPERVISOR'),
    }:
        return True
    if role == getattr(role_cls, 'HQ_STAFF', 'HQ_STAFF'):
        return _has_schedule_finalize_override(user)
    return False


def agent_requires_identity_documents(agent):
    if not agent:
        return False
    checker = getattr(agent, 'agent_identity_verification_required', None)
    if callable(checker):
        return bool(checker())
    role_cls = getattr(agent, 'Role', None)
    status_cls = getattr(agent, 'AgentIdentityVerificationStatus', None)
    return bool(
        getattr(agent, 'role', None) == getattr(role_cls, 'AGENT', 'AGENT')
        and getattr(agent, 'agent_identity_verification_status', None) == getattr(status_cls, 'REQUIRED', 'REQUIRED')
    )


def get_agent_identity_documents(submission, agent):
    if not submission or not agent:
        return {}
    rows = (
        CaseDocument.objects.filter(
            submission=submission,
            owner_user=agent,
            document_type__in=AGENT_IDENTITY_DOCUMENT_TYPES,
        )
        .exclude(status=CaseDocument.Status.ARCHIVED)
        .order_by('document_type', '-version', '-created_at')
    )
    documents = {}
    for row in rows:
        documents.setdefault(row.document_type, row)
    return documents


def has_required_agent_identity_documents(submission, agent):
    documents = get_agent_identity_documents(submission, agent)
    return all(document_type in documents for document_type in AGENT_IDENTITY_DOCUMENT_TYPES)


def build_lsa_identity_requirement(agent, submission=None):
    documents = get_agent_identity_documents(submission, agent) if submission and agent else {}
    required = agent_requires_identity_documents(agent)
    missing = [document_type for document_type in AGENT_IDENTITY_DOCUMENT_TYPES if document_type not in documents]
    return {
        'required': required,
        'documents_complete': (not required) or not missing,
        'required_document_types': list(AGENT_IDENTITY_DOCUMENT_TYPES),
        'missing_document_types': missing if required else [],
        'uploaded_documents': documents,
        'verification_status': getattr(agent, 'agent_identity_verification_status', ''),
        'verified_at': getattr(agent, 'agent_identity_verified_at', None),
    }


def _extract_state_code(submission):
    data = get_quote_input_data(submission) if submission else {}
    state = (data.get('settlement_state') or '').strip().upper()
    if state:
        return state
    region = (data.get('region') or '').strip()
    if not region:
        return ''
    return region.split(',')[0].strip().upper()


def _build_requested_services_snapshot(schedule_plan):
    rows = []
    seen = set()
    for it in schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED).order_by('sort_order', 'id'):
        code = (it.service_code or '').strip()
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({
            'code': code,
            'label': it.service_label or code,
            'service_type': it.service_type or '',
        })
    return rows


def _build_internal_pricing_snapshot(schedule_plan, state_code=''):
    items = _build_requested_services_snapshot(schedule_plan)
    out = []
    for svc in items:
        code = svc['code']
        base_service = SettlementService.objects.filter(code=code).first()
        if not base_service and str(code).isdigit():
            base_service = SettlementService.objects.filter(id=int(code)).first()
        if not base_service:
            out.append({
                'service_code': code,
                'service_label': svc.get('label') or code,
                'internal_agent_price': None,
                'currency': 'USD',
                'state_code': state_code or '',
            })
            continue
        state_price = None
        if state_code:
            state_price = ServiceStatePrice.objects.filter(service=base_service, state_code=state_code).first()
        agent_price = state_price.agent_price if state_price else base_service.agent_price
        out.append({
            'service_code': code,
            'service_label': svc.get('label') or base_service.name or code,
            'internal_agent_price': float(agent_price) if agent_price is not None else None,
            'currency': 'USD',
            'state_code': state_code or '',
        })
    return out


def _build_customer_safe_info(submission):
    data = get_quote_input_data(submission) if submission else {}
    return {
        'submission_id': submission.id if submission else None,
        'region': data.get('region') or '',
        'entry_date': data.get('entry_date') or '',
    }


def _extract_agent_pricing_constraints(agent):
    raw = getattr(agent, 'agent_level_constraints', None)
    constraints = raw if isinstance(raw, dict) else {}
    weight = constraints.get('lsa_auto_priority_weight')
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        weight = 1.0
    if weight <= 0:
        weight = 1.0
    return {
        'agent_level': getattr(agent, 'agent_level', '') or 'BRONZE',
        'lsa_auto_priority_weight': round(weight, 4),
        'max_active_assignments': constraints.get('max_active_assignments'),
    }


def _build_agent_adjusted_pricing_snapshot(internal_pricing_snapshot, agent):
    """
    Agent 레벨 constraint에 따라 LSA proposal 단가를 service별로 계산.
    - base: internal_agent_price
    - adjusted: internal_agent_price * lsa_auto_priority_weight
    """
    rows = list(internal_pricing_snapshot or [])
    constraints = _extract_agent_pricing_constraints(agent)
    weight = constraints.get('lsa_auto_priority_weight') or 1.0
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        base_price = row.get('internal_agent_price')
        adjusted_price = None
        if base_price is not None:
            try:
                adjusted_price = round(float(base_price) * float(weight), 2)
            except (TypeError, ValueError):
                adjusted_price = None
        out.append({
            **row,
            'proposal_agent_price': adjusted_price,
            'pricing_weight': weight,
            'pricing_rule': 'base_internal_agent_price * lsa_auto_priority_weight',
            'agent_level': constraints.get('agent_level') or 'BRONZE',
        })
    return out


def _build_agent_payload(batch, agent):
    snapshot_plan = batch.schedule_plan
    based_on_id = getattr(snapshot_plan, 'based_on_id', None)
    root_recommended_id = based_on_id
    if based_on_id:
        based_on_plan = ServiceSchedulePlan.objects.filter(pk=based_on_id).only('based_on_id').first()
        if based_on_plan and based_on_plan.based_on_id:
            root_recommended_id = based_on_plan.based_on_id

    constraints = _extract_agent_pricing_constraints(agent)
    adjusted_pricing = _build_agent_adjusted_pricing_snapshot(batch.internal_pricing_snapshot, agent)
    identity_requirement = build_lsa_identity_requirement(agent, batch.submission)

    return {
        'batch_id': batch.id,
        'submission_id': batch.submission_id,
        'target_agent_id': agent.id,
        'target_agent_name': agent.get_full_name() or agent.username,
        'target_agent_level': constraints.get('agent_level') or 'BRONZE',
        'proposed_schedule_plan_id': snapshot_plan.id,
        'based_on_schedule_plan_id': based_on_id,
        'root_recommended_schedule_plan_id': root_recommended_id,
        'proposed_schedule_version': batch.schedule_version,
        'customer_safe_info': _build_customer_safe_info(batch.submission),
        'requested_services': batch.requested_services_snapshot,
        'proposed_schedule': batch.proposed_schedule_snapshot,
        'internal_service_pricing': adjusted_pricing,
        'constraint_snapshot': constraints,
        'identity_verification_required': identity_requirement['required'],
        'identity_documents_complete': identity_requirement['documents_complete'],
        'required_identity_documents': identity_requirement['required_document_types'],
        'sent_at': timezone.now().isoformat(),
    }


def build_lsa_preview_payload(schedule_plan, agent):
    """발송 전 Admin UI에서 Agent별 LSA proposal 포맷 미리보기."""
    if not schedule_plan or not getattr(schedule_plan, 'submission_id', None):
        raise ValueError('유효한 schedule_plan이 필요합니다.')
    if not agent:
        raise ValueError('유효한 agent가 필요합니다.')

    proposed_schedule = serialize_schedule_items_for_calendar(schedule_plan)
    if not proposed_schedule:
        raise ValueError('제안 일정 항목이 없습니다.')

    state_code = _extract_state_code(schedule_plan.submission)
    requested_services = _build_requested_services_snapshot(schedule_plan)
    internal_pricing = _build_internal_pricing_snapshot(schedule_plan, state_code=state_code)
    adjusted_pricing = _build_agent_adjusted_pricing_snapshot(internal_pricing, agent)
    constraints = _extract_agent_pricing_constraints(agent)
    identity_requirement = build_lsa_identity_requirement(agent, schedule_plan.submission)

    return {
        'submission_id': schedule_plan.submission_id,
        'target_agent_id': agent.id,
        'target_agent_name': agent.get_full_name() or agent.username,
        'target_agent_level': constraints.get('agent_level') or 'BRONZE',
        'proposed_schedule_plan_id': schedule_plan.id,
        'based_on_schedule_plan_id': getattr(schedule_plan, 'based_on_id', None),
        'proposed_schedule_version': schedule_plan.version,
        'customer_safe_info': _build_customer_safe_info(schedule_plan.submission),
        'requested_services': requested_services,
        'proposed_schedule': proposed_schedule,
        'internal_service_pricing': adjusted_pricing,
        'constraint_snapshot': constraints,
        'identity_verification_required': identity_requirement['required'],
        'identity_documents_complete': identity_requirement['documents_complete'],
        'required_identity_documents': identity_requirement['required_document_types'],
        'preview_generated_at': timezone.now().isoformat(),
    }


def _notify_agent_lsa(batch, agent, payload, lsa_request, language_code='ko'):
    from messaging.models import Conversation, ConversationParticipant, Message
    from .notifications import _get_or_create_workspace_conversation, _get_system_sender, _is_email_configured
    from django.conf import settings
    from django.core.mail import send_mail

    sender = _get_system_sender()
    if not sender:
        return False

    conv = _get_or_create_workspace_conversation(
        batch.submission,
        Conversation.WorkspaceType.LOCAL_EXECUTION,
        subject_fallback='LSA 일정 제안 요청',
        agent=agent,
    )
    ConversationParticipant.objects.get_or_create(conversation=conv, user=agent)

    lines = [
        'LSA 일정 제안 요청',
        f"Batch #{batch.id} / Schedule v{batch.schedule_version}",
        '',
        '요청 서비스:',
    ]
    for svc in batch.requested_services_snapshot:
        lines.append(f"- {svc.get('label') or svc.get('code')} ({svc.get('code')})")
    lines.append('')
    lines.append('제안 일정:')
    for row in batch.proposed_schedule_snapshot:
        label = row.get('service_label') or row.get('service_code')
        lines.append(f"- {label}: {row.get('starts_at')} ~ {row.get('ends_at')}")
    lines.append('')
    lines.append('응답 링크:')
    lines.append(build_lsa_response_link(lsa_request.id, agent.id))
    lines.append('')
    if payload.get('identity_verification_required'):
        lines.append('추가 제출 필요:')
        lines.append('- 최초 온보딩 확인을 위해 신분증 앞면/뒷면 업로드가 필요합니다.')
        lines.append('')
    lines.append('내부 단가(Agent):')
    for p in (payload.get('internal_service_pricing') or []):
        base_price = p.get('internal_agent_price')
        proposal_price = p.get('proposal_agent_price')
        lines.append(
            f"- {p.get('service_label')}: base={base_price} {p.get('currency')} / proposal={proposal_price} {p.get('currency')}"
        )

    body = '\n'.join(lines)
    try:
        Message.objects.create(conversation=conv, sender=sender, body=body)
    except Exception:
        return False

    if _is_email_configured() and getattr(agent, 'email', None):
        try:
            send_mail(
                f"[LSA] 일정 제안 요청 Batch #{batch.id}",
                body,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [agent.email],
                fail_silently=True,
            )
        except Exception:
            pass
    return True


def _notify_agent_lsa_not_selected(batch, agent):
    from messaging.models import Conversation, ConversationParticipant, Message
    from .notifications import _get_or_create_workspace_conversation, _get_system_sender, _is_email_configured
    from django.conf import settings
    from django.core.mail import send_mail

    sender = _get_system_sender()
    if not sender:
        return False

    conv = _get_or_create_workspace_conversation(
        batch.submission,
        Conversation.WorkspaceType.LOCAL_EXECUTION,
        subject_fallback='LSA 결과 안내',
        agent=agent,
    )
    ConversationParticipant.objects.get_or_create(conversation=conv, user=agent)

    body = '\n'.join([
        'LSA 결과 안내',
        f"Batch #{batch.id}",
        '',
        '이번 소싱 배치에서는 다른 Agent가 최종 선정되었습니다.',
        '검토해 주셔서 감사합니다. 다음 요청에서 다시 연락드리겠습니다.',
    ])
    try:
        Message.objects.create(conversation=conv, sender=sender, body=body)
    except Exception:
        return False

    if _is_email_configured() and getattr(agent, 'email', None):
        try:
            send_mail(
                f"[LSA] Batch #{batch.id} 결과 안내",
                body,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [agent.email],
                fail_silently=True,
            )
        except Exception:
            pass
    return True


def _expand_existing_shared_conversation_for_contract(contract):
    """
    기존 customer-admin 공유 대화에 선정 Agent를 참여자로 추가하고,
    Agent 합류 시스템 메시지를 남긴다. (idempotent)
    """
    from messaging.models import Conversation, ConversationParticipant, Message
    from .notifications import _get_or_create_workspace_conversation, _get_system_sender

    submission = contract.submission
    selected_agent = contract.selected_agent
    if not submission or not selected_agent:
        return False

    sender = _get_system_sender()
    if not sender:
        return False

    conv = _get_or_create_workspace_conversation(
        submission,
        Conversation.WorkspaceType.LOCAL_EXECUTION,
        subject_fallback='현지진행방',
        agent=selected_agent,
    )
    ConversationParticipant.objects.get_or_create(conversation=conv, user=selected_agent)

    display_name = selected_agent.get_full_name() or selected_agent.username or f'Agent#{selected_agent.id}'
    join_body = f"System: {display_name} joined the thread."
    if not Message.objects.filter(conversation=conv, body=join_body).exists():
        Message.objects.create(
            conversation=conv,
            sender=sender,
            body=join_body,
        )
    return True


def _deliver_contract_to_selected_agent(contract):
    """
    선정 Agent에게 계약 확정 안내를 앱 메시지 + 이메일로 전달.
    """
    from messaging.models import Conversation, ConversationParticipant, Message
    from .notifications import _get_or_create_workspace_conversation, _get_system_sender, _is_email_configured
    from django.conf import settings
    from django.core.mail import send_mail

    selected_agent = contract.selected_agent
    if not selected_agent:
        return False
    sender = _get_system_sender()
    if not sender:
        return False

    conv = _get_or_create_workspace_conversation(
        contract.submission,
        Conversation.WorkspaceType.LOCAL_EXECUTION,
        subject_fallback='계약 확정 안내',
        agent=selected_agent,
    )
    ConversationParticipant.objects.get_or_create(conversation=conv, user=selected_agent)

    execution_plan_id = getattr(contract, 'execution_schedule_plan_id', None)
    lines = [
        '계약 확정 안내',
        f"Batch #{contract.batch_id}",
        f"Contract #{contract.id}",
    ]
    if execution_plan_id:
        lines.append(f"Execution plan #{execution_plan_id}")
    lines.extend([
        '',
        '최종 Agent로 선정되었습니다. 계약이 확정되었으며 실행 일정이 생성되었습니다.',
        '고객/관리자와의 기존 스레드에서 후속 진행 내용을 확인해 주세요.',
    ])
    body = '\n'.join(lines)

    try:
        Message.objects.create(conversation=conv, sender=sender, body=body)
    except Exception:
        return False

    if _is_email_configured() and getattr(selected_agent, 'email', None):
        try:
            send_mail(
                f"[LSA] 계약 확정 Batch #{contract.batch_id}",
                body,
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                [selected_agent.email],
                fail_silently=True,
            )
        except Exception:
            pass
    return True


def _build_lsa_sent_snapshot_plan(schedule_plan, actor=None):
    """
    LSA 발송 시점 immutable snapshot(FINALIZED) 플랜을 생성한다.
    - DRAFT/REVIEWING working draft와 분리
    - 이후 admin 수정이 있어도 발송 스냅샷은 변하지 않음
    """
    if not schedule_plan:
        raise ValueError('schedule_plan is required')

    if schedule_plan.status == ServiceSchedulePlan.Status.FINALIZED:
        return schedule_plan

    next_version = (
        ServiceSchedulePlan.objects.filter(submission=schedule_plan.submission)
        .order_by('-version')
        .values_list('version', flat=True)
        .first()
        or 0
    ) + 1

    snapshot_plan = ServiceSchedulePlan.objects.create(
        submission=schedule_plan.submission,
        quote=schedule_plan.quote,
        customer=schedule_plan.customer,
        status=ServiceSchedulePlan.Status.FINALIZED,
        source=ServiceSchedulePlan.Source.ADMIN,
        version=next_version,
        based_on=schedule_plan,
        created_by=actor,
        updated_by=actor,
    )

    base_items = list(
        schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
        .order_by('sort_order', 'starts_at', 'id')
    )
    for it in base_items:
        ServiceScheduleItem.objects.create(
            schedule_plan=snapshot_plan,
            service_code=it.service_code,
            service_label=it.service_label,
            service_type=it.service_type,
            starts_at=it.starts_at,
            ends_at=it.ends_at,
            duration_minutes=it.duration_minutes,
            assigned_agent_id=it.assigned_agent_id,
            location_text=it.location_text,
            status=it.status,
            source_score=it.source_score,
            source_reason=it.source_reason,
            based_on_item=it,
            recommendation_source=it.recommendation_source,
            needs_admin_review=it.needs_admin_review,
            recommendation_metadata=it.recommendation_metadata if isinstance(it.recommendation_metadata, dict) else {},
            notes=it.notes,
            sort_order=it.sort_order,
        )

    return snapshot_plan


def send_lsa_batch_for_schedule_plan(schedule_plan, agents, actor=None):
    """
    Admin 조정안 스케줄을 기준으로 LSA 배치를 생성하고, 후보 Agent들에게 동일 스냅샷을 발송.
    """
    if not schedule_plan or not getattr(schedule_plan, 'submission_id', None):
        raise ValueError('유효한 schedule_plan이 필요합니다.')
    if actor is not None and not _can_finalize_schedule_actor(actor):
        raise PermissionError('LSA 전송 권한이 없습니다.')
    if schedule_plan.status not in (schedule_plan.Status.DRAFT, schedule_plan.Status.REVIEWING, schedule_plan.Status.FINALIZED):
        raise ValueError('LSA 전송 가능한 스케줄 상태가 아닙니다.')

    snapshot_plan = _build_lsa_sent_snapshot_plan(schedule_plan, actor=actor)
    items = serialize_schedule_items_for_calendar(snapshot_plan)
    if not items:
        raise ValueError('제안 일정 항목이 없습니다.')

    state_code = _extract_state_code(snapshot_plan.submission)
    requested_services = _build_requested_services_snapshot(snapshot_plan)
    pricing = _build_internal_pricing_snapshot(snapshot_plan, state_code=state_code)

    with transaction.atomic():
        batch = LsaSourcingBatch.objects.create(
            submission=snapshot_plan.submission,
            schedule_plan=snapshot_plan,
            schedule_version=snapshot_plan.version or 1,
            proposed_schedule_snapshot=items,
            requested_services_snapshot=requested_services,
            internal_pricing_snapshot=pricing,
            created_by=actor,
        )
        created_requests = []
        for agent in agents:
            payload = _build_agent_payload(batch, agent)
            req = LsaAgentRequest.objects.create(
                batch=batch,
                target_agent=agent,
                payload_snapshot=payload,
                status=LsaAgentRequest.Status.SENT,
            )
            _notify_agent_lsa(batch, agent, payload, lsa_request=req)
            created_requests.append(req)

    return batch, created_requests


def _response_item_key(row):
    return (
        (row.service_code or '').strip(),
        row.proposed_starts_at.isoformat() if row.proposed_starts_at else '',
        row.proposed_ends_at.isoformat() if row.proposed_ends_at else '',
    )


def _schedule_item_key(row):
    return (
        (row.service_code or '').strip(),
        row.starts_at.isoformat() if row.starts_at else '',
        row.ends_at.isoformat() if row.ends_at else '',
    )


def generate_final_execution_schedule(contract, actor=None, approved_modification_keys=None):
    """
    계약(선정 Agent) 기준 최종 실행 일정(ServiceSchedulePlan.ACTIVE) 생성.
    source of truth는 execution plan 1건이며, draft/history는 수정하지 않는다.
    """
    base_plan = contract.batch.schedule_plan
    selected_request = contract.selected_request
    selected_response = contract.selected_response or selected_request.responses.order_by('-revision').first()

    next_version = (
        ServiceSchedulePlan.objects.filter(submission=base_plan.submission)
        .order_by('-version')
        .values_list('version', flat=True)
        .first()
        or 0
    ) + 1

    final_plan = ServiceSchedulePlan.objects.create(
        submission=base_plan.submission,
        quote=base_plan.quote,
        customer=base_plan.customer,
        status=ServiceSchedulePlan.Status.ACTIVE,
        source=ServiceSchedulePlan.Source.HYBRID,
        version=next_version,
        based_on=base_plan,
        created_by=actor,
        updated_by=actor,
    )

    response_items_by_key = {}
    if selected_response:
        for row in selected_response.items.all():
            response_items_by_key[_response_item_key(row)] = row

    approved_keys = set(approved_modification_keys or [])
    approve_all_suggestions = not approved_keys

    created_items = []
    base_items = list(
        base_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
        .order_by('sort_order', 'starts_at', 'id')
    )
    for it in base_items:
        starts_at = it.starts_at
        ends_at = it.ends_at
        notes = it.notes or ''
        response_item = response_items_by_key.get(_schedule_item_key(it))

        if response_item and response_item.action == response_item.Action.SUGGEST_CHANGE:
            k = _response_item_key(response_item)
            if (approve_all_suggestions or k in approved_keys) and response_item.suggested_starts_at and response_item.suggested_ends_at:
                starts_at = response_item.suggested_starts_at
                ends_at = response_item.suggested_ends_at
                notes = (notes + '\n' if notes else '') + 'Adjusted from selected agent suggestion'
        elif response_item and response_item.action == response_item.Action.UNAVAILABLE:
            notes = (notes + '\n' if notes else '') + 'Selected agent reported unavailable; kept admin slot'

        assigned_agent_id = it.assigned_agent_id
        if it.service_type == ServiceScheduleItem.ServiceType.IN_PERSON_AGENT:
            assigned_agent_id = selected_request.target_agent_id

        created_items.append(ServiceScheduleItem(
            schedule_plan=final_plan,
            service_code=it.service_code,
            service_label=it.service_label,
            service_type=it.service_type,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=it.duration_minutes,
            assigned_agent_id=assigned_agent_id,
            location_text=it.location_text,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
            source_score=it.source_score,
            source_reason=(it.source_reason or '')[:500],
            based_on_item=it,
            recommendation_source='agent_finalized',
            needs_admin_review=False,
            notes=notes[:1000],
            sort_order=it.sort_order,
        ))
    ServiceScheduleItem.objects.bulk_create(created_items)

    legacy = plan_to_legacy_schedule(final_plan, customer_safe=True)
    if final_plan.customer_id:
        try:
            plan = UserSettlementPlan.objects.get(user_id=final_plan.customer_id)
            plan.service_schedule = legacy
            plan.save(update_fields=['service_schedule', 'updated_at'])
        except UserSettlementPlan.DoesNotExist:
            UserSettlementPlan.objects.create(
                user_id=final_plan.customer_id,
                service_schedule=legacy,
            )

    return final_plan


def select_lsa_agent_for_contract(batch_id, request_id, response_id, actor=None, note=''):
    """
    Admin이 LSA 배치에서 1명의 Agent를 최종 선정해 계약 레코드를 생성한다.
    - batch당 1회만 가능
    - 선택된 요청/응답은 동일 batch 소속이어야 함
    - selected/non-selected 상태를 일괄 반영
    """
    if actor is not None and not _can_finalize_schedule_actor(actor):
        raise PermissionError('LSA 최종 선정 권한이 없습니다.')
    with transaction.atomic():
        batch = LsaSourcingBatch.objects.select_for_update().select_related('schedule_plan', 'submission').get(pk=batch_id)
        if batch.selected_request_id:
            raise ValueError('이미 Agent가 선정된 배치입니다.')

        selected_request = LsaAgentRequest.objects.select_for_update().select_related('target_agent').get(pk=request_id)
        if selected_request.batch_id != batch.id:
            raise ValueError('선택 요청이 해당 배치에 속하지 않습니다.')
        if selected_request.status != LsaAgentRequest.Status.RESPONDED:
            raise ValueError('필수 신분 확인 서류 업로드까지 완료된 응답만 선정할 수 있습니다.')

        selected_response = None
        if response_id:
            selected_response = LsaAgentResponse.objects.select_for_update().get(pk=response_id)
            if selected_response.request_id != selected_request.id:
                raise ValueError('선택 응답이 해당 요청에 속하지 않습니다.')

        contract = LsaAgentContract.objects.create(
            batch=batch,
            submission=batch.submission,
            schedule_plan=batch.schedule_plan,
            selected_request=selected_request,
            selected_response=selected_response,
            selected_agent=selected_request.target_agent,
            selected_by=actor,
            selection_note=(note or '')[:1000],
            audit_payload={
                'batch_id': batch.id,
                'request_id': selected_request.id,
                'response_id': selected_response.id if selected_response else None,
                'selected_agent_id': selected_request.target_agent_id,
                'selected_by_id': getattr(actor, 'id', None),
                'selected_at': timezone.now().isoformat(),
            },
        )

        final_execution_plan = generate_final_execution_schedule(contract, actor=actor)
        contract.execution_schedule_plan = final_execution_plan
        contract.save(update_fields=['execution_schedule_plan'])
        if batch.submission_id:
            batch.submission.advance_case_stage(batch.submission.CaseStage.SERVICES_IN_PROGRESS)

        selected_request.status = LsaAgentRequest.Status.SELECTED
        selected_request.responded_at = selected_request.responded_at or timezone.now()
        selected_request.save(update_fields=['status', 'responded_at'])

        non_selected = list(
            LsaAgentRequest.objects.select_for_update()
            .filter(batch=batch)
            .exclude(id=selected_request.id)
            .exclude(status=LsaAgentRequest.Status.CANCELLED)
        )
        for req in non_selected:
            req.status = LsaAgentRequest.Status.NOT_SELECTED
        if non_selected:
            LsaAgentRequest.objects.bulk_update(non_selected, ['status'])

        now = timezone.now()
        batch.selected_request = selected_request
        batch.selected_at = now
        batch.closed_at = now
        batch.save(update_fields=['selected_request', 'selected_at', 'closed_at'])

    for req in non_selected:
        try:
            _notify_agent_lsa_not_selected(batch, req.target_agent)
        except Exception:
            pass

    try:
        _expand_existing_shared_conversation_for_contract(contract)
    except Exception:
        pass

    try:
        _deliver_contract_to_selected_agent(contract)
    except Exception:
        pass

    return contract

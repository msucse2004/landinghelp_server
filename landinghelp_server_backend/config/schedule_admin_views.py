"""
Admin 스케줄 UI: ServiceSchedulePlan/Item 기반 달력 페이지 및 API.
고객 대면 달력(customer_dashboard 등)은 변경하지 않음.
"""
from datetime import datetime, date, time, timedelta
import re
import json
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.db import models

from config.views import _staff_required
from survey.models import SurveySubmission
from survey.quote_input import get_quote_input_data
from settlement.constants import get_service_label
from settlement.models import (
    ServiceSchedulePlan,
    ServiceScheduleItem,
    SettlementQuote,
    SettlementService,
    UserSettlementPlan,
    LsaSourcingBatch,
    LsaAgentRequest,
    LsaAgentContract,
    LsaAgentResponse,
    LsaAgentResponseItem,
)
from settlement.scheduling_engine import generate_schedule_draft, regenerate_agent_dependent_items
from settlement.schedule_utils import plan_to_legacy_schedule, serialize_schedule_items_for_calendar
from settlement.availability_request import get_agents_needing_availability, send_availability_request_to_agent
from settlement.availability_request import (
    get_availability_overlap_rows,
    get_availability_requests_for_workbench,
    send_availability_request_to_customer,
)
from settlement.lsa_service import send_lsa_batch_for_schedule_plan, select_lsa_agent_for_contract, build_lsa_preview_payload
from settlement.forms import US_STATES


def _can_view_internal_availability_responses(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    role = getattr(user, 'role', None)
    role_cls = getattr(user, 'Role', None)
    allowed_roles = {
        getattr(role_cls, 'SUPER_ADMIN', 'SUPER_ADMIN'),
        getattr(role_cls, 'ADMIN', 'ADMIN'),
        getattr(role_cls, 'SUPERVISOR', 'SUPERVISOR'),
    }
    return bool(getattr(user, 'is_superuser', False) or role in allowed_roles)


def _has_schedule_finalize_override(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    try:
        if user.has_perm('settlement.can_finalize_schedule'):
            return True
    except Exception:
        pass
    return bool(getattr(user, 'schedule_finalize_override', False))


def _can_optimize_and_send_schedule(user):
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


def _schedule_action_forbidden_response():
    return JsonResponse({'ok': False, 'error': '해당 작업 권한이 없습니다.'}, status=403)


def _get_schedule_plan_for_submission(submission):
    """제출에 대한 현재 작업 대상 플랜 조회: editable 우선, 없으면 최신 플랜."""
    editable = _get_editable_schedule_plan_for_submission(submission)
    if editable:
        return editable
    return (
        ServiceSchedulePlan.objects.filter(
            submission=submission,
            status__in=(
                ServiceSchedulePlan.Status.DRAFT,
                ServiceSchedulePlan.Status.REVIEWING,
                ServiceSchedulePlan.Status.FINALIZED,
                ServiceSchedulePlan.Status.SENT,
                ServiceSchedulePlan.Status.ACTIVE,
            ),
        )
        .order_by('-updated_at')
        .select_related('quote', 'customer')
        .first()
    )


def _get_editable_schedule_plan_for_submission(submission):
    """Admin이 직접 수정 가능한 플랜(DRAFT/REVIEWING), 최신 1건."""
    return (
        ServiceSchedulePlan.objects.filter(
            submission=submission,
            status__in=(ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING),
        )
        .order_by('-updated_at')
        .select_related('quote', 'customer')
        .first()
    )


def _is_plan_editable(schedule_plan):
    if not schedule_plan:
        return False
    return schedule_plan.status in (ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING)


def _clone_plan_as_admin_revision(base_plan, actor):
    """
    system draft(DRAFT)를 기반으로 admin 조정안(REVIEWING) 버전 생성.
    원본 draft는 보존한다.
    """
    if not base_plan:
        return None
    next_version = (
        ServiceSchedulePlan.objects.filter(submission=base_plan.submission)
        .order_by('-version')
        .values_list('version', flat=True)
        .first()
        or 0
    ) + 1

    cloned = ServiceSchedulePlan.objects.create(
        submission=base_plan.submission,
        quote=base_plan.quote,
        customer=base_plan.customer,
        status=ServiceSchedulePlan.Status.REVIEWING,
        source=ServiceSchedulePlan.Source.ADMIN,
        version=next_version,
        based_on=base_plan,
        created_by=actor,
        updated_by=actor,
    )
    base_items = list(
        base_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
        .order_by('sort_order', 'starts_at', 'id')
    )
    for it in base_items:
        ServiceScheduleItem.objects.create(
            schedule_plan=cloned,
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
    return cloned


def _schedule_stage_key(status):
    """UI/운영용 단계 키."""
    if status == ServiceSchedulePlan.Status.DRAFT:
        return 'system_draft'
    if status == ServiceSchedulePlan.Status.REVIEWING:
        return 'admin_adjusted_draft'
    if status == ServiceSchedulePlan.Status.FINALIZED:
        return 'lsa_sent_draft'
    if status in (ServiceSchedulePlan.Status.SENT, ServiceSchedulePlan.Status.ACTIVE):
        return 'finalized_execution_schedule'
    return 'unknown'


def _parse_iso_datetime_or_error(value, field_name):
    if value in (None, ''):
        return None, None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return None, f'Invalid datetime for {field_name}'
    else:
        return None, f'Invalid datetime for {field_name}'
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt, None


def _parse_anchor_date_or_today(raw_value):
    if not raw_value:
        return timezone.localdate()
    try:
        return date.fromisoformat(str(raw_value)[:10])
    except Exception:
        return timezone.localdate()


def _calendar_range(anchor_date, view_mode):
    mode = (view_mode or 'week').strip().lower()
    if mode == 'day':
        return anchor_date, anchor_date
    if mode == 'month':
        month_start = anchor_date.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1, day=1)
        return month_start, (next_month - timedelta(days=1))
    week_start = anchor_date - timedelta(days=anchor_date.weekday())
    return week_start, (week_start + timedelta(days=6))


def _matches_search(payload, q):
    if not q:
        return True
    fields = [
        payload.get('service_code') or '',
        payload.get('service_label') or '',
        payload.get('assigned_agent_name') or '',
        payload.get('notes') or '',
        payload.get('recommendation_reason') or '',
        payload.get('recommendation_source') or '',
        payload.get('status') or '',
    ]
    haystack = ' '.join(str(v).lower() for v in fields if v is not None)
    return q in haystack


def _get_paid_services(submission):
    """결제/송부된 견적의 서비스 코드·라벨 목록."""
    quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID),
        )
        .order_by('-updated_at')
        .first()
    )
    if not quote or not quote.items:
        return []
    out = []
    for it in quote.items:
        if not isinstance(it, dict):
            continue
        code = (it.get('code') or '').strip()
        if not code:
            continue
        out.append({'code': code, 'label': (it.get('label') or get_service_label(code))})
    return out


def _validate_agent_id(agent_id):
    """assigned_agent_id가 유효한 Agent인지."""
    if agent_id is None:
        return True
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        u = User.objects.get(pk=int(agent_id))
        return getattr(u, 'role', None) == User.Role.AGENT
    except (User.DoesNotExist, ValueError, TypeError):
        return False


def _resolve_candidate_agents(agent_ids):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    valid_ids = []
    for raw in agent_ids or []:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        valid_ids.append(aid)
    if not valid_ids:
        return []
    agents = list(
        User.objects.filter(
            id__in=valid_ids,
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
    )
    return agents


def _extract_submission_state_code(submission, request_data=None):
    payload = request_data or get_quote_input_data(submission)
    answers = getattr(submission, 'answers', None) or {}
    raw_region = str(
        payload.get('region')
        or payload.get('state')
        or answers.get('region')
        or answers.get('state')
        or ''
    ).strip()
    if not raw_region:
        return ''

    state_name_to_code = {
        str(name or '').strip().upper(): str(code or '').strip().upper()
        for code, name in (US_STATES or []) if code
    }
    known_state_codes = set(state_name_to_code.values())

    region_upper = raw_region.upper()
    if region_upper in known_state_codes:
        return region_upper
    if region_upper in state_name_to_code:
        return state_name_to_code[region_upper]

    tokens = [token for token in re.split(r'[^A-Z]+', region_upper) if token]
    for token in tokens:
        if token in known_state_codes:
            return token

    for state_name, code in state_name_to_code.items():
        if state_name and state_name in region_upper:
            return code
    return ''


def _resolve_candidate_agents_for_submission(submission, request_data=None):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    queryset = User.objects.filter(
        role=User.Role.AGENT,
        status=User.Status.ACTIVE,
    ).order_by('username')

    state_code = _extract_submission_state_code(submission, request_data=request_data)
    if not state_code:
        return [], ''
    candidates = []
    for agent in queryset:
        agent_states = {str(s or '').strip().upper() for s in (getattr(agent, 'agent_states', None) or []) if str(s or '').strip()}
        if state_code not in agent_states:
            continue
        candidates.append(agent)
    return candidates, state_code


def _agent_level_rank(level):
    order = {
        'BRONZE': 1,
        'SILVER': 2,
        'GOLD': 3,
        'DIAMOND': 4,
        'PLATINUM': 5,
    }
    return order.get(str(level or '').strip().upper(), 0)


def _serialize_lsa_candidate_agents(agent_list):
    service_map = {
        svc.id: svc.name
        for svc in SettlementService.objects.filter(is_active=True).only('id', 'name')
    }
    out = []
    for u in (agent_list or []):
        summary = u.get_agent_rating_summary() or {}
        score = float(u.agent_level_score) if getattr(u, 'agent_level_score', None) is not None else 0.0
        level = str(getattr(u, 'agent_level', '') or 'BRONZE').upper()
        service_names = [
            service_map.get(int(sid), str(sid))
            for sid in (getattr(u, 'agent_services', None) or [])
            if str(sid).isdigit()
        ]
        out.append({
            'id': u.id,
            'name': u.get_full_name() or u.username or str(u.email),
            'username': u.username,
            'badge': level,
            'agent_level': level,
            'agent_level_score': round(score, 2),
            'accept_rate': float(u.accept_rate) if getattr(u, 'accept_rate', None) is not None else None,
            'rating_avg': round(float(summary.get('avg') or 0.0), 2),
            'rating_count': int(summary.get('count') or 0),
            'states': list(getattr(u, 'agent_states', None) or []),
            'service_names': service_names[:10],
            'constraints': getattr(u, 'agent_level_constraints', None) if isinstance(getattr(u, 'agent_level_constraints', None), dict) else {},
        })
    out.sort(key=lambda row: (-_agent_level_rank(row.get('agent_level')), -(row.get('agent_level_score') or 0.0), row.get('name') or ''))
    return out


def _resolve_service_type_for_submission(submission, service_code):
    code = str(service_code or '').strip()
    if not code:
        return ServiceScheduleItem.ServiceType.AI_AGENT
    answers = getattr(submission, 'answers', None) or {}
    per_service = answers.get('service_delivery_per_service') or {}
    preference = str(per_service.get(code) or answers.get('service_delivery_preference') or '').strip()
    mapping = {
        'direct_search': ServiceScheduleItem.ServiceType.SELF_SEARCH,
        'ai_service': ServiceScheduleItem.ServiceType.AI_AGENT,
        'agent_direct': ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
    }
    return mapping.get(preference, ServiceScheduleItem.ServiceType.AI_AGENT)


def _check_overlaps(items_data, exclude_item_id=None):
    """
    items_data: list of {assigned_agent_id, starts_at, ends_at, id?}
    같은 agent에 대해 시간 겹침이 있으면 (item_id, message) 리스트 반환.
    """
    overlaps = []
    agent_slots = {}
    for it in items_data:
        aid = it.get('assigned_agent_id')
        if not aid:
            continue
        sid = it.get('id')
        if exclude_item_id and sid == exclude_item_id:
            continue
        start = it.get('starts_at')
        end = it.get('ends_at')
        if not start or not end:
            continue
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace('Z', '+00:00'))
        if isinstance(end, str):
            end = datetime.fromisoformat(end.replace('Z', '+00:00'))
        key = aid
        if key not in agent_slots:
            agent_slots[key] = []
        for existing in agent_slots[key]:
            if not (end <= existing['start'] or start >= existing['end']):
                overlaps.append({
                    'item_id': sid,
                    'message': '동일 Agent 시간 겹침',
                })
                break
        agent_slots[key].append({'start': start, 'end': end})
    return overlaps


@require_GET
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
@xframe_options_sameorigin
def submission_review_schedule(request, submission_id):
    """Admin: 제출별 스케줄 편집 페이지. 고객 요약, 결제 서비스, 플랜/항목, 미배정 풀 표시."""
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    customer_name = ''
    if submission.user_id:
        u = submission.user
        customer_name = (u.get_full_name() or u.username or u.email or '').strip() or submission.email
    else:
        customer_name = submission.email
    customer_summary = {
        'name': customer_name,
        'email': submission.email,
        'user_id': submission.user_id,
    }
    request_data = get_quote_input_data(submission)
    paid_services = _get_paid_services(submission)
    if not paid_services:
        # 견적(초안)에서라도 서비스 목록 표시
        quote_draft = (
            SettlementQuote.objects.filter(submission=submission).order_by('-updated_at').first()
        )
        if quote_draft and quote_draft.items:
            for it in quote_draft.items:
                if isinstance(it, dict) and (it.get('code') or '').strip():
                    paid_services.append({
                        'code': it.get('code', '').strip(),
                        'label': it.get('label') or get_service_label(it.get('code', '')),
                    })
    for svc in paid_services:
        svc['service_type'] = _resolve_service_type_for_submission(submission, svc['code'])
    schedule_plan = _get_schedule_plan_for_submission(submission)
    resolved_agents, candidate_state_code = _resolve_candidate_agents_for_submission(submission, request_data=request_data)
    agents = _serialize_lsa_candidate_agents(resolved_agents)
    availability_request_rows = []
    availability_overlap_rows = []
    if _can_view_internal_availability_responses(request.user):
        availability_request_rows = get_availability_requests_for_workbench(submission, schedule_plan=schedule_plan)
        availability_overlap_rows = get_availability_overlap_rows(submission, schedule_plan=schedule_plan, output_timezone='UTC')
    lsa_requests = list(
        LsaAgentRequest.objects.filter(batch__submission=submission)
        .select_related('target_agent', 'batch')
        .prefetch_related('responses')
        .order_by('-sent_at')[:30]
    )
    lsa_response_rows = []
    for req in lsa_requests:
        latest = req.responses.order_by('-revision').first()
        lsa_response_rows.append({
            'request_id': req.id,
            'batch_id': req.batch_id,
            'agent_name': (req.target_agent.get_full_name() or req.target_agent.username) if req.target_agent else f'#{req.target_agent_id}',
            'status': req.status,
            'sent_at': req.sent_at,
            'response_decision': latest.decision if latest else '',
            'response_revision': latest.revision if latest else None,
            'response_note': (latest.note or '') if latest else '',
        })
    embed_mode = str(request.GET.get('embed') or '').lower() in ('1', 'true', 'yes', 'y', 'on')

    return render(request, 'app/admin_schedule.html', {
        'submission': submission,
        'customer_summary': customer_summary,
        'request_summary': {
            'region': request_data.get('region') or '',
            'entry_date': request_data.get('entry_date') or '',
        },
        'paid_services': paid_services,
        'schedule_plan': schedule_plan,
        'is_schedule_editable': _is_plan_editable(schedule_plan),
        'schedule_stage_key': _schedule_stage_key(schedule_plan.status) if schedule_plan else '',
        'agents_json': json.dumps(agents, ensure_ascii=False),
        'paid_services_json': json.dumps(paid_services, ensure_ascii=False),
        'availability_request_rows': availability_request_rows,
        'availability_overlap_rows': availability_overlap_rows,
        'lsa_response_rows': lsa_response_rows,
        'candidate_state_code': candidate_state_code,
        'embed_mode': embed_mode,
    })


@require_GET
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_lsa_preview(request, submission_id, agent_id):
    """Admin: 특정 후보 Agent 기준 LSA proposal 포맷 미리보기."""
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_editable_schedule_plan_for_submission(submission) or _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '전송할 스케줄 플랜이 없습니다.'}, status=400)

    candidates, candidate_state_code = _resolve_candidate_agents_for_submission(submission, request_data=get_quote_input_data(submission))
    agent_by_id = {a.id: a for a in candidates}
    agent = agent_by_id.get(int(agent_id)) if str(agent_id).isdigit() else None
    if not agent:
        return JsonResponse({'ok': False, 'error': '해당 Agent는 현재 후보 목록에 없습니다.'}, status=404)

    try:
        payload = build_lsa_preview_payload(schedule_plan, agent)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    return JsonResponse({
        'ok': True,
        'candidate_state_code': candidate_state_code,
        'payload': payload,
    })


@require_http_methods(['GET', 'POST'])
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_api(request, submission_id):
    """
    GET: 현재 플랜 + 항목(배정된 것 + 미배정) JSON.
    POST: items 배열로 저장. overlap/agent 검증 후 ServiceScheduleItem 갱신.
    """
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if request.method == 'GET':
        view_mode = (request.GET.get('view') or 'week').strip().lower()
        if view_mode not in ('day', 'week', 'month'):
            view_mode = 'week'
        search_q = (request.GET.get('q') or '').strip().lower()
        anchor_date = _parse_anchor_date_or_today(request.GET.get('anchor_date'))
        range_start, range_end = _calendar_range(anchor_date, view_mode)

        if not schedule_plan:
            return JsonResponse({
                'plan': None,
                'items': [],
                'unscheduled': [],
                'items_in_view': [],
                'calendar_view': {
                    'mode': view_mode,
                    'anchor_date': anchor_date.isoformat(),
                    'range_start': range_start.isoformat(),
                    'range_end': range_end.isoformat(),
                },
            })
        items = list(
            schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
            .order_by('sort_order', 'starts_at', 'id')
            .select_related('assigned_agent')
        )
        scheduled = []
        unscheduled = []
        for it in items:
            rec_meta = it.recommendation_metadata if isinstance(it.recommendation_metadata, dict) else {}
            payload = {
                'id': it.id,
                'service_code': it.service_code,
                'service_label': it.service_label or it.service_code,
                'service_type': it.service_type or '',
                'starts_at': it.starts_at.isoformat() if it.starts_at else None,
                'ends_at': it.ends_at.isoformat() if it.ends_at else None,
                'duration_minutes': it.duration_minutes,
                'assigned_agent_id': it.assigned_agent_id,
                'assigned_agent_name': (it.assigned_agent.get_full_name() or it.assigned_agent.username) if it.assigned_agent else None,
                'status': it.status,
                'notes': it.notes or '',
                'confidence_score': float(it.source_score) if it.source_score is not None else None,
                'recommendation_reason': it.source_reason or '',
                'recommendation_source': it.recommendation_source or 'fallback',
                'evidence_type': rec_meta.get('evidence_type'),
                'similar_historical_sample_count': rec_meta.get('similar_historical_sample_count'),
                'suggested_day_offset_from_entry': rec_meta.get('suggested_day_offset_from_entry'),
                'remaining_days_band': rec_meta.get('remaining_days_band'),
                'remaining_days_value': rec_meta.get('remaining_days_value'),
                'recommendation_metadata': rec_meta,
                'needs_admin_review': bool(it.needs_admin_review),
                'sort_order': it.sort_order,
            }
            if it.starts_at and it.ends_at:
                scheduled.append(payload)
            else:
                unscheduled.append(payload)

        if search_q:
            scheduled = [row for row in scheduled if _matches_search(row, search_q)]
            unscheduled = [row for row in unscheduled if _matches_search(row, search_q)]

        items_in_view = []
        for row in scheduled:
            if not row.get('starts_at'):
                continue
            try:
                dt = datetime.fromisoformat(str(row['starts_at']).replace('Z', '+00:00'))
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt)
                d = dt.date()
                if range_start <= d <= range_end:
                    items_in_view.append(row)
            except Exception:
                continue

        calendar_items = serialize_schedule_items_for_calendar(schedule_plan)
        return JsonResponse({
            'plan': {
                'id': schedule_plan.id,
                'status': schedule_plan.status,
                'version': schedule_plan.version,
                'source': schedule_plan.source,
                'based_on_id': schedule_plan.based_on_id,
                'editable': _is_plan_editable(schedule_plan),
                'stage_key': _schedule_stage_key(schedule_plan.status),
            },
            'items': scheduled,
            'unscheduled': unscheduled,
            'items_in_view': items_in_view,
            'calendar_items': calendar_items,
            'calendar_view': {
                'mode': view_mode,
                'anchor_date': anchor_date.isoformat(),
                'range_start': range_start.isoformat(),
                'range_end': range_end.isoformat(),
                'search_q': search_q,
            },
        })

    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()

    # POST: save items
    try:
        body = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    items_payload = body.get('items')
    if items_payload is None:
        return JsonResponse({'ok': False, 'error': 'items required'}, status=400)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': 'No schedule plan. Generate draft first.'}, status=400)
    if schedule_plan.status in (ServiceSchedulePlan.Status.FINALIZED, ServiceSchedulePlan.Status.SENT, ServiceSchedulePlan.Status.ACTIVE):
        return JsonResponse({'ok': False, 'error': '이미 확정/송부된 일정은 직접 수정할 수 없습니다.'}, status=409)

    editable_plan = _get_editable_schedule_plan_for_submission(submission)
    if not editable_plan:
        return JsonResponse({'ok': False, 'error': '편집 가능한 draft가 없습니다.'}, status=409)
    if editable_plan.status == ServiceSchedulePlan.Status.DRAFT:
        editable_plan = _clone_plan_as_admin_revision(editable_plan, request.user)
        if not editable_plan:
            return JsonResponse({'ok': False, 'error': 'admin 조정안 생성에 실패했습니다.'}, status=500)

    payload_rows = []
    # Validate agents
    for it in items_payload:
        obj = None
        raw_id = it.get('id')
        if raw_id not in (None, ''):
            obj = ServiceScheduleItem.objects.filter(pk=raw_id, schedule_plan=editable_plan).first()
            if not obj:
                obj = ServiceScheduleItem.objects.filter(schedule_plan=editable_plan, based_on_item_id=raw_id).first()
            if not obj:
                return JsonResponse({'ok': False, 'error': f'Item not found in editable draft: {raw_id}'}, status=400)
        service_code = str(it.get('service_code') or '').strip()
        service_label = str(it.get('service_label') or '').strip()
        if not obj and not service_code:
            return JsonResponse({'ok': False, 'error': 'New item requires service_code.'}, status=400)
        aid = it.get('assigned_agent_id')
        if aid is not None and aid != '':
            if not _validate_agent_id(aid):
                return JsonResponse({'ok': False, 'error': f'Invalid agent id: {aid}'}, status=400)
        else:
            it['assigned_agent_id'] = None
        start, start_err = _parse_iso_datetime_or_error(it.get('starts_at'), 'starts_at')
        if start_err:
            return JsonResponse({'ok': False, 'error': start_err}, status=400)
        end, end_err = _parse_iso_datetime_or_error(it.get('ends_at'), 'ends_at')
        if end_err:
            return JsonResponse({'ok': False, 'error': end_err}, status=400)
        if bool(start) ^ bool(end):
            return JsonResponse({'ok': False, 'error': 'starts_at and ends_at must be provided together.'}, status=400)
        if start and end and end <= start:
            return JsonResponse({'ok': False, 'error': 'ends_at must be after starts_at.'}, status=400)
        payload_rows.append({
            'obj': obj,
            'starts_at': start,
            'ends_at': end,
            'duration_minutes': it.get('duration_minutes'),
            'assigned_agent_id': it.get('assigned_agent_id'),
            'notes': it.get('notes'),
            'status': it.get('status'),
            'needs_admin_review': it.get('needs_admin_review'),
            'service_code': service_code,
            'service_label': service_label,
        })

    normalized_for_overlap = [
        {
            'id': row['obj'].id if row['obj'] else None,
            'assigned_agent_id': row['assigned_agent_id'],
            'starts_at': row['starts_at'],
            'ends_at': row['ends_at'],
        }
        for row in payload_rows
    ]
    # Validate overlaps
    overlaps = _check_overlaps(normalized_for_overlap)
    if overlaps:
        return JsonResponse({'ok': False, 'error': overlaps[0].get('message', 'Overlap'), 'overlaps': overlaps}, status=400)
    # Persist
    updated = 0
    max_sort_order = editable_plan.items.aggregate(max_sort=models.Max('sort_order')).get('max_sort') or 0
    for row in payload_rows:
        obj = row['obj']
        start = row['starts_at']
        end = row['ends_at']
        aid = row['assigned_agent_id']
        if obj:
            obj.starts_at = start
            obj.ends_at = end
            obj.duration_minutes = row['duration_minutes'] or obj.duration_minutes or 60
            obj.assigned_agent_id = int(aid) if aid else None
            obj.notes = (row['notes'] or '')[:500]
            obj.status = row['status'] or obj.status
            if row['needs_admin_review'] is not None:
                obj.needs_admin_review = bool(row['needs_admin_review'])
            obj.save(update_fields=['starts_at', 'ends_at', 'duration_minutes', 'assigned_agent_id', 'notes', 'status', 'needs_admin_review'])
        else:
            max_sort_order += 1
            service_code = row['service_code']
            ServiceScheduleItem.objects.create(
                schedule_plan=editable_plan,
                service_code=service_code,
                service_label=row['service_label'] or get_service_label(service_code) or service_code,
                service_type=_resolve_service_type_for_submission(submission, service_code),
                starts_at=start,
                ends_at=end,
                duration_minutes=row['duration_minutes'] or 60,
                assigned_agent_id=int(aid) if aid else None,
                notes=(row['notes'] or '')[:500],
                status=row['status'] or ServiceScheduleItem.ItemStatus.SCHEDULED,
                needs_admin_review=bool(row['needs_admin_review']) if row['needs_admin_review'] is not None else False,
                recommendation_source='fallback',
                sort_order=max_sort_order,
            )
        updated += 1
    editable_plan.updated_by = request.user
    editable_plan.save(update_fields=['updated_by', 'updated_at'])
    return JsonResponse({'ok': True, 'updated': updated, 'plan_id': editable_plan.id, 'plan_status': editable_plan.status})


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_generate_draft(request, submission_id):
    """ML/규칙 기반 스케줄 초안 생성. 기존 DRAFT 플랜이 있으면 새로 만들지 않고 기존 사용 가능(재생성 시 새 플랜)."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    if not submission.user_id:
        return JsonResponse({'ok': False, 'error': '제출에 연결된 고객 계정이 없습니다.'}, status=400)
    try:
        plan = generate_schedule_draft(submission, quote=None, plan=None, actor=request.user)
        return JsonResponse({'ok': True, 'plan_id': plan.id, 'message': '스케줄 초안을 생성했습니다.'})
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_regenerate_unscheduled(request, submission_id):
    """미배정 항목만 스케줄 엔진으로 다시 제안. 기존 플랜의 starts_at/ends_at 없는 항목에 대해 suggest_placements만 재적용 가능.
    현재는 단순히 'generate draft'로 전체 재생성 후 기존 수정은 덮어쓰이므로, 옵션으로 'unscheduled only' 시 기존 플랜 유지하고
    미배정 항목에 대해 새 날짜만 제안하는 API. 간단 구현: 미배정 항목의 sort_order 기준으로 entry_date 이후 순차 배치."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '플랜이 없습니다. 먼저 초안을 생성하세요.'}, status=400)
    from survey.quote_input import get_quote_input_data
    from settlement.scheduling_engine import parse_entry_date
    request_data = get_quote_input_data(submission)
    entry_date = parse_entry_date(request_data.get('entry_date'))
    base = entry_date or timezone.now().date()
    if base < timezone.now().date():
        base = timezone.now().date()
    unscheduled = list(
        schedule_plan.items.filter(
            status__in=(ServiceScheduleItem.ItemStatus.SCHEDULED, ServiceScheduleItem.ItemStatus.CONFIRMED),
            starts_at__isnull=True,
        ).order_by('sort_order', 'id')
    )
    if not unscheduled:
        return JsonResponse({'ok': True, 'updated': 0, 'message': '미배정 항목이 없습니다.'})
    current_date = base
    for it in unscheduled:
        start_dt = timezone.make_aware(datetime.combine(current_date, time(9, 0)))
        end_dt = start_dt + timedelta(minutes=it.duration_minutes or 60)
        it.starts_at = start_dt
        it.ends_at = end_dt
        it.save(update_fields=['starts_at', 'ends_at'])
        current_date = current_date + timedelta(days=1)
    return JsonResponse({'ok': True, 'updated': len(unscheduled), 'message': f'{len(unscheduled)}건 미배정 항목을 배치했습니다.'})


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_regenerate_agent_dependent(request, submission_id):
    """대면 Agent 서비스 항목만 가용 창 + scoring으로 재배치."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '편집 중인 플랜이 없습니다.'}, status=400)
    try:
        updated = regenerate_agent_dependent_items(schedule_plan, submission)
        return JsonResponse({'ok': True, 'updated': updated, 'message': f'Agent 배정 항목 {updated}건을 재배치했습니다.'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_request_availability(request, submission_id):
    """대면 Agent 서비스로 배정된 Agent들에게 가용 시간 입력 요청(메시지+이메일) 발송."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_editable_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '편집 중인 플랜이 없습니다.'}, status=400)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    agent_ids = get_agents_needing_availability(schedule_plan)
    if not agent_ids:
        return JsonResponse({'ok': False, 'error': '대면 Agent로 배정된 항목이 없습니다.'}, status=400)
    sent = 0
    customer_notified = send_availability_request_to_customer(submission, actor=request.user)
    for aid in agent_ids:
        try:
            agent = User.objects.get(pk=aid)
            if send_availability_request_to_agent(schedule_plan, agent, actor=request.user):
                sent += 1
        except User.DoesNotExist:
            pass
    if sent and schedule_plan.status in (ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING):
        schedule_plan.status = ServiceSchedulePlan.Status.FINALIZED
        schedule_plan.updated_by = request.user
        schedule_plan.save(update_fields=['status', 'updated_by', 'updated_at'])
    if sent:
        submission.advance_case_stage(submission.CaseStage.AVAILABILITY_REQUESTED)
    customer_msg = ' 고객 요청도 생성했습니다.' if customer_notified else ''
    return JsonResponse({'ok': True, 'sent': sent, 'message': f'{sent}명의 Agent에게 가용 시간 입력 요청을 보냈습니다.{customer_msg}'})


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_send_lsa(request, submission_id):
    """Admin: 현재 조정안 스케줄을 스냅샷으로 LSA 배치 발송."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    editable = _get_editable_schedule_plan_for_submission(submission)
    schedule_plan = editable or _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '전송할 스케줄 플랜이 없습니다.'}, status=400)

    request_data = get_quote_input_data(submission)
    agents, candidate_state_code = _resolve_candidate_agents_for_submission(submission, request_data=request_data)
    if not agents:
        if candidate_state_code:
            return JsonResponse({'ok': False, 'error': f'{candidate_state_code} 주에 해당하는 활성 Agent가 없습니다.'}, status=400)
        return JsonResponse({'ok': False, 'error': '동일 주(State) 정보를 찾을 수 없어 발송 가능한 Agent가 없습니다.'}, status=400)

    try:
        batch, requests = send_lsa_batch_for_schedule_plan(schedule_plan, agents, actor=request.user)
    except PermissionError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    submission.advance_case_stage(submission.CaseStage.LSA_PENDING)

    return JsonResponse({
        'ok': True,
        'batch_id': batch.id,
        'schedule_plan_id': batch.schedule_plan_id,
        'schedule_version': batch.schedule_version,
        'candidate_state_code': candidate_state_code,
        'sent_count': len(requests),
        'message': f'LSA 배치 #{batch.id}를 {len(requests)}명에게 발송했습니다.',
    })


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_finalize(request, submission_id):
    """플랜을 FINALIZED → SENT로 하고 고객에게 일정 전달. UserSettlementPlan.service_schedule 동기화(호환 유지). 고객 앱 메시지·이메일 발송 및 SCHEDULE_SENT 이벤트 기록."""
    from survey.models import SurveySubmissionEvent
    from settlement.notifications import send_schedule_sent_to_customer
    from translations.utils import get_request_language
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '편집 중인 플랜이 없습니다.'}, status=400)
    if schedule_plan.status in (ServiceSchedulePlan.Status.SENT, ServiceSchedulePlan.Status.ACTIVE):
        return JsonResponse({'ok': False, 'error': '이미 고객에게 송부된 일정입니다.'}, status=409)
    schedule_plan.status = ServiceSchedulePlan.Status.FINALIZED
    schedule_plan.updated_by = request.user
    schedule_plan.save(update_fields=['status', 'updated_by', 'updated_at'])
    legacy = plan_to_legacy_schedule(schedule_plan, customer_safe=True)
    if submission.user_id and legacy:
        try:
            plan = UserSettlementPlan.objects.get(user_id=submission.user_id)
            plan.service_schedule = legacy
            plan.save(update_fields=['service_schedule', 'updated_at'])
        except UserSettlementPlan.DoesNotExist:
            UserSettlementPlan.objects.create(
                user_id=submission.user_id,
                service_schedule=legacy,
            )
    schedule_plan.status = ServiceSchedulePlan.Status.SENT
    schedule_plan.save(update_fields=['status', 'updated_at'])
    lang = get_request_language(request)
    if getattr(submission, 'user', None) and getattr(submission.user, 'preferred_language', None):
        lang = (submission.user.preferred_language or lang) or 'ko'
    send_schedule_sent_to_customer(submission, language_code=lang)
    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=SurveySubmissionEvent.EventType.SCHEDULE_SENT,
        created_by=request.user,
        meta={'schedule_plan_id': schedule_plan.id},
    )
    submission.advance_case_stage(submission.CaseStage.SCHEDULE_FINALIZED)
    return JsonResponse({'ok': True, 'message': '일정을 확정하고 고객에게 반영했습니다.'})


@require_GET
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_lsa_batch_review(request, submission_id, batch_id):
    """Admin: 동일 admin draft 기준으로 수신된 Agent 응답 비교/선정 페이지."""
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    batch = get_object_or_404(
        LsaSourcingBatch.objects.select_related('schedule_plan', 'selected_request__target_agent').prefetch_related(
            'agent_requests__target_agent',
            'agent_requests__responses__items',
            'contract',
        ),
        id=batch_id,
        submission=submission,
    )

    pricing_by_code = {
        (row.get('service_code') or ''): row
        for row in (batch.internal_pricing_snapshot or [])
        if isinstance(row, dict)
    }
    requests = list(batch.agent_requests.all().order_by('id'))
    response_rows = []
    for req in requests:
        latest = req.responses.order_by('-revision').first()
        items = list(latest.items.all()) if latest else []
        accepted_count = sum(1 for it in items if it.action == LsaAgentResponseItem.Action.ACCEPT)
        suggested_count = sum(1 for it in items if it.action == LsaAgentResponseItem.Action.SUGGEST_CHANGE)
        conflict_count = sum(1 for it in items if it.action == LsaAgentResponseItem.Action.UNAVAILABLE)
        item_rows = []
        for it in items:
            item_rows.append({
                'service_code': it.service_code,
                'service_label': it.service_label or it.service_code,
                'action': it.action,
                'proposed_starts_at': it.proposed_starts_at,
                'proposed_ends_at': it.proposed_ends_at,
                'suggested_starts_at': it.suggested_starts_at,
                'suggested_ends_at': it.suggested_ends_at,
                'note': it.note or '',
                'pricing': pricing_by_code.get(it.service_code) or {},
            })

        response_rows.append({
            'request': req,
            'latest_response': latest,
            'accepted_count': accepted_count,
            'suggested_count': suggested_count,
            'conflict_count': conflict_count,
            'item_rows': item_rows,
            'can_select': bool(latest) and req.status == LsaAgentRequest.Status.RESPONDED and not bool(batch.selected_request_id),
        })

    execution_items = []
    contract = getattr(batch, 'contract', None)
    execution_plan = getattr(contract, 'execution_schedule_plan', None) if contract else None
    if execution_plan:
        for it in execution_plan.items.order_by('sort_order', 'starts_at', 'id').select_related('assigned_agent'):
            execution_items.append({
                'service_code': it.service_code,
                'service_label': it.service_label or it.service_code,
                'starts_at': it.starts_at,
                'ends_at': it.ends_at,
                'assigned_agent_name': (it.assigned_agent.get_full_name() or it.assigned_agent.username) if it.assigned_agent else '',
                'recommendation_source': it.recommendation_source or '',
                'recommendation_reason': it.source_reason or '',
                'notes': it.notes or '',
            })

    return render(request, 'app/admin_lsa_batch_review.html', {
        'submission': submission,
        'batch': batch,
        'response_rows': response_rows,
        'draft_schedule': batch.proposed_schedule_snapshot or [],
        'contract': contract,
        'execution_items': execution_items,
    })


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_lsa_select_agent(request, submission_id, batch_id):
    """Admin: 후보 응답 비교 후 최종 Agent 1명 선정/계약."""
    if not _can_optimize_and_send_schedule(request.user):
        return _schedule_action_forbidden_response()
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    batch = get_object_or_404(LsaSourcingBatch, id=batch_id, submission=submission)

    import json
    try:
        body = json.loads(request.body or '{}')
    except Exception:
        body = {}

    request_id = body.get('request_id')
    response_id = body.get('response_id')
    note = (body.get('note') or '').strip()

    if not request_id:
        return JsonResponse({'ok': False, 'error': 'request_id required'}, status=400)

    try:
        contract = select_lsa_agent_for_contract(
            batch_id=batch.id,
            request_id=int(request_id),
            response_id=int(response_id) if response_id else None,
            actor=request.user,
            note=note,
        )
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=409)
    except PermissionError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except LsaAgentRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'invalid request'}, status=400)
    except LsaAgentResponse.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'invalid response'}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    return JsonResponse({
        'ok': True,
        'contract_id': contract.id,
        'execution_plan_id': contract.execution_schedule_plan_id,
        'batch_id': batch.id,
        'selected_request_id': contract.selected_request_id,
        'selected_agent_id': contract.selected_agent_id,
        'message': '최종 Agent를 선정하고 계약 레코드를 생성했습니다.',
    })

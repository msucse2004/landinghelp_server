"""
Admin 스케줄 UI: ServiceSchedulePlan/Item 기반 달력 페이지 및 API.
고객 대면 달력(customer_dashboard 등)은 변경하지 않음.
"""
from datetime import datetime, date, time, timedelta
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie

from config.views import _staff_required
from survey.models import SurveySubmission
from survey.quote_input import get_quote_input_data
from settlement.constants import get_service_label
from settlement.models import (
    ServiceSchedulePlan,
    ServiceScheduleItem,
    SettlementQuote,
    UserSettlementPlan,
)
from settlement.scheduling_engine import generate_schedule_draft, regenerate_agent_dependent_items
from settlement.schedule_utils import plan_to_legacy_schedule, serialize_schedule_items_for_calendar
from settlement.availability_request import get_agents_needing_availability, send_availability_request_to_agent
from settlement.models import AgentAvailabilityWindow


def _get_schedule_plan_for_submission(submission):
    """제출에 대한 현재 편집 대상 플랜: DRAFT 또는 REVIEWING, 최신 1건."""
    return (
        ServiceSchedulePlan.objects.filter(
            submission=submission,
            status__in=(ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING),
        )
        .order_by('-updated_at')
        .select_related('quote', 'customer')
        .first()
    )


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
    schedule_plan = _get_schedule_plan_for_submission(submission)
    agents = []
    from django.contrib.auth import get_user_model
    User = get_user_model()
    for u in User.objects.filter(role=User.Role.AGENT, status=User.Status.ACTIVE).order_by('username')[:100]:
        agents.append({'id': u.id, 'name': u.get_full_name() or u.username or str(u.email)})
    availability_by_agent = []
    if schedule_plan:
        windows = list(
            AgentAvailabilityWindow.objects.filter(
                schedule_plan=schedule_plan,
                status=AgentAvailabilityWindow.WindowStatus.AVAILABLE,
            )
            .order_by('agent_id', 'starts_at')
            .select_related('agent')
        )
        from itertools import groupby
        for agent_id, group in groupby(windows, key=lambda w: w.agent_id):
            grp = list(group)
            agent_obj = grp[0].agent if grp else None
            availability_by_agent.append({
                'agent_id': agent_id,
                'agent_name': (agent_obj.get_full_name() or agent_obj.username) if agent_obj else '',
                'windows': [{'starts_at': w.starts_at, 'ends_at': w.ends_at, 'source': w.get_source_display()} for w in grp],
            })
    return render(request, 'app/admin_schedule.html', {
        'submission': submission,
        'customer_summary': customer_summary,
        'request_summary': {
            'region': request_data.get('region') or '',
            'entry_date': request_data.get('entry_date') or '',
        },
        'paid_services': paid_services,
        'schedule_plan': schedule_plan,
        'agents_json': agents,
        'availability_by_agent': availability_by_agent,
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
        if not schedule_plan:
            return JsonResponse({
                'plan': None,
                'items': [],
                'unscheduled': [],
            })
        items = list(
            schedule_plan.items.exclude(status=ServiceScheduleItem.ItemStatus.CANCELLED)
            .order_by('sort_order', 'starts_at', 'id')
            .select_related('assigned_agent')
        )
        scheduled = []
        unscheduled = []
        for it in items:
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
                'sort_order': it.sort_order,
            }
            if it.starts_at and it.ends_at:
                scheduled.append(payload)
            else:
                unscheduled.append(payload)
        calendar_items = serialize_schedule_items_for_calendar(schedule_plan)
        return JsonResponse({
            'plan': {
                'id': schedule_plan.id,
                'status': schedule_plan.status,
                'version': schedule_plan.version,
            },
            'items': scheduled,
            'unscheduled': unscheduled,
            'calendar_items': calendar_items,
        })

    # POST: save items
    import json
    try:
        body = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    items_payload = body.get('items')
    if items_payload is None:
        return JsonResponse({'ok': False, 'error': 'items required'}, status=400)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': 'No schedule plan. Generate draft first.'}, status=400)
    # Validate agents
    for it in items_payload:
        aid = it.get('assigned_agent_id')
        if aid is not None and aid != '':
            if not _validate_agent_id(aid):
                return JsonResponse({'ok': False, 'error': f'Invalid agent id: {aid}'}, status=400)
        else:
            it['assigned_agent_id'] = None
    # Validate overlaps
    overlaps = _check_overlaps(items_payload)
    if overlaps:
        return JsonResponse({'ok': False, 'error': overlaps[0].get('message', 'Overlap'), 'overlaps': overlaps}, status=400)
    # Persist
    updated = 0
    for it in items_payload:
        pk = it.get('id')
        if not pk:
            continue
        try:
            obj = ServiceScheduleItem.objects.get(pk=pk, schedule_plan=schedule_plan)
        except ServiceScheduleItem.DoesNotExist:
            continue
        start = it.get('starts_at')
        end = it.get('ends_at')
        if start and isinstance(start, str):
            try:
                start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                if timezone.is_naive(start):
                    start = timezone.make_aware(start)
            except Exception:
                start = None
        if end and isinstance(end, str):
            try:
                end = datetime.fromisoformat(end.replace('Z', '+00:00'))
                if timezone.is_naive(end):
                    end = timezone.make_aware(end)
            except Exception:
                end = None
        obj.starts_at = start
        obj.ends_at = end
        obj.duration_minutes = it.get('duration_minutes') or obj.duration_minutes or 60
        aid = it.get('assigned_agent_id')
        obj.assigned_agent_id = int(aid) if aid else None
        obj.notes = (it.get('notes') or '')[:500]
        obj.status = it.get('status') or obj.status
        obj.save(update_fields=['starts_at', 'ends_at', 'duration_minutes', 'assigned_agent_id', 'notes', 'status'])
        updated += 1
    return JsonResponse({'ok': True, 'updated': updated})


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_generate_draft(request, submission_id):
    """ML/규칙 기반 스케줄 초안 생성. 기존 DRAFT 플랜이 있으면 새로 만들지 않고 기존 사용 가능(재생성 시 새 플랜)."""
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
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '편집 중인 플랜이 없습니다.'}, status=400)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    agent_ids = get_agents_needing_availability(schedule_plan)
    if not agent_ids:
        return JsonResponse({'ok': False, 'error': '대면 Agent로 배정된 항목이 없습니다.'}, status=400)
    sent = 0
    for aid in agent_ids:
        try:
            agent = User.objects.get(pk=aid)
            if send_availability_request_to_agent(schedule_plan, agent):
                sent += 1
        except User.DoesNotExist:
            pass
    return JsonResponse({'ok': True, 'sent': sent, 'message': f'{sent}명의 Agent에게 가용 시간 입력 요청을 보냈습니다.'})


@require_POST
@login_required
@user_passes_test(_staff_required, login_url='/login/')
@ensure_csrf_cookie
def submission_review_schedule_finalize(request, submission_id):
    """플랜을 FINALIZED → SENT로 하고 고객에게 일정 전달. UserSettlementPlan.service_schedule 동기화(호환 유지). 고객 앱 메시지·이메일 발송 및 SCHEDULE_SENT 이벤트 기록."""
    from survey.models import SurveySubmissionEvent
    from settlement.notifications import send_schedule_sent_to_customer
    from translations.utils import get_request_language
    submission = get_object_or_404(SurveySubmission, id=submission_id)
    schedule_plan = _get_schedule_plan_for_submission(submission)
    if not schedule_plan:
        return JsonResponse({'ok': False, 'error': '편집 중인 플랜이 없습니다.'}, status=400)
    schedule_plan.status = ServiceSchedulePlan.Status.FINALIZED
    schedule_plan.updated_by = request.user
    schedule_plan.save(update_fields=['status', 'updated_by', 'updated_at'])
    legacy = plan_to_legacy_schedule(schedule_plan)
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
    return JsonResponse({'ok': True, 'message': '일정을 확정하고 고객에게 반영했습니다.'})

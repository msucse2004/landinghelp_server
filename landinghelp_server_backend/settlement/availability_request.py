import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import (
    AvailabilityRequest,
    AvailabilityResponse,
    AvailabilitySlot,
    ServiceScheduleItem,
    ServiceSchedulePlan,
    UserSettlementPlan,
)

logger = logging.getLogger(__name__)

REFERENCE_MONDAY = date(2024, 1, 1)
COMMON_TIMEZONES = (
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Asia/Seoul',
)


def get_common_timezones():
    return list(COMMON_TIMEZONES)


def _request_base_queryset(submission, schedule_plan=None):
    qs = AvailabilityRequest.objects.filter(submission=submission)
    if schedule_plan is not None:
        qs = qs.filter(Q(schedule_plan=schedule_plan) | Q(schedule_plan__isnull=True))
    return qs


def _latest_schedule_plan_for_submission(submission):
    if not submission:
        return None
    return (
        ServiceSchedulePlan.objects.filter(submission=submission)
        .order_by('-updated_at')
        .first()
    )


def _target_agent_ids(submission, schedule_plan=None):
    agent_ids = set()
    if schedule_plan:
        agent_ids.update(
            aid for aid in schedule_plan.items.exclude(assigned_agent_id__isnull=True)
            .values_list('assigned_agent_id', flat=True)
            if aid
        )
    try:
        plan = UserSettlementPlan.objects.filter(user=getattr(submission, 'user', None)).select_related('assigned_agent').first()
        if plan and plan.assigned_agent_id:
            agent_ids.add(plan.assigned_agent_id)
    except Exception:
        pass
    if not agent_ids:
        latest_plan = _latest_schedule_plan_for_submission(submission)
        if latest_plan and (schedule_plan is None or latest_plan.id != getattr(schedule_plan, 'id', None)):
            agent_ids.update(
                aid for aid in latest_plan.items.exclude(assigned_agent_id__isnull=True)
                .values_list('assigned_agent_id', flat=True)
                if aid
            )
    return sorted(agent_ids)


def get_agents_needing_availability(schedule_plan):
    if not schedule_plan:
        return []
    return sorted(
        aid for aid in schedule_plan.items.filter(
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            assigned_agent_id__isnull=False,
        ).values_list('assigned_agent_id', flat=True).distinct()
        if aid
    )


def _get_system_sender():
    from .notifications import _get_system_sender as _notification_system_sender

    return _notification_system_sender()


def _get_workspace_conversation(submission, participant_role, target_user=None):
    from messaging.models import Conversation
    from .notifications import _get_or_create_workspace_conversation

    workspace_type = Conversation.WorkspaceType.HQ_BACKOFFICE
    if participant_role == AvailabilityRequest.ParticipantRole.AGENT:
        workspace_type = Conversation.WorkspaceType.LOCAL_EXECUTION
    return _get_or_create_workspace_conversation(
        submission,
        workspace_type,
        subject_fallback='가용 시간 요청',
        agent=target_user if participant_role == AvailabilityRequest.ParticipantRole.AGENT else None,
    )


def build_internal_availability_link(availability_request, request=None):
    path = reverse('availability_request_input', kwargs={'request_id': availability_request.id})
    base = ''
    if request is not None:
        try:
            return request.build_absolute_uri(path)
        except Exception:
            pass
    if getattr(settings, 'SITE_URL', None):
        base = (settings.SITE_URL or '').strip().rstrip('/')
    return (base + path) if base else path


def _message_body_for_request(availability_request):
    role_label = availability_request.get_participant_role_display()
    link = build_internal_availability_link(availability_request)
    return '\n'.join([
        f'{role_label} 가용 시간 요청이 생성되었습니다.',
        '아래 내부 페이지에서 가능한 요일과 시간을 제출해 주세요.',
        link,
        '',
        '반복 가능한 요일/시간 기준으로 여러 개를 등록할 수 있습니다.',
    ])


def _notify_availability_request(availability_request):
    if not availability_request or not availability_request.submission_id:
        return False

    try:
        from messaging.models import ConversationParticipant, Message

        conv = _get_workspace_conversation(
            availability_request.submission,
            availability_request.participant_role,
            target_user=availability_request.target_user,
        )
        ConversationParticipant.objects.get_or_create(
            conversation=conv,
            user=availability_request.target_user,
        )
        sender = _get_system_sender()
        if not sender:
            return False
        Message.objects.create(
            conversation=conv,
            sender=sender,
            body=_message_body_for_request(availability_request),
        )
        return True
    except Exception as exc:
        logger.warning(
            'Availability request notification failed: request_id=%s error=%s',
            getattr(availability_request, 'id', None),
            exc,
            exc_info=True,
        )
        return False


@transaction.atomic
def _get_or_create_availability_request(
    *,
    submission,
    target_user,
    participant_role,
    schedule_plan=None,
    timezone_name='UTC',
    requested_by=None,
    message='',
):
    existing = (
        _request_base_queryset(submission, schedule_plan=schedule_plan)
        .filter(
            target_user=target_user,
            participant_role=participant_role,
            status__in=[
                AvailabilityRequest.Status.OPEN,
                AvailabilityRequest.Status.RESPONDED,
            ],
        )
        .order_by('-created_at')
        .first()
    )
    if existing:
        changed_fields = []
        if schedule_plan and existing.schedule_plan_id != schedule_plan.id:
            existing.schedule_plan = schedule_plan
            changed_fields.append('schedule_plan')
        if timezone_name and existing.timezone_name != timezone_name:
            existing.timezone_name = timezone_name
            changed_fields.append('timezone_name')
        if requested_by and existing.requested_by_id != requested_by.id:
            existing.requested_by = requested_by
            changed_fields.append('requested_by')
        if message and existing.message != message:
            existing.message = message
            changed_fields.append('message')
        if changed_fields:
            changed_fields.append('updated_at')
            existing.save(update_fields=changed_fields)
        return existing, False

    created = AvailabilityRequest.objects.create(
        submission=submission,
        schedule_plan=schedule_plan,
        target_user=target_user,
        participant_role=participant_role,
        timezone_name=timezone_name or 'UTC',
        requested_by=requested_by,
        message=message or '',
    )
    return created, True


@transaction.atomic
def create_post_payment_availability_requests(submission, actor=None, schedule_plan=None, notify=True):
    if not submission:
        raise ValueError('submission is required')

    schedule_plan = schedule_plan or _latest_schedule_plan_for_submission(submission)
    timezone_name = 'UTC'

    customer_request = None
    created_count = 0
    notified_count = 0
    customer = getattr(submission, 'user', None)
    if customer and getattr(customer, 'is_authenticated', True):
        customer_request, customer_created = _get_or_create_availability_request(
            submission=submission,
            target_user=customer,
            participant_role=AvailabilityRequest.ParticipantRole.CUSTOMER,
            schedule_plan=schedule_plan,
            timezone_name=timezone_name,
            requested_by=actor,
            message='고객 가용 시간 수집',
        )
        created_count += 1 if customer_created else 0
        if notify and _notify_availability_request(customer_request):
            notified_count += 1

    agent_requests = []
    from django.contrib.auth import get_user_model
    User = get_user_model()
    agent_ids = _target_agent_ids(submission, schedule_plan=schedule_plan)
    if schedule_plan:
        plan_agent_ids = get_agents_needing_availability(schedule_plan)
        agent_ids = sorted(set(agent_ids) | set(plan_agent_ids))
    for agent in User.objects.filter(id__in=agent_ids, is_active=True):
        req, was_created = _get_or_create_availability_request(
            submission=submission,
            target_user=agent,
            participant_role=AvailabilityRequest.ParticipantRole.AGENT,
            schedule_plan=schedule_plan,
            timezone_name=timezone_name,
            requested_by=actor,
            message='에이전트 가용 시간 수집',
        )
        agent_requests.append(req)
        created_count += 1 if was_created else 0
        if notify and _notify_availability_request(req):
            notified_count += 1

    return {
        'customer_request': customer_request,
        'agent_requests': agent_requests,
        'created_count': created_count,
        'notified_count': notified_count,
    }


def send_availability_request_to_customer(submission, language_code='ko', actor=None):
    result = create_post_payment_availability_requests(submission, actor=actor, notify=False)
    customer_request = result.get('customer_request')
    if not customer_request:
        return False
    return _notify_availability_request(customer_request)


def send_availability_request_to_agent(schedule_plan, agent, language_code='ko', actor=None):
    if not schedule_plan or not agent:
        return False
    submission = getattr(schedule_plan, 'submission', None)
    if not submission:
        return False
    availability_request, _created = _get_or_create_availability_request(
        submission=submission,
        target_user=agent,
        participant_role=AvailabilityRequest.ParticipantRole.AGENT,
        schedule_plan=schedule_plan,
        timezone_name='UTC',
        requested_by=actor,
        message='에이전트 가용 시간 수집',
    )
    return _notify_availability_request(availability_request)


def can_user_respond_to_availability_request(user, availability_request):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not availability_request:
        return False
    if availability_request.target_user_id == user.id:
        return True
    return False


def _parse_time_value(value):
    if isinstance(value, time):
        return value
    if not value:
        raise ValueError('time value is required')
    if isinstance(value, str):
        raw = value.strip()
        for fmt in ('%H:%M', '%H:%M:%S'):
            try:
                return datetime.strptime(raw, fmt).time()
            except ValueError:
                continue
    raise ValueError('invalid time value')


def _validate_timezone_name(timezone_name):
    tz_name = (timezone_name or 'UTC').strip() or 'UTC'
    ZoneInfo(tz_name)
    return tz_name


def _normalize_slot_payloads(slots, timezone_name):
    normalized = []
    for slot in (slots or []):
        if not isinstance(slot, dict):
            continue
        weekday = slot.get('weekday')
        try:
            weekday = int(weekday)
        except (TypeError, ValueError):
            continue
        if weekday < 0 or weekday > 6:
            continue
        start_time_value = _parse_time_value(slot.get('start_time'))
        end_time_value = _parse_time_value(slot.get('end_time'))
        if end_time_value <= start_time_value:
            continue
        normalized.append({
            'weekday': weekday,
            'start_time': start_time_value,
            'end_time': end_time_value,
            'timezone_name': _validate_timezone_name(slot.get('timezone_name') or timezone_name),
        })
    return normalized


@transaction.atomic
def submit_availability_response(availability_request, responder, timezone_name, slots, note=''):
    if not availability_request:
        raise ValueError('availability_request is required')
    if not can_user_respond_to_availability_request(responder, availability_request):
        raise PermissionDenied('해당 가용 시간 요청에 응답할 권한이 없습니다.')
    if availability_request.status in (AvailabilityRequest.Status.CLOSED, AvailabilityRequest.Status.CANCELED):
        raise ValueError('종료된 요청입니다.')

    normalized_timezone = _validate_timezone_name(timezone_name)
    normalized_slots = _normalize_slot_payloads(slots, normalized_timezone)
    if not normalized_slots:
        raise ValueError('최소 1개 이상의 유효한 가용 시간 슬롯이 필요합니다.')

    next_revision = (
        availability_request.responses.order_by('-revision')
        .values_list('revision', flat=True)
        .first()
        or 0
    ) + 1

    response = AvailabilityResponse.objects.create(
        request=availability_request,
        responded_by=responder,
        timezone_name=normalized_timezone,
        note=(note or '').strip(),
        revision=next_revision,
    )
    AvailabilitySlot.objects.bulk_create([
        AvailabilitySlot(
            response=response,
            weekday=slot['weekday'],
            start_time=slot['start_time'],
            end_time=slot['end_time'],
            timezone_name=slot['timezone_name'],
        )
        for slot in normalized_slots
    ])

    availability_request.status = AvailabilityRequest.Status.RESPONDED
    availability_request.timezone_name = normalized_timezone
    availability_request.save(update_fields=['status', 'timezone_name', 'updated_at'])
    return response


def _slot_segments_in_timezone(slot, output_timezone):
    target_tz = ZoneInfo(_validate_timezone_name(output_timezone))
    slot_tz = ZoneInfo(_validate_timezone_name(slot.timezone_name or getattr(slot.response, 'timezone_name', 'UTC')))
    start_dt = datetime.combine(
        REFERENCE_MONDAY + timedelta(days=int(slot.weekday)),
        slot.start_time,
        tzinfo=slot_tz,
    )
    end_dt = datetime.combine(
        REFERENCE_MONDAY + timedelta(days=int(slot.weekday)),
        slot.end_time,
        tzinfo=slot_tz,
    )
    if end_dt <= start_dt:
        end_dt = end_dt + timedelta(days=1)

    start_local = start_dt.astimezone(target_tz)
    end_local = end_dt.astimezone(target_tz)

    segments = []
    cursor = start_local
    while cursor.date() < end_local.date():
        day_end = datetime.combine(cursor.date(), time.max, tzinfo=target_tz)
        segments.append((cursor.weekday(), cursor.timetz().replace(tzinfo=None), time(23, 59)))
        cursor = day_end + timedelta(microseconds=1)
    segments.append((end_local.weekday(), start_local.timetz().replace(tzinfo=None) if not segments else cursor.timetz().replace(tzinfo=None), end_local.timetz().replace(tzinfo=None)))
    return segments


def compute_overlapping_windows(customer_response, agent_response, output_timezone='UTC'):
    if not customer_response or not agent_response:
        return []

    overlaps = []
    customer_segments = []
    agent_segments = []
    for slot in customer_response.slots.all().order_by('weekday', 'start_time'):
        customer_segments.extend(_slot_segments_in_timezone(slot, output_timezone))
    for slot in agent_response.slots.all().order_by('weekday', 'start_time'):
        agent_segments.extend(_slot_segments_in_timezone(slot, output_timezone))

    for c_weekday, c_start, c_end in customer_segments:
        for a_weekday, a_start, a_end in agent_segments:
            if c_weekday != a_weekday:
                continue
            overlap_start = max(c_start, a_start)
            overlap_end = min(c_end, a_end)
            if overlap_start < overlap_end:
                overlaps.append({
                    'weekday': c_weekday,
                    'weekday_label': dict(AvailabilitySlot.Weekday.choices).get(c_weekday, str(c_weekday)),
                    'start_time': overlap_start.strftime('%H:%M'),
                    'end_time': overlap_end.strftime('%H:%M'),
                    'timezone_name': output_timezone,
                })

    deduped = []
    seen = set()
    for item in sorted(overlaps, key=lambda value: (value['weekday'], value['start_time'], value['end_time'])):
        key = (item['weekday'], item['start_time'], item['end_time'], item['timezone_name'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def get_availability_requests_for_workbench(submission, schedule_plan=None):
    requests = list(
        _request_base_queryset(submission, schedule_plan=schedule_plan)
        .select_related('target_user', 'requested_by', 'schedule_plan')
        .prefetch_related('responses__slots')
        .order_by('participant_role', 'target_user__username', '-created_at')
    )
    rows = []
    for availability_request in requests:
        latest_response = availability_request.latest_response()
        slots = []
        if latest_response:
            slots = [
                {
                    'weekday': slot.weekday,
                    'weekday_label': slot.get_weekday_display(),
                    'start_time': slot.start_time.strftime('%H:%M'),
                    'end_time': slot.end_time.strftime('%H:%M'),
                    'timezone_name': slot.timezone_name,
                }
                for slot in latest_response.slots.all().order_by('weekday', 'start_time', 'id')
            ]
        user = availability_request.target_user
        rows.append({
            'id': availability_request.id,
            'target_user_id': availability_request.target_user_id,
            'target_user_name': (user.get_full_name() or user.username or user.email or '').strip() if user else '',
            'participant_role': availability_request.participant_role,
            'participant_role_label': availability_request.get_participant_role_display(),
            'status': availability_request.status,
            'status_label': availability_request.get_status_display(),
            'timezone_name': availability_request.timezone_name,
            'created_at': availability_request.created_at,
            'latest_response_id': getattr(latest_response, 'id', None),
            'latest_response_revision': getattr(latest_response, 'revision', None),
            'latest_response_submitted_at': getattr(latest_response, 'submitted_at', None),
            'slot_count': len(slots),
            'slots': slots,
            'form_url': reverse('availability_request_input', kwargs={'request_id': availability_request.id}),
        })
    return rows


def get_availability_overlap_rows(submission, schedule_plan=None, output_timezone='UTC'):
    requests = list(
        _request_base_queryset(submission, schedule_plan=schedule_plan)
        .filter(status=AvailabilityRequest.Status.RESPONDED)
        .select_related('target_user')
        .prefetch_related('responses__slots')
    )
    customer_request = next((req for req in requests if req.participant_role == AvailabilityRequest.ParticipantRole.CUSTOMER and req.latest_response()), None)
    if not customer_request:
        return []
    customer_response = customer_request.latest_response()

    rows = []
    for agent_request in requests:
        if agent_request.participant_role != AvailabilityRequest.ParticipantRole.AGENT:
            continue
        agent_response = agent_request.latest_response()
        if not agent_response:
            continue
        overlaps = compute_overlapping_windows(customer_response, agent_response, output_timezone=output_timezone)
        user = agent_request.target_user
        rows.append({
            'agent_request_id': agent_request.id,
            'agent_id': agent_request.target_user_id,
            'agent_name': (user.get_full_name() or user.username or user.email or '').strip() if user else '',
            'timezone_name': output_timezone,
            'overlaps': overlaps,
        })
    return rows

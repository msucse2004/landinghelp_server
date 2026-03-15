import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .availability_request import (
    can_user_respond_to_availability_request,
    get_common_timezones,
    submit_availability_response,
)
from .models import AvailabilityRequest


def AvailabilitySlotWeekdayChoices():
    from .models import AvailabilitySlot

    return AvailabilitySlot.Weekday.choices


WEEKDAY_CHOICES = [
    {'value': value, 'label': label}
    for value, label in AvailabilitySlotWeekdayChoices()
]


@require_GET
@login_required
@ensure_csrf_cookie
def availability_request_input(request, request_id):
    availability_request = get_object_or_404(
        AvailabilityRequest.objects.select_related('submission', 'target_user'),
        pk=request_id,
    )
    if not can_user_respond_to_availability_request(request.user, availability_request):
        return render(
            request,
            'app/availability_request_form.html',
            {'error': 'forbidden', 'availability_request': availability_request},
            status=403,
        )

    latest_response = availability_request.latest_response()
    existing_slots = []
    if latest_response:
        existing_slots = [
            {
                'weekday': slot.weekday,
                'start_time': slot.start_time.strftime('%H:%M'),
                'end_time': slot.end_time.strftime('%H:%M'),
                'timezone_name': slot.timezone_name,
            }
            for slot in latest_response.slots.all().order_by('weekday', 'start_time', 'id')
        ]

    return render(request, 'app/availability_request_form.html', {
        'availability_request': availability_request,
        'existing_slots_json': json.dumps(existing_slots),
        'timezone_choices': get_common_timezones(),
        'weekday_choices_json': json.dumps(WEEKDAY_CHOICES, ensure_ascii=False),
        'default_timezone': getattr(latest_response, 'timezone_name', None) or availability_request.timezone_name or 'UTC',
        'error': None,
    })


@require_POST
@login_required
@ensure_csrf_cookie
def availability_request_submit(request, request_id):
    availability_request = get_object_or_404(
        AvailabilityRequest.objects.select_related('submission', 'target_user'),
        pk=request_id,
    )
    if not can_user_respond_to_availability_request(request.user, availability_request):
        return JsonResponse({'ok': False, 'error': '권한이 없습니다.'}, status=403)

    payload = {}
    if request.content_type and 'application/json' in (request.content_type or ''):
        try:
            payload = json.loads(request.body or '{}')
        except (TypeError, ValueError):
            payload = {}
    else:
        slots = []
        weekdays = request.POST.getlist('weekday[]') or request.POST.getlist('weekday')
        start_times = request.POST.getlist('start_time[]') or request.POST.getlist('start_time')
        end_times = request.POST.getlist('end_time[]') or request.POST.getlist('end_time')
        slot_timezones = request.POST.getlist('slot_timezone[]') or request.POST.getlist('slot_timezone')
        for idx, weekday in enumerate(weekdays):
            slots.append({
                'weekday': weekday,
                'start_time': start_times[idx] if idx < len(start_times) else '',
                'end_time': end_times[idx] if idx < len(end_times) else '',
                'timezone_name': slot_timezones[idx] if idx < len(slot_timezones) else '',
            })
        payload = {
            'timezone_name': request.POST.get('timezone_name') or '',
            'note': request.POST.get('note') or '',
            'slots': slots,
        }

    try:
        response = submit_availability_response(
            availability_request,
            request.user,
            payload.get('timezone_name') or availability_request.timezone_name or 'UTC',
            payload.get('slots') or [],
            note=payload.get('note') or '',
        )
    except Exception as exc:
        if request.content_type and 'application/json' in (request.content_type or ''):
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        return render(request, 'app/availability_request_form.html', {
            'availability_request': availability_request,
            'existing_slots_json': json.dumps(payload.get('slots') or []),
            'timezone_choices': get_common_timezones(),
            'weekday_choices_json': json.dumps(WEEKDAY_CHOICES, ensure_ascii=False),
            'default_timezone': payload.get('timezone_name') or availability_request.timezone_name or 'UTC',
            'error': str(exc),
        }, status=400)

    if request.content_type and 'application/json' in (request.content_type or ''):
        return JsonResponse({
            'ok': True,
            'response_id': response.id,
            'revision': response.revision,
            'message': '가용 시간이 저장되었습니다.',
        })
    return redirect(reverse('availability_request_input', kwargs={'request_id': availability_request.id}) + '?saved=1')


@require_GET
@login_required
@ensure_csrf_cookie
def agent_availability_input(request, plan_id):
    return render(request, 'app/availability_request_form.html', {
        'error': 'legacy_link_disabled',
        'availability_request': None,
    }, status=410)


@require_POST
@login_required
@ensure_csrf_cookie
def agent_availability_submit(request, plan_id):
    return JsonResponse({'ok': False, 'error': '기존 외부형 링크 입력은 더 이상 사용되지 않습니다.'}, status=410)

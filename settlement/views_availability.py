"""
Agent 가용 시간 입력 페이지 (when2meet 스타일).
토큰으로 본인만 접근 가능.
"""
import json
from datetime import datetime, date, time, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .availability_request import verify_availability_token
from .models import ServiceSchedulePlan, AgentAvailabilityWindow


def _agent_required_for_plan(request, plan_id, token):
    """토큰 검증 후 request.user가 해당 agent인지 확인. (plan, agent_user) 또는 (None, None)."""
    payload = verify_availability_token(token)
    if not payload:
        return None, None
    p_id, agent_id = payload
    if p_id != plan_id:
        return None, None
    if not request.user.is_authenticated or request.user.id != agent_id:
        return None, None
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if getattr(request.user, 'role', None) != User.Role.AGENT:
        return None, None
    plan = get_object_or_404(ServiceSchedulePlan, pk=plan_id)
    return plan, request.user


@require_GET
@login_required
@ensure_csrf_cookie
def agent_availability_input(request, plan_id):
    """가용 시간 입력 폼. token 쿼리 필드 필수, 본인(agent)만 접근."""
    token = (request.GET.get('token') or '').strip()
    if not token:
        return render(request, 'app/agent_availability_input.html', {'error': 'invalid_link', 'plan_id': plan_id})
    plan, agent = _agent_required_for_plan(request, plan_id, token)
    if not plan or not agent:
        return render(request, 'app/agent_availability_input.html', {'error': 'invalid_or_expired', 'plan_id': plan_id})
    windows = list(
        AgentAvailabilityWindow.objects.filter(
            schedule_plan=plan,
            agent=agent,
            source=AgentAvailabilityWindow.Source.LINK_RESPONSE,
            status=AgentAvailabilityWindow.WindowStatus.AVAILABLE,
        ).order_by('starts_at')
    )
    slots = []
    for w in windows:
        if w.starts_at and w.ends_at:
            d = w.starts_at.date()
            sh = w.starts_at.hour
            eh = w.ends_at.hour
            slots.append({'date': d.isoformat(), 'start_hour': sh, 'end_hour': eh})
    return render(request, 'app/agent_availability_input.html', {
        'plan': plan,
        'agent': agent,
        'existing_slots_json': json.dumps(slots),
        'error': None,
    })


@require_POST
@login_required
@ensure_csrf_cookie
def agent_availability_submit(request, plan_id):
    """가용 창 제출. JSON body: { "token": "...", "windows": [ {"date": "YYYY-MM-DD", "start_hour": 9, "end_hour": 10}, ... ] }"""
    try:
        body = json.loads(request.body or '{}')
        token = (body.get('token') or request.POST.get('token') or request.GET.get('token') or '').strip()
    except Exception:
        token = ''
    if not token:
        return JsonResponse({'ok': False, 'error': 'invalid_link'}, status=400)
    plan, agent = _agent_required_for_plan(request, plan_id, token)
    if not plan or not agent:
        return JsonResponse({'ok': False, 'error': 'invalid_or_expired'}, status=403)
    try:
        body = json.loads(request.body or '{}')
    except Exception:
        body = {}
    windows_payload = body.get('windows') or []
    if not isinstance(windows_payload, list):
        return JsonResponse({'ok': False, 'error': 'windows must be array'}, status=400)
    AgentAvailabilityWindow.objects.filter(
        schedule_plan=plan,
        agent=agent,
        source=AgentAvailabilityWindow.Source.LINK_RESPONSE,
    ).delete()
    created = 0
    submission = getattr(plan, 'submission', None)
    for w in windows_payload:
        if not isinstance(w, dict):
            continue
        d_str = w.get('date')
        sh = w.get('start_hour')
        eh = w.get('end_hour')
        if not d_str or sh is None or eh is None:
            continue
        try:
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        try:
            sh, eh = int(sh), int(eh)
        except (ValueError, TypeError):
            continue
        if sh < 0 or sh >= 24 or eh <= sh or eh > 24:
            continue
        start_dt = timezone.make_aware(datetime.combine(d, time(sh, 0)))
        end_dt = timezone.make_aware(datetime.combine(d, time(eh, 0)))
        AgentAvailabilityWindow.objects.create(
            agent=agent,
            submission=submission,
            schedule_plan=plan,
            starts_at=start_dt,
            ends_at=end_dt,
            source=AgentAvailabilityWindow.Source.LINK_RESPONSE,
            status=AgentAvailabilityWindow.WindowStatus.AVAILABLE,
        )
        created += 1
    return JsonResponse({'ok': True, 'created': created, 'message': f'{created}개 시간대를 저장했습니다.'})

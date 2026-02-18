# billing: 템플릿 컨텍스트 프로세서

from .models import Subscription


def user_plan_info(request):
    """
    모든 템플릿에 user_id, user_plan_display 제공.
    로그인 시: user_id=username, user_plan_display=현재 ACTIVE 구독 플랜명
    비로그인 시: user_id=None, user_plan_display=None (템플릿에서 Guest 표시)
    """
    if not request.user.is_authenticated:
        return {
            'user_id': None,
            'user_plan_display': None,
        }
    if request.user.is_superuser:
        return {
            'user_id': request.user.username,
            'user_plan_display': 'Super User',
        }
    sub = (
        request.user.subscriptions.select_related('plan')
        .filter(status=Subscription.Status.ACTIVE)
        .order_by('-started_at')
        .first()
    )
    plan_display = sub.plan.get_code_display() if sub and sub.plan else '미설정'
    return {
        'user_id': request.user.username,
        'user_plan_display': plan_display,
    }

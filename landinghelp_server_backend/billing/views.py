# billing: plan/subscription 뷰
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

from .models import Plan, Subscription


@login_required
def subscription_plan(request):
    """구독 플랜 목록 - 사용자 역할에 맞는 플랜만 표시 (고객 3개 / 에이전트 3개)"""
    user = request.user
    role_map = {'CUSTOMER': Plan.TargetRole.CUSTOMER, 'AGENT': Plan.TargetRole.AGENT}
    target = role_map.get(user.role, Plan.TargetRole.CUSTOMER)
    plans = Plan.objects.filter(is_active=True, target_role=target).order_by('tier')

    # 현재 구독
    current_sub = (
        user.subscriptions.select_related('plan')
        .filter(status=Subscription.Status.ACTIVE)
        .order_by('-started_at')
        .first()
    )

    from settlement.constants import get_service_label
    plan_list = [
        {'plan': p, 'free_agent_labels': [get_service_label(c) for c in (p.free_agent_service_codes or [])]}
        for p in plans
    ]

    return render(request, 'billing/subscription_plan.html', {
        'plan_list': plan_list,
        'current_subscription': current_sub,
    })


@login_required
def subscription_checkout(request, plan_id):
    """선택한 플랜 결제 화면"""
    plan = get_object_or_404(Plan, pk=plan_id, is_active=True)
    user = request.user

    # 역할 검증 (슈퍼유저 제외)
    if not user.is_superuser:
        role_map = {'CUSTOMER': Plan.TargetRole.CUSTOMER, 'AGENT': Plan.TargetRole.AGENT}
        target = role_map.get(user.role, Plan.TargetRole.CUSTOMER)
        if plan.target_role != target:
            messages.error(request, '선택한 플랜은 회원 유형에 맞지 않습니다.')
            return redirect('billing:subscription_plan')

    if request.method == 'POST':
        # 기존 ACTIVE 구독 취소
        user.subscriptions.filter(status=Subscription.Status.ACTIVE).update(
            status=Subscription.Status.CANCELED
        )
        # 새 구독 생성 (테스트/데모: 결제 없이 바로 활성화)
        Subscription.objects.create(
            user=user,
            plan=plan,
            status=Subscription.Status.ACTIVE,
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        messages.success(request, f'{plan.get_display_name()} 플랜 구독이 완료되었습니다.')
        return redirect('billing:subscription_complete', plan_id=plan.pk)

    return render(request, 'billing/subscription_checkout.html', {'plan': plan})


@login_required
def subscription_complete(request, plan_id):
    """구독 완료 페이지"""
    plan = get_object_or_404(Plan, pk=plan_id)
    return render(request, 'billing/subscription_complete.html', {'plan': plan})

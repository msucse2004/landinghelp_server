from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from billing.utils import get_user_tier
from billing.models import Plan
from content.models import CarouselSlide


def home(request):
    slides = list(CarouselSlide.objects.filter(is_active=True).order_by('order', 'id'))
    return render(request, 'home.html', {'carousel_slides': slides})


@login_required
def app_entry(request):
    """/app/ 진입점 - role별 대시보드 리다이렉트"""
    role = request.user.role
    if role == 'ADMIN':
        return redirect('app_admin_dashboard')
    if role == 'AGENT':
        return redirect('app_agent_dashboard')
    return redirect('app_customer_dashboard')


def _tier_label(tier):
    """tier 값 → 표시용 레이블"""
    val = getattr(tier, 'value', tier) if hasattr(tier, 'value') else tier
    return dict(Plan.Tier.choices).get(val, '베이직')


@login_required
def admin_dashboard(request):
    tier = get_user_tier(request.user)
    return render(request, 'app/admin_dashboard.html', {
        'tier_label': _tier_label(tier),
    })


@login_required
def agent_dashboard(request):
    tier = get_user_tier(request.user)
    return render(request, 'app/agent_dashboard.html', {
        'tier_label': _tier_label(tier),
    })


@login_required
def customer_dashboard(request):
    tier = get_user_tier(request.user)
    return render(request, 'app/customer_dashboard.html', {
        'tier_label': _tier_label(tier),
    })

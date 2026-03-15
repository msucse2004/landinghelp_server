from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .forms import SignUpForm, AdminPasswordResetForm, FindUsernameForm
from .models import User
from .services import send_verification_email, send_username_reminder, verify_token


def _is_staff(user):
    return user.is_authenticated and getattr(user, 'can_participate_in_hq_workspace', lambda: False)()


def find_username(request):
    """아이디 찾기: 이메일로 등록된 아이디 발송"""
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = FindUsernameForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()
            users = User.objects.filter(email__iexact=email, is_active=True)
            usernames = [u.username for u in users]
            if usernames:
                login_url = request.build_absolute_uri(reverse('login'))
                send_username_reminder(email, usernames, login_url=login_url)
            return redirect('find_username_done')
    else:
        form = FindUsernameForm()
    return render(request, 'registration/find_username.html', {'form': form})


def find_username_done(request):
    """아이디 찾기 완료 안내"""
    return render(request, 'registration/find_username_done.html')


def check_username(request):
    """아이디 중복 확인 API"""
    username = (request.GET.get('username') or '').strip()
    if not username:
        return JsonResponse({'available': None})
    exists = User.objects.filter(username__iexact=username).exists()
    return JsonResponse({'available': not exists})


@login_required
@user_passes_test(_is_staff, login_url='/login/')
def member_list(request):
    """Admin: 가입자 목록"""
    users = User.objects.prefetch_related('subscriptions__plan').order_by('-date_joined')
    for u in users:
        sub = next((s for s in u.subscriptions.all() if s.status == 'ACTIVE'), None)
        u.plan_display = sub.plan.get_display_name() if sub and sub.plan else '-'
    return render(request, 'accounts/member_list.html', {'users': users})


def signup(request):
    from settlement.constants import CATEGORY_ORDER
    from settlement.models import SettlementService
    from community.models import Area

    if request.user.is_authenticated:
        return redirect('home')
    services_qs = SettlementService.objects.filter(is_active=True).order_by('category', 'name')
    services_list = list(services_qs.values('id', 'name', 'category', 'agent_price'))
    services_by_category = {}
    for s in services_list:
        cat = s['category']
        services_by_category.setdefault(cat, []).append(s)
    services_by_category = {c: services_by_category.get(c, []) for c in CATEGORY_ORDER if c in services_by_category}
    areas_by_state = {}
    for a in Area.objects.order_by('state_code', 'order', 'id'):
        key = a.state_code
        if key not in areas_by_state:
            areas_by_state[key] = {'name': a.state_name or a.state_code, 'cities': []}
        areas_by_state[key]['cities'].append({'id': a.id, 'name': a.city_name})
    if request.method == 'POST':
        form = SignUpForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False
                    user.status = User.Status.UNVERIFIED
                    if user.role == User.Role.AGENT:
                        # 서비스 ID: DB에 존재하는 활성 서비스만 저장
                        raw_service_ids = [int(x) for x in request.POST.getlist('agent_services') if x.isdigit()]
                        valid_services = list(SettlementService.objects.filter(
                            id__in=raw_service_ids, is_active=True
                        ).values_list('id', flat=True))
                        user.agent_services = valid_services

                        # 도시 ID: DB에 존재하는 Area만 저장
                        raw_city_ids = [int(x) for x in request.POST.getlist('agent_cities') if x.isdigit()]
                        areas = Area.objects.filter(id__in=raw_city_ids)
                        user.agent_cities = list(areas.values_list('id', flat=True))

                        # State: 선택된 도시들의 주 코드 목록 (중복 제거)
                        user.agent_states = list(areas.values_list('state_code', flat=True).distinct())

                        # 주별 도시: {"NC": [1,2,3], "CA": [10,11]}
                        by_state = {}
                        for a in areas.values('id', 'state_code'):
                            sc = a['state_code']
                            by_state.setdefault(sc, []).append(a['id'])
                        user.agent_cities_by_state = by_state

                        # 프로필 사진 (에이전트만)
                        if request.FILES.get('agent_profile_image'):
                            user.profile_image = request.FILES['agent_profile_image']
                    else:
                        user.agent_services = []
                        user.agent_states = []
                        user.agent_cities = []
                        user.agent_cities_by_state = {}
                    user.save()
                    send_verification_email(user, request)
            except Exception:
                raise
            return redirect('verification_sent')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {
        'form': form,
        'services_by_category': services_by_category,
        'areas_by_state': areas_by_state,
    })


def verification_sent(request):
    """이메일 인증 안내 페이지"""
    return render(request, 'registration/verification_sent.html')


def verify_email(request):
    """이메일 인증 링크 클릭 처리"""
    token = request.GET.get('token')
    if not token:
        return render(request, 'registration/verification_failed.html', {'reason': 'invalid'})
    result = verify_token(token)
    if not result:
        return render(request, 'registration/verification_failed.html', {'reason': 'expired_or_invalid'})
    user_id, email = result
    user = User.objects.filter(pk=user_id, email=email, is_active=False).first()
    if not user:
        return render(request, 'registration/verification_failed.html', {'reason': 'already_verified'})
    user.is_active = True
    user.status = User.Status.ACTIVE
    user.save()
    login(request, user)
    messages.success(request, '이메일 인증이 완료되었습니다. 가입이 완료되었습니다.')
    return redirect('home')


@login_required
@user_passes_test(_is_staff, login_url='/login/')
@require_POST
def member_delete(request, user_id):
    """Admin: 가입자 삭제"""
    target = get_object_or_404(User, pk=user_id)
    if target == request.user:
        messages.error(request, '본인 계정은 삭제할 수 없습니다.')
    elif target.is_superuser:
        messages.error(request, '슈퍼유저는 삭제할 수 없습니다.')
    else:
        username = target.username
        target.delete()
        messages.success(request, f'"{username}" 계정이 삭제되었습니다.')
    return redirect('member_list')


@login_required
@user_passes_test(_is_staff, login_url='/login/')
def member_password_reset(request, user_id):
    """Admin: 가입자 비밀번호 리셋"""
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = AdminPasswordResetForm(request.POST)
        if form.is_valid():
            target.set_password(form.cleaned_data['new_password'])
            target.save()
            messages.success(request, f'"{target.username}" 비밀번호가 변경되었습니다.')
            return redirect('member_list')
    else:
        form = AdminPasswordResetForm()
    return render(request, 'accounts/member_password_reset.html', {
        'form': form,
        'target_user': target,
    })

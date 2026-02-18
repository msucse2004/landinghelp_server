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
    return user.is_authenticated and user.is_staff


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
        u.plan_display = sub.plan.get_code_display() if sub and sub.plan else '-'
    return render(request, 'accounts/member_list.html', {'users': users})


def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False
                    user.status = User.Status.UNVERIFIED
                    user.save()
                    send_verification_email(user, request)
            except Exception:
                raise
            return redirect('verification_sent')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


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

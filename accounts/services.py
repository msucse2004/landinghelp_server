# accounts: 이메일 인증等服务
from urllib.parse import quote

from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse


def generate_verification_token(user):
    """인증용 토큰 생성 (24시간 유효)"""
    signer = TimestampSigner()
    return signer.sign(f"{user.pk}:{user.email}")


def verify_token(token):
    """토큰 검증, 성공 시 (user_id, email) 반환, 실패 시 None"""
    signer = TimestampSigner()
    try:
        value = signer.unsign(token, max_age=86400)  # 24시간
        parts = value.split(":", 1)
        if len(parts) == 2:
            return int(parts[0]), parts[1]
    except (SignatureExpired, BadSignature):
        pass
    return None


def send_username_reminder(email, usernames, login_url=None):
    """
    아이디 찾기: 해당 이메일로 등록된 아이디(들) 발송.
    usernames: 문자열 리스트
    login_url: 로그인 페이지 URL (선택)
    """
    if not usernames:
        return
    subject = "[랜딩헬프] 아이디 안내"
    ids_text = ", ".join(usernames)
    login_hint = f"\n로그인: {login_url}" if login_url else ""
    message = f"""안녕하세요.

랜딩헬프 아이디 찾기 요청을 받으셨습니다.
등록된 아이디: {ids_text}
{login_hint}
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )


def send_verification_email(user, request):
    """가입 확인 이메일 발송"""
    token = generate_verification_token(user)
    verify_url = request.build_absolute_uri(
        reverse("verify_email") + "?token=" + quote(token)
    )
    subject = "[랜딩헬프] 이메일 인증을 완료해주세요"
    message = f"""안녕하세요, {user.first_name or user.username}님.

랜딩헬프 회원가입을 진행해 주셔서 감사합니다.
아래 링크를 클릭하여 이메일 인증을 완료해주세요.

{verify_url}

※ 링크는 24시간 동안 유효합니다.
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )

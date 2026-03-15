"""
설문 리마인드 이메일: status=DRAFT, updated_at 24시간 이상 경과, 이메일 존재 시 24시간마다 1회 발송.
실행: python manage.py send_survey_reminders
cron 예시: 0 10 * * * (매일 10시) → docs/SCHEDULING.md 참고.
"""
import logging
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.urls import reverse

from survey.models import SurveySubmission

logger = logging.getLogger(__name__)

# 하루 1회 제한용: 마지막 리마인드 후 이 시간 이상 지나야 재발송
REMINDER_INTERVAL_HOURS = 24


def _is_email_configured_for_sending():
    """실제 발송 가능 여부. 환경변수만 사용, 코드/깃에 비밀 없음."""
    backend = (getattr(settings, 'EMAIL_BACKEND', '') or '').lower()
    if 'console' in backend:
        return False
    user = (getattr(settings, 'EMAIL_HOST_USER', None) or '').strip()
    password = (getattr(settings, 'EMAIL_HOST_PASSWORD', None) or '').strip()
    return bool(user and password)


def get_survey_resume_url():
    """설문 이어하기 절대 URL (이메일 링크용). SITE_URL 미설정 시 경로만 반환."""
    base = (getattr(settings, 'SITE_URL', None) or '').strip().rstrip('/')
    path = reverse('survey:survey_start')
    if base:
        return f"{base}{path}"
    return path


def get_reminder_subject():
    return "[랜딩헬프] 설문을 이어서 작성해 주세요"


def get_reminder_body(resume_url):
    return f"""안녕하세요.

시작하셨던 설문이 아직 완료되지 않았습니다.
아래 링크에서 이어서 작성해 주세요.

설문 이어하기: {resume_url}

감사합니다.
랜딩헬프
"""


class Command(BaseCommand):
    help = "미제출 DRAFT 설문에 대해 24시간마다 리마인드 이메일 발송 (하루 1회 제한)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='발송하지 않고 대상만 출력',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='대상/발송 결과 상세 출력',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']

        # 설정 없으면 리마인더 조용히 비활성화 (경고 로그만)
        if not _is_email_configured_for_sending():
            logger.warning(
                "Survey reminders disabled: email not configured (EMAIL_HOST_USER/EMAIL_HOST_PASSWORD or SMTP backend). "
                "Set env vars and use django.core.mail.backends.smtp.EmailBackend; run check_email_env to verify."
            )
            if verbose:
                self.stdout.write(self.style.WARNING("이메일 미설정으로 리마인더 비활성화됨."))
            return

        from datetime import timedelta
        now = timezone.now()
        cutoff_updated = now - timedelta(hours=REMINDER_INTERVAL_HOURS)
        cutoff_reminded = now - timedelta(hours=REMINDER_INTERVAL_HOURS)

        # 조건: status=DRAFT, 이메일 존재, updated_at 24시간 이상 경과,
        #       last_reminded_at 없거나 24시간 이상 경과 (하루 1회 제한)
        from django.db.models import Q
        qs = SurveySubmission.objects.filter(
            status=SurveySubmission.Status.DRAFT,
        ).exclude(
            email__isnull=True,
        ).exclude(
            email='',
        ).filter(
            updated_at__lte=cutoff_updated,
        ).filter(
            Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lte=cutoff_reminded)
        )

        targets = list(qs.order_by('updated_at'))
        if not targets:
            if verbose:
                self.stdout.write("발송 대상 없음.")
            return

        self.stdout.write(f"대상 {len(targets)}건 (dry_run={dry_run})")
        resume_url = get_survey_resume_url()
        subject = get_reminder_subject()
        body = get_reminder_body(resume_url)
        sent = 0
        failed = 0

        for sub in targets:
            if verbose:
                self.stdout.write(f"  {sub.email} (id={sub.id}, updated_at={sub.updated_at})")
            if dry_run:
                sent += 1
                continue
            try:
                send_mail(
                    subject,
                    body,
                    settings.DEFAULT_FROM_EMAIL,
                    [sub.email],
                    fail_silently=False,
                )
                sub.last_reminded_at = now
                sub.save(update_fields=['last_reminded_at'])
                sent += 1
                if verbose:
                    self.stdout.write(self.style.SUCCESS(f"  발송 완료: {sub.email}"))
            except Exception as e:
                failed += 1
                logger.warning("Survey reminder send failed: submission_id=%s email=%s error=%s",
                               sub.id, sub.email, e, exc_info=True)
                if verbose:
                    self.stdout.write(self.style.WARNING(f"  발송 실패: {sub.email} - {e}"))

        self.stdout.write(self.style.SUCCESS(f"완료: 발송={sent}, 실패={failed}"))

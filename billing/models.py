# billing: plan/subscription
from django.db import models
from django.conf import settings


class Plan(models.Model):
    """요금제"""

    class Code(models.TextChoices):
        C_BASIC = 'C_BASIC', '고객 베이직'
        C_STANDARD = 'C_STANDARD', '고객 스탠다드'
        C_PREMIUM = 'C_PREMIUM', '고객 프리미엄'
        P_BASIC = 'P_BASIC', '에이전트 베이직'
        P_STANDARD = 'P_STANDARD', '에이전트 스탠다드'
        P_PREMIUM = 'P_PREMIUM', '에이전트 프리미엄'

    class TargetRole(models.TextChoices):
        CUSTOMER = 'CUSTOMER', '고객'
        AGENT = 'AGENT', '에이전트'

    class Tier(models.IntegerChoices):
        BASIC = 1, '베이직'
        STANDARD = 2, '스탠다드'
        PREMIUM = 3, '프리미엄'

    code = models.CharField(
        max_length=30,
        choices=Code.choices,
        unique=True,
    )
    target_role = models.CharField(
        max_length=20,
        choices=TargetRole.choices,
    )
    tier = models.PositiveSmallIntegerField(
        choices=Tier.choices,
    )
    features = models.JSONField(
        default=dict,
        blank=True,
        help_text='플랜 기능 목록 (JSON)',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = '요금제'
        verbose_name_plural = '요금제'

    def __str__(self):
        return self.get_code_display()


class Subscription(models.Model):
    """구독 (유저당 ACTIVE 1개)"""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '활성'
        CANCELED = 'CANCELED', '취소됨'
        PAST_DUE = 'PAST_DUE', '결제연체'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '구독'
        verbose_name_plural = '구독'

    def __str__(self):
        return f"{self.user} - {self.plan} ({self.get_status_display()})"

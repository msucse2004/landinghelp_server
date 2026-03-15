# billing: plan/subscription
from django.db import models
from django.conf import settings


class Plan(models.Model):
    """요금제"""

    class Code(models.TextChoices):
        C_BASIC = 'C_BASIC', 'Basic'
        C_STANDARD = 'C_STANDARD', 'Standard'
        C_PREMIUM = 'C_PREMIUM', 'Premium'
        P_BASIC = 'P_BASIC', 'Basic'
        P_STANDARD = 'P_STANDARD', 'Standard'
        P_PREMIUM = 'P_PREMIUM', 'Premium'

    class TargetRole(models.TextChoices):
        CUSTOMER = 'CUSTOMER', '고객'
        AGENT = 'AGENT', '에이전트'

    class Tier(models.IntegerChoices):
        BASIC = 1, '베이직'
        STANDARD = 2, '스탠다드'
        PREMIUM = 3, '프리미엄'

    name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='요금제 이름',
        help_text='표시용 이름. 예: 스탠다드, 프리미엄',
    )
    code = models.CharField(
        max_length=30,
        choices=Code.choices,
        unique=True,
        null=True,
        blank=True,
        help_text='레거시/시드용. 비워두면 이름으로만 표시.',
    )
    target_role = models.CharField(
        max_length=20,
        choices=TargetRole.choices,
    )
    tier = models.PositiveSmallIntegerField(
        choices=Tier.choices,
        null=True,
        blank=True,
        help_text='레거시용. 비워두면 표시만 이름 사용.',
    )
    features = models.JSONField(
        default=dict,
        blank=True,
        help_text='플랜 기능 목록 (JSON)',
    )
    free_agent_service_codes = models.JSONField(
        default=list,
        blank=True,
        verbose_name='무료 Agent 서비스 항목',
        help_text='고객 플랜 전용. 이 요금제에서 무료로 제공하는 정착 서비스 코드 목록. 예: ["AIRPORT_PICKUP"]',
    )
    # 서비스 정책 (비어 있으면 tier 기반으로 동작, tier도 없으면 베이직)
    can_use_llm = models.BooleanField(
        null=True,
        blank=True,
        verbose_name='LLM(AI) 서비스 사용',
        help_text='체크 시 AI 서비스 이용 가능. 비워두면 tier/기본값 적용.',
    )
    has_agent_assistance = models.BooleanField(
        null=True,
        blank=True,
        verbose_name='에이전트 도움(필요 시)',
        help_text='체크 시 필요 시 에이전트 도움 가능. 비워두면 tier 적용.',
    )
    has_full_agent_assistance = models.BooleanField(
        null=True,
        blank=True,
        verbose_name='전체 항목 에이전트 도움',
        help_text='체크 시 모든 항목 에이전트 도움. 비워두면 tier 적용.',
    )
    can_contract_package_or_single = models.BooleanField(
        null=True,
        blank=True,
        verbose_name='패키지/단일 계약 가능',
        help_text='체크 시 패키지·단일 항목 계약 가능. 비워두면 tier 적용.',
    )
    DURATION_CHOICES = [
        (1, '1개월'),
        (3, '3개월'),
        (6, '6개월'),
        (0, '무제한'),
    ]
    duration_months = models.IntegerField(
        choices=DURATION_CHOICES,
        default=1,
        verbose_name='요금제 유지 기간',
        help_text='1개월, 3개월, 6개월, 무제한 중 선택.',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = '요금제'
        verbose_name_plural = '요금제'

    def __str__(self):
        return self.name or (self.get_code_display() if self.code else f'요금제 #{self.pk}')

    def get_display_name(self):
        """표시용 이름 (이름 우선, 없으면 code 표시)"""
        return self.name or (self.get_code_display() if self.code else f'요금제 #{self.pk}')


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

# accounts: 인증/역할(app authentication & role)
import re
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth.models import AbstractUser
from translations.utils import DisplayKey


def format_phone_number(phone: str) -> str:
    """한국 휴대폰 번호를 010-XXXX-XXXX 형식으로 정규화. 형식 불명 번호는 원문 반환."""
    if not phone:
        return phone
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('01'):
        return f'{digits[:3]}-{digits[3:7]}-{digits[7:]}'
    if len(digits) == 10 and digits.startswith('01'):
        return f'{digits[:3]}-{digits[3:6]}-{digits[6:]}'
    return phone


class AgentRating(models.Model):
    """에이전트에 대한 고객 별점 평가. appointment가 있으면 약속당 1건, 없으면 (rater, agent)당 1건(레거시)."""

    rater = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='ratings_given',
        verbose_name=DisplayKey('평가자 (Customer)'),  # 평가자 (Customer)
    )
    agent = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='ratings_received',
        verbose_name=DisplayKey('평가 대상 (Agent)'),  # 평가 대상 (Agent)
    )
    appointment = models.ForeignKey(
        'settlement.AgentAppointmentRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ratings',
        verbose_name=DisplayKey('연결된 약속'),  # 연결된 약속
        help_text=DisplayKey('완료된 약속에 대한 후기일 때만 연결. 약속당 1건만 허용.'),
    )
    score = models.PositiveSmallIntegerField(
        verbose_name=DisplayKey('별점'),  # 별점
        help_text=DisplayKey('1~5점'),
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True, verbose_name=DisplayKey('한줄평'))  # 한줄평
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = DisplayKey('에이전트 별점')  # 에이전트 별점
        verbose_name_plural = DisplayKey('에이전트 별점')
        ordering = ('-created_at',)
        constraints = [
            # 레거시: appointment 없을 때 (rater, agent)당 1건
            models.UniqueConstraint(
                fields=['rater', 'agent'],
                condition=models.Q(appointment__isnull=True),
                name='unique_agent_rating_per_customer_legacy',
            ),
            # 약속당 1건
            models.UniqueConstraint(
                fields=['rater', 'appointment'],
                condition=models.Q(appointment__isnull=False),
                name='unique_agent_rating_per_appointment',
            ),
        ]

    def __str__(self):
        return f'{self.rater.username} → {self.agent.username}: {self.score}점'


class User(AbstractUser):
    """커스텀 사용자 모델 - 역할(role), 상태(status)"""

    class Role(models.TextChoices):
        SUPER_ADMIN = 'SUPER_ADMIN', '슈퍼 관리자'
        ADMIN = 'ADMIN', '관리자'
        SUPERVISOR = 'SUPERVISOR', '운영 관리자'
        HQ_STAFF = 'HQ_STAFF', '본사 스태프'
        AGENT = 'AGENT', '에이전트'
        CUSTOMER = 'CUSTOMER', '고객'

    class Status(models.TextChoices):
        UNVERIFIED = 'UNVERIFIED', '인증전'
        ACTIVE = 'ACTIVE', '활성'
        PENDING = 'PENDING', '대기'
        SUSPENDED = 'SUSPENDED', '정지'

    class AgentLevel(models.TextChoices):
        BRONZE = 'BRONZE', 'Bronze'
        SILVER = 'SILVER', 'Silver'
        GOLD = 'GOLD', 'Gold'
        DIAMOND = 'DIAMOND', 'Diamond'
        PLATINUM = 'PLATINUM', 'Platinum'

    class AgentIdentityVerificationStatus(models.TextChoices):
        NOT_REQUIRED = 'NOT_REQUIRED', '확인 불필요'
        REQUIRED = 'REQUIRED', '신분 확인 서류 필요'
        SUBMITTED = 'SUBMITTED', '신분 확인 서류 제출됨'
        VERIFIED = 'VERIFIED', '신분 확인 완료'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name=DisplayKey('생년월일'))  # 생년월일
    phone = models.CharField(
        max_length=30,
        blank=True,
        default='',
        verbose_name=DisplayKey('휴대폰 번호'),  # 휴대폰 번호
    )

    class Gender(models.TextChoices):
        M = 'M', '남성'
        F = 'F', '여성'
        O = 'O', '기타'

    gender = models.CharField(
        max_length=2,
        choices=Gender.choices,
        null=True,
        blank=True,
        verbose_name=DisplayKey('성별'),  # 성별
    )
    # 선호 언어 (Django 언어 코드). 라벨은 CSV key로 사용되며 표시 시 get_display_text로 조회.
    PREFERRED_LANGUAGE_CHOICES = [
        ('ko', 'KR 한국어'),
        ('en', 'EN English'),
        ('es', 'ES Español'),
        ('zh-hans', 'ZH 中文(简体)'),
        ('zh-hant', 'ZH 中文(繁體)'),
        ('vi', 'VI Tiếng Việt'),
    ]
    preferred_language = models.CharField(
        max_length=10,
        choices=PREFERRED_LANGUAGE_CHOICES,
        default='en',
        blank=True,
        verbose_name=DisplayKey('선호 언어'),  # 선호 언어
    )
    agent_services = models.JSONField(default=list, blank=True, verbose_name=DisplayKey('에이전트 서비스 (가입 시 선택)'),  # 에이전트 서비스 (가입 시 선택)
        help_text=DisplayKey('에이전트 가입 시 선택한 SettlementService ID 목록'))
    agent_states = models.JSONField(default=list, blank=True, verbose_name=DisplayKey('커버 주(State)'),  # 커버 주(State)
        help_text=DisplayKey('에이전트가 커버하는 주 코드 목록 (예: NC, CA, TX)'))
    agent_cities = models.JSONField(default=list, blank=True, verbose_name=DisplayKey('커버 도시'),  # 커버 도시
        help_text=DisplayKey('에이전트가 커버하는 도시 Area ID 목록'))
    agent_cities_by_state = models.JSONField(default=dict, blank=True, verbose_name=DisplayKey('커버 도시 (주별)'),  # 커버 도시 (주별)
        help_text=DisplayKey('주별 도시 ID: {"NC": [1,2,3], "CA": [10,11]}'))
    profile_image = models.ImageField(
        upload_to='accounts/profile/%Y/%m/',
        blank=True,
        null=True,
        verbose_name=DisplayKey('프로필 사진'),  # 프로필 사진
    )
    # 에이전트 전체 수락률 (0~1 또는 0~100 저장 시 0~1 권장). 관리/표시용.
    accept_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=DisplayKey('Accept rate (수락률)'),  # Accept rate (수락률)
        help_text=DisplayKey('에이전트 전체 약속 수락률. 예: 0.85 = 85%. 비워두면 서비스별 통계에서 계산해 표시.'),
    )
    agent_level = models.CharField(
        max_length=20,
        choices=AgentLevel.choices,
        default=AgentLevel.BRONZE,
        db_index=True,
        verbose_name=DisplayKey('Agent 레벨'),
        help_text=DisplayKey('Bronze/Silver/Gold/Diamond/Platinum 레벨'),
    )
    agent_level_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=DisplayKey('Agent 레벨 점수'),
        help_text=DisplayKey('완료건수/별점/수락률 기반 계산 점수(0~100 권장)'),
    )
    agent_completed_service_count = models.PositiveIntegerField(
        default=0,
        verbose_name=DisplayKey('완료 서비스 건수(스냅샷)'),
        help_text=DisplayKey('레벨 계산 시점 기준 완료 서비스 건수'),
    )
    agent_rating_avg_snapshot = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=DisplayKey('평점 평균(스냅샷)'),
        help_text=DisplayKey('레벨 계산 시점 기준 평균 별점(1~5)'),
    )
    agent_accept_rate_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=DisplayKey('수락률(스냅샷)'),
        help_text=DisplayKey('레벨 계산 시점 기준 수락률(0~1 권장)'),
    )
    agent_level_constraints = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=DisplayKey('레벨 기반 제약(초안)'),
        help_text=DisplayKey('향후 레벨별 제약 룰을 저장하기 위한 구조화 필드'),
    )
    agent_level_last_evaluated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=DisplayKey('레벨 평가 시각'),
    )
    agent_identity_verification_status = models.CharField(
        max_length=20,
        choices=AgentIdentityVerificationStatus.choices,
        default=AgentIdentityVerificationStatus.NOT_REQUIRED,
        db_index=True,
        verbose_name=DisplayKey('Agent 신분 확인 상태'),
        help_text=DisplayKey('최초 온보딩 시 신분증 확인이 필요한 Agent 여부와 처리 상태'),
    )
    agent_identity_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=DisplayKey('Agent 신분 확인 완료 시각'),
    )

    class Meta:
        verbose_name = DisplayKey('사용자')  # 사용자
        verbose_name_plural = DisplayKey('사용자들')

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role != self.Role.SUPER_ADMIN:
            self.role = self.Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    @classmethod
    def internal_staff_role_values(cls):
        return (
            cls.Role.SUPER_ADMIN,
            cls.Role.ADMIN,
            cls.Role.SUPERVISOR,
            cls.Role.HQ_STAFF,
        )

    def is_internal_staff(self):
        if not getattr(self, 'is_authenticated', True):
            return False
        if self.role in self.internal_staff_role_values():
            return True
        return bool(getattr(self, 'is_staff', False) or getattr(self, 'is_superuser', False))

    def can_send_quote(self):
        return self.is_internal_staff()

    def can_finalize_schedule(self):
        return self.is_internal_staff()

    def can_manage_case_documents(self):
        return self.is_internal_staff()

    def agent_identity_verification_required(self):
        return (
            self.role == self.Role.AGENT
            and self.agent_identity_verification_status == self.AgentIdentityVerificationStatus.REQUIRED
        )

    def agent_identity_verified(self):
        return self.agent_identity_verification_status == self.AgentIdentityVerificationStatus.VERIFIED

    def can_view_customer_private_docs(self, submission):
        if not getattr(self, 'is_authenticated', True):
            return False
        if self.is_internal_staff():
            return True
        if self.role != self.Role.CUSTOMER:
            return False
        owner_id = getattr(submission, 'user_id', None) if submission is not None else None
        return bool(owner_id and owner_id == self.id)

    def can_participate_in_hq_workspace(self):
        return self.is_internal_staff()

    def can_participate_in_local_workspace(self):
        if not getattr(self, 'is_authenticated', True):
            return False
        if self.role in (self.Role.CUSTOMER, self.Role.AGENT):
            return True
        return self.is_internal_staff()

    def get_agent_rating_summary(self):
        """에이전트일 때 평균 별점과 평가 수 반환 (agent만 사용)"""
        if self.role != self.Role.AGENT:
            return None
        from django.db.models import Avg, Count
        result = self.ratings_received.aggregate(avg=Avg('score'), count=Count('id'))
        return {'avg': result['avg'], 'count': result['count'] or 0}

    def is_agent_level_at_least(self, level: str) -> bool:
        if self.role != self.Role.AGENT:
            return False
        order = [
            self.AgentLevel.BRONZE,
            self.AgentLevel.SILVER,
            self.AgentLevel.GOLD,
            self.AgentLevel.DIAMOND,
            self.AgentLevel.PLATINUM,
        ]
        try:
            return order.index(self.agent_level or self.AgentLevel.BRONZE) >= order.index(level)
        except ValueError:
            return False


class AgentForRating(User):
    """에이전트 별점 Admin용 프록시 (에이전트 목록 + 별점 세부)"""
    class Meta:
        proxy = True
        verbose_name = DisplayKey('에이전트별 별점')  # 에이전트별 별점
        verbose_name_plural = DisplayKey('에이전트별 별점')

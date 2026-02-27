# accounts: 인증/역할(app authentication & role)
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth.models import AbstractUser
from translations.utils import DisplayKey


class AgentRating(models.Model):
    """에이전트에 대한 고객 별점 평가"""

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
            models.UniqueConstraint(
                fields=['rater', 'agent'],
                name='unique_agent_rating_per_customer',
            ),
        ]

    def __str__(self):
        return f'{self.rater.username} → {self.agent.username}: {self.score}점'


class User(AbstractUser):
    """커스텀 사용자 모델 - 역할(role), 상태(status)"""

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', '관리자'
        AGENT = 'AGENT', '에이전트'
        CUSTOMER = 'CUSTOMER', '고객'

    class Status(models.TextChoices):
        UNVERIFIED = 'UNVERIFIED', '인증전'
        ACTIVE = 'ACTIVE', '활성'
        PENDING = 'PENDING', '대기'
        SUSPENDED = 'SUSPENDED', '정지'

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
        default='ko',
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

    class Meta:
        verbose_name = DisplayKey('사용자')  # 사용자
        verbose_name_plural = DisplayKey('사용자들')

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role != self.Role.ADMIN:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    def get_agent_rating_summary(self):
        """에이전트일 때 평균 별점과 평가 수 반환 (agent만 사용)"""
        if self.role != self.Role.AGENT:
            return None
        from django.db.models import Avg, Count
        result = self.ratings_received.aggregate(avg=Avg('score'), count=Count('id'))
        return {'avg': result['avg'], 'count': result['count'] or 0}


class AgentForRating(User):
    """에이전트 별점 Admin용 프록시 (에이전트 목록 + 별점 세부)"""
    class Meta:
        proxy = True
        verbose_name = DisplayKey('에이전트별 별점')  # 에이전트별 별점
        verbose_name_plural = DisplayKey('에이전트별 별점')

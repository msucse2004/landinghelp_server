from django.db import models
from django.conf import settings
from translations.utils import DisplayKey


class SettlementService(models.Model):
    """정착 서비스 항목 (Admin에서 category별 관리)"""

    class Category(models.TextChoices):
        HOUSING = '주거/임대', '주거/임대'
        TRANSPORT = '교통/차량', '교통/차량'
        LIVING = '생활편의', '생활편의'
        MEDICAL = '의료/교육', '의료/교육'
        ADMIN = '행정/문서', '행정/문서'
        ETC = '기타', '기타'

    code = models.CharField(max_length=50, unique=True, null=True, blank=True, verbose_name=DisplayKey('서비스 코드'),  # 서비스 코드
        help_text=DisplayKey('견적/스케줄 식별용 (예: DRIVERS_LICENSE). 비어있으면 id 사용'))
    name = models.CharField(max_length=100, verbose_name=DisplayKey('항목이름'))  # 항목이름
    category = models.CharField(max_length=20, choices=Category.choices, verbose_name=DisplayKey('카테고리'))  # 카테고리
    required_time = models.PositiveIntegerField(default=60, verbose_name=DisplayKey('필요 시간(분)'), help_text=DisplayKey('예: 60 = 1시간'))  # 필요 시간(분) / 예: 60 = 1시간
    customer_price = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name=DisplayKey('Customer 가격'))  # Customer 가격
    agent_price = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name=DisplayKey('Agent 가격'))  # Agent 가격
    is_active = models.BooleanField(default=True, verbose_name=DisplayKey('활성'))  # 활성
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = DisplayKey('서비스 항목')  # 서비스 항목
        verbose_name_plural = DisplayKey('서비스 항목')
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_category_display()})'


class SettlementQuoteRequest(models.Model):
    """정착 서비스 견적 신청"""
    # 선택 서비스 (코드 목록)
    services = models.JSONField(default=list, verbose_name=DisplayKey('선택 서비스'))  # 선택 서비스
    # 이주 정보
    state = models.CharField(max_length=50, blank=True, verbose_name=DisplayKey('이주 State'))  # 이주 State
    city = models.CharField(max_length=100, blank=True, verbose_name=DisplayKey('도시'))  # 도시
    entry_date = models.DateField(null=True, blank=True, verbose_name=DisplayKey('입국/이주 예정일'))  # 입국/이주 예정일
    # 문의자 정보
    name = models.CharField(max_length=100, verbose_name=DisplayKey('이름'))  # 이름
    email = models.EmailField(verbose_name=DisplayKey('이메일'))  # 이메일
    service_schedule = models.JSONField(default=dict, blank=True, verbose_name=DisplayKey('서비스 일정'),  # 서비스 일정
        help_text=DisplayKey('날짜별 서비스: {"YYYY-MM-DD": ["SERVICE_CODE", ...]}'))
    checkout_total = models.DecimalField(
        max_digits=14, decimal_places=0, default=0, verbose_name=DisplayKey('Checkout 합계'),  # Checkout 합계
        help_text=DisplayKey('서비스 customer_price 합계'),
    )
    memo = models.TextField(blank=True, verbose_name=DisplayKey('추가 문의사항'))  # 추가 문의사항
    # AI 추천 사용 여부
    ai_suggested = models.BooleanField(default=False, verbose_name=DisplayKey('AI 추천 사용'))  # AI 추천 사용
    # 생성/상태
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlement_quotes',
        verbose_name=DisplayKey('신청자'),  # 신청자
    )

    class Meta:
        verbose_name = DisplayKey('견적 신청')  # 견적 신청
        verbose_name_plural = DisplayKey('견적 신청')
        ordering = ['-created_at']


class UserSettlementPlan(models.Model):
    """사용자별 정착 플랜 (저장된 일정·이주정보) - 1 user : 1 plan"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='settlement_plan',
        verbose_name=DisplayKey('사용자'),  # 사용자
    )
    state = models.CharField(max_length=50, blank=True, verbose_name=DisplayKey('이주 State'))  # 이주 State
    city = models.CharField(max_length=100, blank=True, verbose_name=DisplayKey('도시'))  # 도시
    entry_date = models.DateField(null=True, blank=True, verbose_name=DisplayKey('입국/이주 예정일'))  # 입국/이주 예정일
    service_schedule = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=DisplayKey('서비스 일정'),  # 서비스 일정
        help_text=DisplayKey('{"YYYY-MM-DD": [{"code":"X","label":"Y"}, ...]}'),
    )
    checkout_total = models.DecimalField(
        max_digits=14,
        decimal_places=0,
        default=0,
        verbose_name=DisplayKey('Checkout 합계'),  # Checkout 합계
        help_text=DisplayKey('서비스 customer_price 합계'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = DisplayKey('사용자 정착 플랜')  # 사용자 정착 플랜
        verbose_name_plural = DisplayKey('사용자 정착 플랜')

    def has_schedule(self):
        """일정 데이터가 있는지"""
        if not self.service_schedule or not isinstance(self.service_schedule, dict):
            return False
        return bool(self.service_schedule)

    def has_agent_assignment(self):
        """일정에 Agent가 하나라도 할당되어 있는지 (결제 금액 표시 조건)"""
        from .constants import schedule_has_agent_assignment
        return schedule_has_agent_assignment(self.service_schedule)


class AgentAppointmentRequest(models.Model):
    """
    Agent와의 약속(상담) 신청.

    약속 정보의 단일 소스(Single Source of Truth): admin·customer·agent 모두
    이 테이블만 읽어서 표시/수정합니다. 별도 캐시나 중복 저장 없이 DB 한 곳에서만
    읽어오므로, 약속이 수정/삭제되면 모든 화면에 자동 반영됩니다.
    """
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='appointment_requests',
        verbose_name=DisplayKey('Agent'),  # Agent
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments_requested',
        verbose_name=DisplayKey('신청자'),  # 신청자
    )
    service_code = models.CharField(max_length=50, verbose_name=DisplayKey('서비스 코드'))  # 서비스 코드
    service_date = models.DateField(verbose_name=DisplayKey('희망 일자'))  # 희망 일자
    preferred_time = models.CharField(max_length=50, blank=True, verbose_name=DisplayKey('희망 시간대'))  # 희망 시간대
    message = models.TextField(blank=True, verbose_name=DisplayKey('메시지'))  # 메시지
    # 비로그인 시 연락처
    customer_name = models.CharField(max_length=100, blank=True, verbose_name=DisplayKey('연락처 이름'))  # 연락처 이름
    customer_email = models.EmailField(blank=True, verbose_name=DisplayKey('연락처 이메일'))  # 연락처 이메일
    status = models.CharField(
        max_length=20,
        default='PENDING',
        choices=[
            ('PENDING', '대기'),
            ('CONFIRMED', '확정'),
            ('CANCELLED', '취소'),
        ],
        verbose_name=DisplayKey('상태'),  # 상태
    )
    cancellation_reason = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=DisplayKey('취소 사유'),  # 취소 사유
        help_text=DisplayKey('취소 시 사유. 예: 사용자 취소, Agent 취소'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=DisplayKey('수락 독촉 알림 발송 시각'),  # 수락 독촉 알림 발송 시각
        help_text=DisplayKey('24시간 미수락 시 에이전트에게 보낸 독촉 메시지 발송 시각'),
    )

    class Meta:
        verbose_name = DisplayKey('약속 신청')  # 약속 신청
        verbose_name_plural = DisplayKey('약속 신청')
        ordering = ['-created_at']

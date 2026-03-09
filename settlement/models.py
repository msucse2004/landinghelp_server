from decimal import Decimal
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


class ServiceStatePrice(models.Model):
    """서비스별·State별 가격. 없으면 SettlementService.customer_price/agent_price 사용."""

    service = models.ForeignKey(
        SettlementService,
        on_delete=models.CASCADE,
        related_name='state_prices',
        verbose_name='서비스',
    )
    state_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name='State 코드',
        help_text='예: CA, NC, NY (2글자 권장)',
    )
    customer_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name='Customer 가격 (USD)',
    )
    agent_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name='Agent 가격 (USD)',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '서비스 State별 가격'
        verbose_name_plural = '서비스 State별 가격'
        unique_together = [['service', 'state_code']]
        ordering = ['service', 'state_code']

    def __str__(self):
        return f'{self.service.name} @ {self.state_code}'


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


class SettlementQuote(models.Model):
    """Admin 작성 견적. 설문 제출(SurveySubmission)에 연결. status < FINAL_SENT일 때 고객에게 가격/합계 비노출."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '초안'
        NEGOTIATING = 'NEGOTIATING', '협의 중'
        FINAL_SENT = 'FINAL_SENT', '송부 완료'
        PAID = 'PAID', '결제 완료'

    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='settlement_quotes',
        verbose_name='설문 제출',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name='상태',
    )
    items = models.JSONField(
        default=list,
        blank=True,
        verbose_name='견적 항목',
        help_text='[{"code":"X","label":"서비스명","price":50000,"_auto":true,"_needs_review":false}, ...] _auto/_needs_review는 자동 생성 시 사용.',
    )
    region = models.CharField(max_length=200, blank=True, verbose_name='지역')
    total = models.DecimalField(
        max_digits=14,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name='합계',
    )
    version = models.PositiveIntegerField(default=1, verbose_name='버전')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='송부 시각')
    draft_source = models.CharField(
        max_length=10,
        blank=True,
        choices=[
            ('', '—'),
            ('auto', '자동 생성'),
            ('admin', 'Admin 작성'),
        ],
        default='',
        verbose_name='초안 출처',
        help_text='자동 생성 draft vs Admin이 직접 작성·수정한 견적 구분.',
    )
    auto_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='자동 생성 시각',
    )

    class Meta:
        verbose_name = '견적'
        verbose_name_plural = '견적'
        ordering = ['-updated_at']

    def __str__(self):
        return f'견적 #{self.id} ({self.submission.email}) {self.get_status_display()}'

    def customer_can_see_prices(self):
        """고객에게 가격/합계 노출 허용 여부. FINAL_SENT 이상만 True."""
        return self.status in (self.Status.FINAL_SENT, self.Status.PAID)


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
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_customer_plans',
        verbose_name='전담 Agent',
        help_text='결제 후 고객이 선택한 전담 Agent 1명. 서비스별 선택 제거.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = DisplayKey('사용자 정착 플랜')  # 사용자 정착 플랜
        verbose_name_plural = DisplayKey('사용자 정착 플랜')

    def has_schedule(self):
        """일정 데이터가 있는지 (기존 service_schedule JSON 기준). 새 모델은 뷰에서 get_schedule_for_display()로 판단."""
        if not self.service_schedule or not isinstance(self.service_schedule, dict):
            return False
        return bool(self.service_schedule)

    def has_agent_assignment(self):
        """전담 Agent가 있거나 일정에 Agent가 하나라도 할당되어 있으면 True (결제 금액 표시 조건)"""
        if self.assigned_agent_id:
            return True
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
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='일정 확정 시각',
        help_text='Agent가 일정(날짜/시간) 확정 시 기록. 확정 시 고객에게 메시지 발송.',
    )
    confirmed_time_slot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='확정 시간대',
        help_text='Agent가 확정한 시간대(예: 10:00-12:00).',
    )

    class Meta:
        verbose_name = DisplayKey('약속 신청')  # 약속 신청
        verbose_name_plural = DisplayKey('약속 신청')
        ordering = ['-created_at']


class PlanServiceTask(models.Model):
    """
    결제된 견적(approved quote) 기준으로 생성되는 "스케줄 필요 서비스" 목록.
    PAID 시 quote.items에서 자동 생성. Admin이 필요 작업 확인·에이전트 배정 현황 파악용.
    """
    plan = models.ForeignKey(
        UserSettlementPlan,
        on_delete=models.CASCADE,
        related_name='service_tasks',
        verbose_name='정착 플랜',
    )
    service_code = models.CharField(max_length=50, verbose_name='서비스 코드')
    label = models.CharField(max_length=200, blank=True, verbose_name='표시명')
    display_order = models.PositiveIntegerField(default=0, verbose_name='표시 순서')
    appointment = models.OneToOneField(
        AgentAppointmentRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plan_task',
        verbose_name='연결된 약속',
        help_text='고객/Admin이 에이전트 배정 후 생성된 약속.',
    )

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = '플랜 서비스 작업'
        verbose_name_plural = '플랜 서비스 작업'
        unique_together = [('plan', 'service_code')]

    def __str__(self):
        return f'{self.plan_id} · {self.service_code} ({self.label or "-"})'


# --- 스케줄 도메인: ML 초안 / Admin 수정 / 확정 이력 분리. 기존 UserSettlementPlan.service_schedule JSON은 유지하여 하위 호환. ---


class ServiceSchedulePlan(models.Model):
    """
    서비스 일정 "플랜" 1건. draft → reviewing → finalized → sent → active 흐름.
    ML 초안 생성 후 Admin이 수정·확정하고, 고객에게 송부(sent)하면 달력에 반영(active).
    submission/quote/customer로 설문·견적과 연결. 기존 service_schedule JSON 대신 버전·출처·이력 관리용.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '초안'
        REVIEWING = 'REVIEWING', '검토 중'
        FINALIZED = 'FINALIZED', '확정'
        SENT = 'SENT', '고객 송부'
        ACTIVE = 'ACTIVE', '활성(달력 반영)'

    class Source(models.TextChoices):
        ML = 'ML', 'ML 추천'
        ADMIN = 'ADMIN', 'Admin 작성'
        HYBRID = 'HYBRID', 'ML+Admin 혼합'

    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='service_schedule_plans',
        null=True,
        blank=True,
        verbose_name='설문 제출',
    )
    quote = models.ForeignKey(
        'SettlementQuote',
        on_delete=models.CASCADE,
        related_name='service_schedule_plans',
        null=True,
        blank=True,
        verbose_name='견적',
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='service_schedule_plans',
        verbose_name='고객',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name='상태',
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.ADMIN,
        blank=True,
        verbose_name='출처',
    )
    version = models.PositiveIntegerField(default=1, verbose_name='버전')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_schedule_plans',
        verbose_name='생성자',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_schedule_plans',
        verbose_name='수정자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '서비스 일정 플랜'
        verbose_name_plural = '서비스 일정 플랜'
        ordering = ['-updated_at']

    def __str__(self):
        return f'일정 플랜 #{self.id} (v{self.version}, {self.get_status_display()})'


class ServiceScheduleItem(models.Model):
    """
    일정 플랜 내 개별 서비스 1건. 날짜/시간, 담당 Agent, 서비스 유형(직접검색/AI/대면) 등.
    AgentAppointmentRequest와 별도: Item은 "슬롯", Appointment는 실제 약속 신청/확정.
    """
    class ServiceType(models.TextChoices):
        SELF_SEARCH = 'SELF_SEARCH', '직접 검색'
        AI_AGENT = 'AI_AGENT', 'AI 서비스'
        IN_PERSON_AGENT = 'IN_PERSON_AGENT', 'Agent 대면'

    class ItemStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', '예정'
        CONFIRMED = 'CONFIRMED', '확정'
        CANCELLED = 'CANCELLED', '취소'

    schedule_plan = models.ForeignKey(
        ServiceSchedulePlan,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='일정 플랜',
    )
    service_code = models.CharField(max_length=50, verbose_name='서비스 코드')
    service_label = models.CharField(max_length=200, blank=True, verbose_name='서비스 표시명')
    service_type = models.CharField(
        max_length=30,
        choices=ServiceType.choices,
        default=ServiceType.AI_AGENT,
        blank=True,
        verbose_name='서비스 유형',
    )
    starts_at = models.DateTimeField(null=True, blank=True, verbose_name='시작 시각')
    ends_at = models.DateTimeField(null=True, blank=True, verbose_name='종료 시각')
    duration_minutes = models.PositiveIntegerField(null=True, blank=True, verbose_name='소요 시간(분)')
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_schedule_items',
        verbose_name='배정 Agent',
    )
    location_text = models.CharField(max_length=300, blank=True, verbose_name='장소/위치')
    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.SCHEDULED,
        db_index=True,
        verbose_name='상태',
    )
    source_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='ML 추천 점수',
        help_text='ML 생성 시 신뢰도/점수.',
    )
    source_reason = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='출처 사유',
        help_text='ML/Admin 선택 이유 요약.',
    )
    notes = models.TextField(blank=True, verbose_name='메모')
    sort_order = models.PositiveIntegerField(default=0, verbose_name='정렬 순서')

    class Meta:
        verbose_name = '서비스 일정 항목'
        verbose_name_plural = '서비스 일정 항목'
        ordering = ['schedule_plan', 'sort_order', 'starts_at', 'id']

    def __str__(self):
        return f'{self.service_code} @ {self.starts_at or "날짜미정"} ({self.get_status_display()})'


class AgentAvailabilityWindow(models.Model):
    """
    Agent 가용 시간대. when2meet 스타일 수집용.
    manual: Admin/Agent가 직접 입력, link_response: 링크 응답, admin_entered: Admin 대신 입력.
    """
    class Source(models.TextChoices):
        MANUAL = 'manual', '직접 입력'
        LINK_RESPONSE = 'link_response', '링크 응답'
        ADMIN_ENTERED = 'admin_entered', 'Admin 입력'

    class WindowStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', '가능'
        USED = 'USED', '사용됨'
        CANCELLED = 'CANCELLED', '취소'

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='availability_windows',
        verbose_name='Agent',
    )
    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='agent_availability_windows',
        null=True,
        blank=True,
        verbose_name='설문 제출',
    )
    schedule_plan = models.ForeignKey(
        ServiceSchedulePlan,
        on_delete=models.CASCADE,
        related_name='agent_availability_windows',
        null=True,
        blank=True,
        verbose_name='일정 플랜',
    )
    starts_at = models.DateTimeField(verbose_name='시작 시각')
    ends_at = models.DateTimeField(verbose_name='종료 시각')
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
        verbose_name='입력 출처',
    )
    status = models.CharField(
        max_length=20,
        choices=WindowStatus.choices,
        default=WindowStatus.AVAILABLE,
        db_index=True,
        verbose_name='상태',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Agent 가용 시간대'
        verbose_name_plural = 'Agent 가용 시간대'
        ordering = ['agent', 'starts_at']

    def __str__(self):
        return f'{self.agent_id} {self.starts_at}–{self.ends_at} ({self.get_status_display()})'

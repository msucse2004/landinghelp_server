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
    """
    Admin 작성 견적. 설문 제출(SurveySubmission)에 연결. status < FINAL_SENT일 때 고객에게 가격/합계 비노출.

    무효화 정책(견적 삭제 금지):
    - 고객 수정 요청 승인 시 기존 FINAL_SENT 견적을 hard delete 하지 않음.
    - revision_superseded_at 을 설정해 결제만 차단하고, 레코드·메시지·이력은 유지.
    - 결제 가능 여부는 is_payable() 로 판단. Admin은 이전/새 견적 이력을 모두 조회 가능.
    """

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
    revision_superseded_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='수정 요청으로 대체 시각',
        help_text='설문 재개 승인 시 설정. 이 견적은 결제 대상에서 제외(무효화). 레코드는 삭제하지 않음.',
    )
    supersedes = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='superseded_by_quotes',
        verbose_name='대체한 견적',
        help_text='재제출·재견적 흐름에서 이 견적이 대체한 이전 견적. Admin에서 이전/새 견적 관계 추적용.',
    )

    class Meta:
        verbose_name = '견적'
        verbose_name_plural = '견적'
        ordering = ['-updated_at']

    def __str__(self):
        return f'견적 #{self.id} ({self.submission.email}) {self.get_status_display()}'

    def customer_can_see_prices(self):
        """고객에게 가격/합계 노출 허용 여부. FINAL_SENT 이상만 True. 무효화(superseded)여도 이력용으로 노출 가능."""
        return self.status in (self.Status.FINAL_SENT, self.Status.PAID)

    def is_payable(self):
        """
        이 견적이 결제 대상인지. 무효화 정책: hard delete 하지 않고 revision_superseded_at으로 결제만 차단.
        - FINAL_SENT 이고 revision_superseded_at 이 비어 있을 때만 True.
        - PAID 는 이미 결제됐으므로 결제 액션 대상이 아님(여기서는 False로 해석하지 않고, 결제 처리 로직에서 status==PAID 별도 처리).
        """
        if self.status != self.Status.FINAL_SENT:
            return False
        return not bool(getattr(self, 'revision_superseded_at', None))


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
    based_on = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='derived_plans',
        verbose_name='기반 플랜',
        help_text='Admin 조정안 버전이 어떤 이전 플랜을 기반으로 생성됐는지 추적.',
    )
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
    based_on_item = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='derived_items',
        verbose_name='기반 항목',
        help_text='Admin 조정안에서 원본 system draft 항목 추적용.',
    )
    recommendation_source = models.CharField(
        max_length=30,
        blank=True,
        default='fallback',
        verbose_name='추천 출처',
        help_text='historical | rule_based | fallback',
    )
    needs_admin_review = models.BooleanField(
        default=False,
        verbose_name='Admin 검토 필요',
    )
    recommendation_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='추천 메타데이터',
        help_text='confidence/evidence_type/sample_count/day_offset 등 구조화된 추천 근거.',
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


class LsaSourcingBatch(models.Model):
    """
    Admin이 후보 Agent들에게 발송한 LSA 소싱 배치.
    발송 시점의 스케줄/서비스/내부단가를 스냅샷으로 보존한다.
    """

    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='lsa_sourcing_batches',
        verbose_name='설문 제출',
    )
    schedule_plan = models.ForeignKey(
        ServiceSchedulePlan,
        on_delete=models.CASCADE,
        related_name='lsa_sourcing_batches',
        verbose_name='기준 일정 플랜',
    )
    schedule_version = models.PositiveIntegerField(default=1, verbose_name='기준 일정 버전')
    proposed_schedule_snapshot = models.JSONField(default=list, blank=True, verbose_name='제안 일정 스냅샷')
    requested_services_snapshot = models.JSONField(default=list, blank=True, verbose_name='요청 서비스 스냅샷')
    internal_pricing_snapshot = models.JSONField(default=list, blank=True, verbose_name='내부 단가 스냅샷')
    selected_request = models.OneToOneField(
        'LsaAgentRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='selected_for_batch',
        verbose_name='선정된 Agent 요청',
    )
    selected_at = models.DateTimeField(null=True, blank=True, verbose_name='선정 시각')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='배치 종료 시각')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_lsa_sourcing_batches',
        verbose_name='생성자',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'LSA 소싱 배치'
        verbose_name_plural = 'LSA 소싱 배치'
        ordering = ['-created_at']

    def __str__(self):
        return f'LSA Batch #{self.id} (submission={self.submission_id}, plan_v={self.schedule_version})'


class LsaAgentRequest(models.Model):
    """
    LSA 소싱 배치의 Agent별 발송 레코드.
    payload_snapshot은 발송 시점 문서(JSON)를 그대로 보존한다.
    """

    class Status(models.TextChoices):
        SENT = 'SENT', '발송됨'
        RESPONDED = 'RESPONDED', '응답함'
        DECLINED = 'DECLINED', '거절'
        SELECTED = 'SELECTED', '선정됨'
        NOT_SELECTED = 'NOT_SELECTED', '미선정'
        CANCELLED = 'CANCELLED', '취소'

    batch = models.ForeignKey(
        LsaSourcingBatch,
        on_delete=models.CASCADE,
        related_name='agent_requests',
        verbose_name='LSA 배치',
    )
    target_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lsa_agent_requests',
        verbose_name='대상 Agent',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
        db_index=True,
        verbose_name='상태',
    )
    payload_snapshot = models.JSONField(default=dict, blank=True, verbose_name='발송 payload 스냅샷')
    sent_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name='응답 시각')

    class Meta:
        verbose_name = 'LSA Agent 요청'
        verbose_name_plural = 'LSA Agent 요청'
        ordering = ['-sent_at']
        unique_together = [('batch', 'target_agent')]

    def __str__(self):
        return f'LSA Request #{self.id} (batch={self.batch_id}, agent={self.target_agent_id})'


class LsaAgentResponse(models.Model):
    """
    Agent의 LSA 요청 응답(리비전 이력).
    """

    class Decision(models.TextChoices):
        ACCEPT_AS_IS = 'ACCEPT_AS_IS', '제안 일정 그대로 수락'
        PARTIAL = 'PARTIAL', '일부 수락/일부 조정'
        DECLINE = 'DECLINE', '전체 거절'

    request = models.ForeignKey(
        LsaAgentRequest,
        on_delete=models.CASCADE,
        related_name='responses',
        verbose_name='LSA Agent 요청',
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lsa_responses',
        verbose_name='응답 Agent',
    )
    decision = models.CharField(
        max_length=20,
        choices=Decision.choices,
        default=Decision.ACCEPT_AS_IS,
        db_index=True,
        verbose_name='응답 결정',
    )
    note = models.TextField(blank=True, verbose_name='응답 메모')
    revision = models.PositiveIntegerField(default=1, verbose_name='응답 리비전')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'LSA Agent 응답'
        verbose_name_plural = 'LSA Agent 응답'
        ordering = ['-created_at']
        unique_together = [('request', 'revision')]

    def __str__(self):
        return f'LSA Response #{self.id} (request={self.request_id}, rev={self.revision})'


class LsaAgentResponseItem(models.Model):
    """
    서비스별 응답 상세(수락/변경제안/불가).
    """

    class Action(models.TextChoices):
        ACCEPT = 'ACCEPT', '수락'
        SUGGEST_CHANGE = 'SUGGEST_CHANGE', '변경 제안'
        UNAVAILABLE = 'UNAVAILABLE', '불가'

    response = models.ForeignKey(
        LsaAgentResponse,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='LSA 응답',
    )
    service_code = models.CharField(max_length=50, blank=True, verbose_name='서비스 코드')
    service_label = models.CharField(max_length=200, blank=True, verbose_name='서비스 표시명')
    proposed_starts_at = models.DateTimeField(null=True, blank=True, verbose_name='제안 시작 시각')
    proposed_ends_at = models.DateTimeField(null=True, blank=True, verbose_name='제안 종료 시각')
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        default=Action.ACCEPT,
        verbose_name='서비스별 응답',
    )
    suggested_starts_at = models.DateTimeField(null=True, blank=True, verbose_name='제안 변경 시작 시각')
    suggested_ends_at = models.DateTimeField(null=True, blank=True, verbose_name='제안 변경 종료 시각')
    note = models.TextField(blank=True, verbose_name='항목 메모')

    class Meta:
        verbose_name = 'LSA Agent 응답 항목'
        verbose_name_plural = 'LSA Agent 응답 항목'
        ordering = ['id']

    def __str__(self):
        return f'LSA Response Item #{self.id} ({self.service_code})'


class LsaAgentContract(models.Model):
    """
    LSA 배치에서 Admin이 최종 선정한 Agent 계약 레코드.
    배치당 정확히 1건만 허용한다.
    """

    batch = models.OneToOneField(
        LsaSourcingBatch,
        on_delete=models.CASCADE,
        related_name='contract',
        verbose_name='LSA 배치',
    )
    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='lsa_agent_contracts',
        verbose_name='설문 제출',
    )
    schedule_plan = models.ForeignKey(
        ServiceSchedulePlan,
        on_delete=models.CASCADE,
        related_name='lsa_agent_contracts',
        verbose_name='일정 플랜',
    )
    selected_request = models.ForeignKey(
        LsaAgentRequest,
        on_delete=models.PROTECT,
        related_name='contracts',
        verbose_name='선정 요청',
    )
    selected_response = models.ForeignKey(
        LsaAgentResponse,
        on_delete=models.PROTECT,
        related_name='contracts',
        null=True,
        blank=True,
        verbose_name='선정 응답',
    )
    execution_schedule_plan = models.OneToOneField(
        ServiceSchedulePlan,
        on_delete=models.PROTECT,
        related_name='execution_contract',
        null=True,
        blank=True,
        verbose_name='최종 실행 일정 플랜',
    )
    selected_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='selected_lsa_contracts',
        verbose_name='선정 Agent',
    )
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_lsa_contracts',
        verbose_name='선정 Admin',
    )
    selection_note = models.TextField(blank=True, verbose_name='선정 메모')
    audit_payload = models.JSONField(default=dict, blank=True, verbose_name='감사 추적 payload')
    selected_at = models.DateTimeField(auto_now_add=True, verbose_name='선정 시각')

    class Meta:
        verbose_name = 'LSA Agent 계약'
        verbose_name_plural = 'LSA Agent 계약'
        ordering = ['-selected_at']

    def __str__(self):
        return f'LSA Contract #{self.id} (batch={self.batch_id}, agent={self.selected_agent_id})'


# --- 견적 변경 요청: 구조화 요청 + LLM 해석 + 실행 로그 (hard delete 없이 상태/이력 중심) ---


class QuoteChangeRequest(models.Model):
    """
    고객의 견적 수정 요청 1건. 자유 텍스트 또는 구조화 입력.
    LLM 해석(QuoteChangeAnalysis)과 실행 로그(QuoteChangeActionLog)와 연결.
    """

    class SourceType(models.TextChoices):
        TEXT = 'TEXT', '자유 텍스트'
        STRUCTURED = 'STRUCTURED', '구조화'
        MIXED = 'MIXED', '혼합'

    class Status(models.TextChoices):
        OPEN = 'OPEN', '접수'
        ANALYZED = 'ANALYZED', '분석 완료'
        IN_REVIEW = 'IN_REVIEW', '검토 중'
        APPROVED = 'APPROVED', '승인'
        REJECTED = 'REJECTED', '반려'
        CUSTOMER_ACTION_REQUIRED = 'CUSTOMER_ACTION_REQUIRED', '고객 조치 대기'
        APPLIED = 'APPLIED', '적용 완료'
        CANCELED = 'CANCELED', '취소'

    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        related_name='quote_change_requests',
        verbose_name='설문 제출',
    )
    quote = models.ForeignKey(
        SettlementQuote,
        on_delete=models.CASCADE,
        related_name='change_requests',
        verbose_name='대상 견적',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quote_change_requests',
        verbose_name='요청자',
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.TEXT,
        db_index=True,
        verbose_name='입력 유형',
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name='상태',
    )
    customer_message = models.TextField(blank=True, verbose_name='고객 메시지')
    admin_note = models.TextField(blank=True, verbose_name='Admin 메모')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='검토 시각')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='처리 완료 시각')

    class Meta:
        verbose_name = '견적 변경 요청'
        verbose_name_plural = '견적 변경 요청'
        ordering = ['-created_at']

    def __str__(self):
        return f'변경요청 #{self.id} (견적 #{self.quote_id}, {self.get_status_display()})'

    def can_run_llm_analysis(self):
        """LLM 분석을 실행해도 되는 상태인지. OPEN이고 아직 분석이 없거나 재분석 허용 시 True."""
        if self.status not in (self.Status.OPEN, self.Status.ANALYZED):
            return False
        return True

    def can_be_reopened_for_survey_edit(self):
        """설문 재개(고객 수정) 플로우를 실행할 수 있는지. submission이 재개 가능 상태이고 요청이 승인/적용 대기 등일 때."""
        if not self.submission_id:
            return False
        from survey.models import SurveySubmission
        return self.submission.status in (
            SurveySubmission.Status.SUBMITTED,
            SurveySubmission.Status.AWAITING_PAYMENT,
        ) and self.status in (
            self.Status.APPROVED,
            self.Status.IN_REVIEW,
            self.Status.ANALYZED,
        )

    def has_pending_customer_action(self):
        """고객 측 조치가 필요한 상태인지 (예: 설문 수정 링크 발송 후 대기)."""
        return self.status == self.Status.CUSTOMER_ACTION_REQUIRED

    def latest_analysis(self):
        """가장 최근 LLM 분석 결과. 없으면 None."""
        return getattr(self, '_analysis', None) or self.analyses.order_by('-created_at').first()


class QuoteChangeRequestItem(models.Model):
    """견적 변경 요청의 항목 단위 (추가/제거/변경)."""

    class ActionType(models.TextChoices):
        ADD = 'ADD', '추가'
        REMOVE = 'REMOVE', '제거'
        CHANGE = 'CHANGE', '변경'

    change_request = models.ForeignKey(
        QuoteChangeRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='변경 요청',
    )
    action_type = models.CharField(
        max_length=20,
        choices=ActionType.choices,
        db_index=True,
        verbose_name='액션 유형',
    )
    service_code = models.CharField(max_length=50, blank=True, db_index=True, verbose_name='서비스 코드')
    service_label = models.CharField(max_length=200, blank=True, verbose_name='서비스 표시명')
    payload = models.JSONField(default=dict, blank=True, verbose_name='추가 데이터')
    display_order = models.PositiveIntegerField(default=0, verbose_name='표시 순서')

    class Meta:
        verbose_name = '견적 변경 요청 항목'
        verbose_name_plural = '견적 변경 요청 항목'
        ordering = ['change_request', 'display_order', 'id']

    def __str__(self):
        return f'{self.get_action_type_display()} {self.service_code or "-"} (요청 #{self.change_request_id})'


class QuoteChangeAnalysis(models.Model):
    """LLM 해석 결과 저장. 요청당 최신 1건만 사용해도 되고, 이력은 여러 건 허용."""

    class DetectedIntent(models.TextChoices):
        QUOTE_ITEM_CHANGE_REQUEST = 'QUOTE_ITEM_CHANGE_REQUEST', '견적 항목 변경 요청'
        SURVEY_REOPEN_REQUEST = 'SURVEY_REOPEN_REQUEST', '설문 재개 요청'
        GENERAL_QUESTION = 'GENERAL_QUESTION', '일반 문의'
        UNSUPPORTED_REQUEST = 'UNSUPPORTED_REQUEST', '미지원 요청'
        URGENT_ADMIN_REVIEW = 'URGENT_ADMIN_REVIEW', 'Admin 수동 검토'

    change_request = models.ForeignKey(
        QuoteChangeRequest,
        on_delete=models.CASCADE,
        related_name='analyses',
        verbose_name='변경 요청',
    )
    model_name = models.CharField(max_length=100, blank=True, verbose_name='LLM 모델명')
    raw_customer_message = models.TextField(verbose_name='원문 고객 메시지')
    normalized_summary = models.TextField(blank=True, verbose_name='정규화 요약')
    detected_intent = models.CharField(
        max_length=40,
        choices=DetectedIntent.choices,
        db_index=True,
        verbose_name='감지된 의도',
    )
    confidence = models.FloatField(
        default=0.0,
        verbose_name='신뢰도',
        help_text='0.0~1.0. 이 값이 낮으면 수동 검토 권장.',
    )
    extracted_actions = models.JSONField(
        default=list,
        blank=True,
        verbose_name='추출된 액션 목록',
        help_text='[{"action": "PROPOSE_ADD_SERVICE", "service_code": "X", ...}, ...]',
    )
    extracted_service_codes = models.JSONField(
        default=list,
        blank=True,
        verbose_name='추출된 서비스 코드 목록',
    )
    requires_admin_confirmation = models.BooleanField(
        default=True,
        verbose_name='Admin 확인 필요',
    )
    recommended_next_step = models.CharField(max_length=500, blank=True, verbose_name='추천 다음 단계')
    raw_llm_output = models.JSONField(default=dict, blank=True, verbose_name='LLM 원시 출력')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '견적 변경 LLM 분석'
        verbose_name_plural = '견적 변경 LLM 분석'
        ordering = ['-created_at']

    def __str__(self):
        return f'분석 #{self.id} ({self.change_request_id}, {self.get_detected_intent_display()})'


class QuoteChangeActionLog(models.Model):
    """누가 어떤 추천 액션을 승인/실행했는지 이력."""

    class ActionType(models.TextChoices):
        ANALYSIS_CREATED = 'ANALYSIS_CREATED', '분석 생성'
        ADMIN_APPROVED_REOPEN = 'ADMIN_APPROVED_REOPEN', 'Admin 설문 재개 승인'
        ADMIN_APPROVED_QUOTE_REVISION = 'ADMIN_APPROVED_QUOTE_REVISION', 'Admin 견적 수정 승인'
        ADMIN_REJECTED = 'ADMIN_REJECTED', 'Admin 반려'
        SURVEY_REOPENED = 'SURVEY_REOPENED', '설문 재개 실행'
        QUOTE_SUPERSEDED = 'QUOTE_SUPERSEDED', '견적 대체(수정본 생성)'
        MESSAGE_SENT = 'MESSAGE_SENT', '메시지 발송'
        CUSTOMER_RESUME_LINK_CREATED = 'CUSTOMER_RESUME_LINK_CREATED', '고객 설문 링크 생성'

    change_request = models.ForeignKey(
        QuoteChangeRequest,
        on_delete=models.CASCADE,
        related_name='action_logs',
        verbose_name='변경 요청',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_change_action_logs',
        verbose_name='실행자',
    )
    action_type = models.CharField(
        max_length=50,
        choices=ActionType.choices,
        db_index=True,
        verbose_name='액션 유형',
    )
    detail = models.JSONField(default=dict, blank=True, verbose_name='상세')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '견적 변경 액션 로그'
        verbose_name_plural = '견적 변경 액션 로그'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_type_display()} (요청 #{self.change_request_id}, {self.created_at})'


class CustomerActionOffer(models.Model):
    """
    고객 액션 제안(버튼). 서버 truth 기반으로 노출 여부·실행 가능 여부 결정.
    버튼 클릭 전에는 실제 상태 전이 없음. execute_confirmed_action() 호출 시에만 실행.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', '대기'
        EXECUTED = 'EXECUTED', '실행됨'
        EXPIRED = 'EXPIRED', '만료'
        CANCELED = 'CANCELED', '취소'

    title = models.CharField(max_length=200, blank=True, verbose_name='제목')
    body = models.TextField(blank=True, verbose_name='본문')
    button_label = models.CharField(max_length=100, verbose_name='버튼 라벨')
    button_action_key = models.CharField(
        max_length=80,
        db_index=True,
        verbose_name='버튼 액션 키',
        help_text='예: survey_reopen, survey_resume, quote_resend',
    )
    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_offers',
        verbose_name='설문 제출',
    )
    quote = models.ForeignKey(
        'SettlementQuote',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_offers',
        verbose_name='견적',
    )
    change_request = models.ForeignKey(
        QuoteChangeRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_offers',
        verbose_name='변경 요청',
    )
    conversation = models.ForeignKey(
        'messaging.Conversation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_offers',
        verbose_name='대화',
    )
    trigger_message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_action_offers',
        verbose_name='트리거 메시지',
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='만료 시각')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='상태',
    )
    can_execute = models.BooleanField(
        default=True,
        verbose_name='실행 가능',
        help_text='서버에서 판단한 실행 가능 여부.',
    )
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name='실행 시각')
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executed_action_offers',
        verbose_name='실행자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '고객 액션 제안'
        verbose_name_plural = '고객 액션 제안'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.button_action_key} #{self.id} ({self.get_status_display()})'


class HumanReviewRequest(models.Model):
    """
    사람 검토가 필요한 고객 요청 1건.
    HUMAN_REVIEW_REQUIRED 시 생성. admin / agent / admin_then_agent 로 라우팅.
    담당자 최종 응답 시 COMPLETED 로 종료.
    """

    class ReviewTarget(models.TextChoices):
        admin = 'admin', 'Admin 검토'
        agent = 'agent', 'Agent 검토'
        admin_then_agent = 'admin_then_agent', 'Admin 후 Agent'

    class Status(models.TextChoices):
        RECEIVED = 'RECEIVED', '접수됨'
        IN_REVIEW = 'IN_REVIEW', '검토 중'
        NEEDS_INFO = 'NEEDS_INFO', '추가 확인 필요'
        COMPLETED = 'COMPLETED', '답변 완료'

    conversation = models.ForeignKey(
        'messaging.Conversation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='human_review_requests',
        verbose_name='대화',
    )
    trigger_message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_human_review_requests',
        verbose_name='트리거 메시지',
    )
    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='human_review_requests',
        verbose_name='설문 제출',
    )
    quote = models.ForeignKey(
        'SettlementQuote',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='human_review_requests',
        verbose_name='견적',
    )
    change_request = models.ForeignKey(
        QuoteChangeRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='human_review_requests',
        verbose_name='변경 요청',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='human_review_requests',
        verbose_name='요청자',
    )
    review_target = models.CharField(
        max_length=30,
        choices=ReviewTarget.choices,
        db_index=True,
        verbose_name='검토 담당',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
        db_index=True,
        verbose_name='상태',
    )
    original_message = models.TextField(blank=True, verbose_name='원문 메시지')
    detected_intent = models.CharField(max_length=80, blank=True, db_index=True, verbose_name='LLM intent')
    recommended_action = models.CharField(max_length=80, blank=True, verbose_name='recommended action')
    execution_mode = models.CharField(max_length=40, blank=True, verbose_name='execution mode')
    confidence = models.FloatField(default=0.0, verbose_name='confidence')
    suggested_internal_next_step = models.TextField(blank=True, verbose_name='내부 권장 다음 단계')
    suggested_customer_reply = models.TextField(blank=True, verbose_name='권장 고객 응답 문구')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_human_review_requests',
        verbose_name='담당자',
    )
    appointment = models.ForeignKey(
        'AgentAppointmentRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='human_review_requests',
        verbose_name='약속',
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='처리 완료 시각')
    completed_note = models.TextField(blank=True, verbose_name='처리 메모')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '사람 검토 요청'
        verbose_name_plural = '사람 검토 요청'
        ordering = ['-created_at']

    def __str__(self):
        return f'검토 #{self.id} ({self.get_review_target_display()}, {self.get_status_display()})'

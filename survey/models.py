"""
설문: 카드/섹션(SurveySection) + 문항(SurveyQuestion) + 제출/초안(SurveySubmission).
Admin은 카드 단위로 설문을 구성하고, 문항을 카드에 묶어 관리.
DRAFT 상태에서는 answers가 부분적으로만 있어도 저장 가능.
"""
from django.db import models
from django.conf import settings


class SurveySection(models.Model):
    """
    설문 카드/섹션. Admin이 카드 단위로 설문을 구성.
    - 제목, 설명, 표시 순서, 활성 여부
    - is_internal=True: Admin 전용(고객 비노출), False: 고객 노출
    - visibility_condition: 선택적 조건부 노출 (JSON, 예: {"depends_on": "key", "value": "x"})
    """
    title = models.CharField(max_length=200, verbose_name='카드 제목')
    description = models.TextField(blank=True, verbose_name='카드 설명/도움말')
    display_order = models.PositiveIntegerField(default=0, verbose_name='표시 순서')
    is_active = models.BooleanField(default=True, verbose_name='활성')
    is_internal = models.BooleanField(
        default=False,
        verbose_name='Admin 전용',
        help_text='True면 고객 설문에 노출되지 않음(내부용).',
    )
    visibility_condition = models.JSONField(
        null=True,
        blank=True,
        verbose_name='조건부 노출',
        help_text='선택. 예: {"depends_on": "question_key", "value": "expected"}',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = '설문'
        verbose_name_plural = '설문'

    def __str__(self):
        return f'{self.title} (순서 {self.display_order})'


class SurveyQuestion(models.Model):
    """
    설문 문항. 카드(SurveySection)에 소속되거나 기존처럼 step으로만 사용 가능.
    - section이 있으면 카드 내 order_in_section으로 정렬.
    - section이 없으면 step/order로 기존 Wizard 동작 유지.
    """

    class FieldType(models.TextChoices):
        TEXT = 'text', '텍스트'
        TEXTAREA = 'textarea', '긴 텍스트'
        SELECT = 'select', '선택(단일)'
        RADIO = 'radio', '라디오'
        CHECKBOX = 'checkbox', '체크박스(다중)'
        NUMBER = 'number', '숫자'
        DATE = 'date', '날짜'
        EMAIL = 'email', '이메일'

    section = models.ForeignKey(
        SurveySection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questions',
        verbose_name='소속 카드(섹션)',
        help_text='비어 있으면 기존 step/order로만 사용.',
    )
    order_in_section = models.PositiveIntegerField(
        default=0,
        verbose_name='카드 내 순서',
        help_text='같은 카드 안에서의 표시 순서.',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='표시 순서')
    step = models.PositiveIntegerField(default=1, verbose_name='단계')
    key = models.CharField(max_length=100, unique=True, verbose_name='키')
    label = models.CharField(max_length=300, verbose_name='라벨')
    field_type = models.CharField(
        max_length=20,
        choices=FieldType.choices,
        default=FieldType.TEXT,
        verbose_name='필드 타입',
    )
    required = models.BooleanField(default=False, verbose_name='필수')
    choices = models.JSONField(
        default=list,
        blank=True,
        verbose_name='선택지',
        help_text='select/radio/checkbox 시 [{"value":"x","label":"X"}, ...]',
    )
    help_text = models.CharField(max_length=500, blank=True, verbose_name='도움말')
    placeholder = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='placeholder',
        help_text='입력 필드 placeholder 텍스트.',
    )
    quote_relevant = models.BooleanField(
        default=False,
        verbose_name='견적 반영',
        help_text='True면 자동 견적 초안 생성 시 이 답변을 참고.',
    )
    quote_mapping_key = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='견적 매핑 키',
        help_text='견적 입력 정규화용 캐노니컬 키. service_codes, region, entry_date, household_size, add_on_codes, special_requirements 등.',
    )
    quote_value_type = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('', '—'),
            ('service_codes', '서비스 코드 목록'),
            ('region', '지역(문자열)'),
            ('date', '날짜(YYYY-MM-DD)'),
            ('number', '숫자'),
            ('options', '선택값(단일/다중)'),
            ('text', '자유 텍스트'),
        ],
        default='',
        verbose_name='견적 값 유형',
        help_text='답변을 어떻게 해석할지. 정규화 시 참고.',
    )
    is_active = models.BooleanField(default=True, verbose_name='활성')

    class Meta:
        # 관리자 인라인·고객 설문 모두 카드 내 순서(order_in_section)로 통일
        ordering = ['step', 'order_in_section', 'order']
        verbose_name = '설문 문항'
        verbose_name_plural = '설문 문항'

    def __str__(self):
        if self.section_id and self.section:
            return f'{self.section.title} / {self.key}: {self.label}'
        return f'[{self.step}] {self.key}: {self.label}'

    def is_customer_visible(self):
        """고객 설문에 노출되는지. 카드에 묶인 경우 카드가 활성이고 비내부일 때만 True."""
        if not self.section_id:
            return True  # step 기반 문항은 기존처럼 노출
        if not self.section:
            return True
        return self.section.is_active and not self.section.is_internal


class SurveySubmission(models.Model):
    """
    설문 제출 = 요청 서류(request dossier). 제출 후에도 수정 요청 시 재편집·재제출 가능.
    워크플로우: DRAFT → SUBMITTED → (선택) REVISION_REQUESTED → SUBMITTED → AWAITING_PAYMENT → AGENT_ASSIGNMENT → SERVICE_IN_PROGRESS
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '고객 설문 작성중'
        SUBMITTED = 'SUBMITTED', 'Admin 검토중'
        REVISION_REQUESTED = 'REVISION_REQUESTED', '고객 수정 요청됨'
        AWAITING_PAYMENT = 'AWAITING_PAYMENT', '고객 결재 대기중'
        AGENT_ASSIGNMENT = 'AGENT_ASSIGNMENT', 'Agent 할당 중'
        SERVICE_IN_PROGRESS = 'SERVICE_IN_PROGRESS', '서비스 진행중'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='survey_submissions',
        verbose_name='사용자',
    )
    email = models.EmailField(verbose_name='이메일')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name='상태',
    )
    current_step = models.PositiveIntegerField(default=1, verbose_name='현재 단계')
    answers = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='답변',
        help_text='key -> value. DRAFT 시 일부만 있어도 저장 가능.',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 저장 시각')
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='제출 시각')
    last_reminded_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='마지막 리마인드 발송 시각',
        help_text='24시간마다 DRAFT 미제출자에게 리마인드 이메일 발송 시 갱신. 하루 1회 제한.',
    )

    preferred_support_mode = models.CharField(max_length=100, blank=True, verbose_name='선호 지원 방식')
    requested_required_services = models.JSONField(
        default=list,
        blank=True,
        verbose_name='필수 요청 서비스',
        help_text='서비스 코드 목록',
    )
    requested_optional_services = models.JSONField(
        default=list,
        blank=True,
        verbose_name='선택 요청 서비스',
        help_text='서비스 코드 목록',
    )
    revision_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='수정 요청 시각',
        help_text='Admin이 고객에게 수정을 요청한 시각.',
    )
    revision_requested_message = models.TextField(
        blank=True,
        verbose_name='수정 요청 메시지',
        help_text='고객에게 전달할 수정 요청 안내(선택).',
    )
    revision_count = models.PositiveIntegerField(
        default=0,
        verbose_name='수정 재개 횟수',
        help_text='Admin이 설문 재개를 승인한 횟수. 재제출 시 리셋하지 않음.',
    )
    reopened_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='최근 재개 시각',
        help_text='Admin이 설문 수정을 승인한 시각.',
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name = '설문 제출'
        verbose_name_plural = '설문 제출'
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(user__isnull=False),
                name='survey_one_submission_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.email} ({self.get_status_display()}) @ {self.updated_at}'

    def get_service_progress(self):
        """
        서비스 진행중(status=SERVICE_IN_PROGRESS)일 때 (완료 수, 전체 수) 반환.
        고객의 AgentAppointmentRequest 중 CANCELLED 제외한 전체, CONFIRMED 건수.
        """
        if self.status != self.Status.SERVICE_IN_PROGRESS or not self.user_id:
            return 0, 0
        from settlement.models import AgentAppointmentRequest
        qs = AgentAppointmentRequest.objects.filter(customer_id=self.user_id).exclude(status='CANCELLED')
        total = qs.count()
        completed = qs.filter(status='CONFIRMED').count()
        return completed, total

    def can_customer_edit(self):
        """고객이 이 요청을 편집할 수 있는지 (DRAFT 또는 Admin이 수정 요청한 경우)."""
        return self.status in (self.Status.DRAFT, self.Status.REVISION_REQUESTED)


class SurveySubmissionEvent(models.Model):
    """요청 서류의 중요 변경 이력(감사 로그). 자동화·협업 추적용."""

    class EventType(models.TextChoices):
        SUBMITTED = 'submitted', '제출'
        REVISION_REQUESTED = 'revision_requested', '수정 요청'
        REOPENED = 'reopened', '재개 승인'
        SECTIONS_UPDATE_REQUESTED = 'sections_update_requested', '카드별 수정 요청'
        RESUBMITTED = 'resubmitted', '재제출'
        QUOTE_SENT = 'quote_sent', '견적 송부'
        PAID = 'paid', '결제 완료'
        SCHEDULE_SENT = 'schedule_sent', '일정 송부'

    submission = models.ForeignKey(
        SurveySubmission,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name='설문 제출',
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        verbose_name='이벤트',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='발생 시각')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='survey_submission_events',
        verbose_name='작업자',
    )
    meta = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='메타',
        help_text='예: {"message": "입력일 수정 요청"}',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = '제출 이벤트'
        verbose_name_plural = '제출 이벤트'

    def __str__(self):
        return f'{self.submission_id} / {self.get_event_type_display()} @ {self.created_at}'


class SurveySubmissionSectionRequest(models.Model):
    """
    Admin이 특정 카드(섹션)만 고객에게 수정을 요청한 기록.
    고객이 해당 카드들을 수정 후 재제출하면 resolved_at 설정.
    """
    submission = models.ForeignKey(
        SurveySubmission,
        on_delete=models.CASCADE,
        related_name='section_requests',
        verbose_name='설문 제출',
    )
    section = models.ForeignKey(
        SurveySection,
        on_delete=models.CASCADE,
        related_name='submission_requests',
        verbose_name='수정 요청 카드',
    )
    message = models.TextField(blank=True, verbose_name='요청 메시지', help_text='해당 카드에 대한 안내(선택).')
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name='요청 시각')
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='survey_section_requests',
        verbose_name='요청자',
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='해결 시각', help_text='고객 수정·재제출 시 설정.')

    class Meta:
        ordering = ['section__display_order', 'id']
        verbose_name = '제출 카드별 수정 요청'
        verbose_name_plural = '제출 카드별 수정 요청'

    def __str__(self):
        return f'{self.submission_id} · {self.section.title} ({"해결" if self.resolved_at else "대기"})'

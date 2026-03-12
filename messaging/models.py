# messaging: 고객↔에이전트 약속 대화, 관리자 공지
from django.conf import settings
from django.db import models
from typing import List


class Conversation(models.Model):
    """대화/스레드. 약속 요청에 연결되거나 관리자 공지용."""

    class Type(models.TextChoices):
        APPOINTMENT = 'APPOINTMENT', '약속 대화'
        NOTICE = 'NOTICE', '공지'
        AI_ASSISTANT = 'AI_ASSISTANT', 'AI 어시스턴트'

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.APPOINTMENT,
    )
    appointment = models.ForeignKey(
        'settlement.AgentAppointmentRequest',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversations',
        verbose_name='약속 신청',
    )
    survey_submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversations',
        verbose_name='설문 제출',
        help_text='공지 대화가 설문 제출/견적 알림일 때 연결된 제출 건.',
    )
    subject = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='제목',
        help_text='공지일 때 제목',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '대화'
        verbose_name_plural = '대화'
        ordering = ['-updated_at']

    def __str__(self):
        if self.appointment_id:
            return f'약속 대화 #{self.appointment_id}'
        return self.subject or f'공지 #{self.pk}'


class ConversationParticipant(models.Model):
    """대화 참여자 (누가 이 대화를 볼 수 있는지)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation_participations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '대화 참여자'
        verbose_name_plural = '대화 참여자'
        unique_together = [['conversation', 'user']]
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user.username} in conv #{self.conversation_id}'


class Message(models.Model):
    """대화 안의 메시지 한 건."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='보낸 사람',
    )
    body = models.TextField(verbose_name='내용', blank=True)
    detected_lang = models.CharField(
        max_length=10,
        blank=True,
        verbose_name='감지된 언어',
        help_text='langdetect 결과 (ko, en 등). 영어가 아니면 body_en에 번역 저장.',
    )
    body_en = models.TextField(
        blank=True,
        verbose_name='영어 번역',
        help_text='원문이 영어가 아닐 때 DeepL로 번역한 영어 본문.',
    )
    image = models.ImageField(
        upload_to='messaging/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='첨부 이미지',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '메시지'
        verbose_name_plural = '메시지'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender.username}: {self.body[:30]}...'


class MessageTranslation(models.Model):
    """메시지 본문의 언어별 번역 캐시 (수신자 선호어 표시용)."""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='translations_by_lang',
    )
    language_code = models.CharField(max_length=20, verbose_name='언어 코드')
    body = models.TextField(verbose_name='번역된 본문', blank=True)

    class Meta:
        verbose_name = '메시지 번역'
        verbose_name_plural = '메시지 번역'
        unique_together = [['message', 'language_code']]
        ordering = ['language_code']

    def __str__(self):
        return f'msg #{self.message_id} ({self.language_code})'


class MessageRead(models.Model):
    """메시지 읽음 상태 (알림/미읽음 표시용)."""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='read_by',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_reads',
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '메시지 읽음'
        verbose_name_plural = '메시지 읽음'
        unique_together = [['message', 'user']]
        ordering = ['read_at']

    def __str__(self):
        return f'{self.user.username} read msg #{self.message_id}'


# ---------------------------------------------------------------------------
# 고객 요청 분류·제안·피드백 모델
# ---------------------------------------------------------------------------


class CustomerRequestIntentAnalysis(models.Model):
    """
    고객 메시지에 대한 intent 분류 결과.

    메시지 수신 직후 LLM/휴리스틱이 분류한 결과를 1:1 저장.
    실제 상태 변경은 하지 않으며, 이후 CustomerActionProposal 생성의 근거가 됨.

    사용처:
    - customer_request_service._save_intent_analysis() 에서 PolicyResult → 레코드 생성
    - customer_request_service.build_customer_ui_payload() 에서 최신 분석 결과 참조
    """

    class PredictedIntent(models.TextChoices):
        SURVEY_REOPEN_REQUEST = 'SURVEY_REOPEN_REQUEST', '설문 재수정 요청'
        SURVEY_RESUME_REQUEST = 'SURVEY_RESUME_REQUEST', '설문 이어쓰기 요청'
        QUOTE_RESEND_REQUEST = 'QUOTE_RESEND_REQUEST', '견적 재발송 요청'
        QUOTE_ITEM_CHANGE_REQUEST = 'QUOTE_ITEM_CHANGE_REQUEST', '견적 항목 변경 요청'
        SCHEDULE_CHANGE_REQUEST = 'SCHEDULE_CHANGE_REQUEST', '일정 변경 요청'
        AGENT_CHANGE_REQUEST = 'AGENT_CHANGE_REQUEST', '담당자 변경 요청'
        PRICING_NEGOTIATION_REQUEST = 'PRICING_NEGOTIATION_REQUEST', '가격 협상 요청'
        GENERAL_QUESTION = 'GENERAL_QUESTION', '일반 문의'
        STATUS_CHECK = 'STATUS_CHECK', '진행 상태 확인'
        UNSUPPORTED_REQUEST = 'UNSUPPORTED_REQUEST', '미지원 요청'

    class PredictedAction(models.TextChoices):
        OFFER_SURVEY_REOPEN = 'OFFER_SURVEY_REOPEN', '설문 재수정 제안'
        OFFER_SURVEY_RESUME = 'OFFER_SURVEY_RESUME', '설문 이어쓰기 제안'
        OFFER_QUOTE_RESEND = 'OFFER_QUOTE_RESEND', '견적 재발송 제안'
        OFFER_QUOTE_REVISION_REQUEST = 'OFFER_QUOTE_REVISION_REQUEST', '견적 수정 요청 제안'
        ROUTE_TO_ADMIN_REVIEW = 'ROUTE_TO_ADMIN_REVIEW', 'Admin 검토 라우팅'
        ROUTE_TO_AGENT_REVIEW = 'ROUTE_TO_AGENT_REVIEW', 'Agent 검토 라우팅'
        ROUTE_TO_ADMIN_THEN_AGENT = 'ROUTE_TO_ADMIN_THEN_AGENT', 'Admin→Agent 라우팅'
        REPLY_WITH_INFORMATION = 'REPLY_WITH_INFORMATION', '정보 안내 응답'
        REPLY_WITH_STATUS = 'REPLY_WITH_STATUS', '상태 안내 응답'

    class PredictedExecutionMode(models.TextChoices):
        AUTO_CONFIRMABLE = 'AUTO_CONFIRMABLE', '자동 제안 (고객 확인)'
        HUMAN_REVIEW_REQUIRED = 'HUMAN_REVIEW_REQUIRED', '사람 검토 필요'
        REPLY_ONLY = 'REPLY_ONLY', '응답만'

    class AnalysisSource(models.TextChoices):
        HEURISTIC = 'heuristic', '휴리스틱 규칙'
        SEMANTIC = 'semantic', '시맨틱 유사도'
        SEMANTIC_SAFE = 'semantic_safe', '시맨틱 유사도(안전 게이트)'
        SEMANTIC_LOCAL = 'semantic_local', '시맨틱+로컬 앙상블'
        SEMANTIC_LOCAL_SAFE = 'semantic_local_safe', '시맨틱+로컬 앙상블(안전 게이트)'
        GEMINI = 'gemini', 'Gemini LLM'
        OLLAMA = 'ollama', 'Ollama LLM'
        STUB = 'stub', 'Stub (미연동)'
        RETRIEVAL = 'retrieval', '검색 기반'
        LOCAL_CLASSIFIER = 'local_classifier', '로컬 분류기'
        LOCAL_CLASSIFIER_SAFE = 'local_classifier_safe', '로컬 분류기(안전 게이트)'
        QUOTE_LLM = 'quote_llm', '견적 변경 LLM'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='request_intent_analyses',
        verbose_name='고객',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='intent_analyses',
        verbose_name='대화',
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='intent_analyses',
        verbose_name='트리거 메시지',
    )
    original_text = models.TextField(
        verbose_name='원문 텍스트',
        help_text='고객이 입력한 원본 메시지.',
    )
    normalized_text = models.TextField(
        blank=True,
        verbose_name='정규화 텍스트',
        help_text='전처리·정규화된 텍스트. 미사용 시 빈 값.',
    )
    predicted_intent = models.CharField(
        max_length=60,
        choices=PredictedIntent.choices,
        db_index=True,
        verbose_name='분류된 의도',
    )
    predicted_action = models.CharField(
        max_length=60,
        choices=PredictedAction.choices,
        db_index=True,
        verbose_name='제안 액션',
    )
    execution_mode = models.CharField(
        max_length=40,
        choices=PredictedExecutionMode.choices,
        verbose_name='실행 모드',
    )
    confidence = models.FloatField(
        default=0.0,
        verbose_name='신뢰도',
        help_text='0.0~1.0. LLM 또는 분류기 출력 confidence.',
    )
    source = models.CharField(
        max_length=30,
        choices=AnalysisSource.choices,
        db_index=True,
        verbose_name='분류 소스',
    )
    raw_model_output = models.JSONField(
        null=True,
        blank=True,
        verbose_name='모델 원본 출력',
        help_text='LLM/분류기의 원시 JSON 응답. 디버그·감사용.',
    )
    target_section_ids = models.JSONField(
        null=True,
        blank=True,
        verbose_name='대상 설문 섹션',
        help_text='LLM이 분석한 수정 대상 설문 섹션 ID 배열.',
    )
    request_id = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='요청 세션 ID',
        help_text='한 번의 수정 요청 흐름을 묶는 UUID. feedback 이벤트·타임라인 조회용.',
    )
    route_candidates = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='경로 추천 후보',
        help_text='top-k 후보(merged_candidates), selected_primary_page, recommendation_confidence. 학습·ranking용.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '고객 요청 분류'
        verbose_name_plural = '고객 요청 분류'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['conversation', '-created_at']),
        ]

    def __str__(self):
        return (
            f'분류 #{self.id} '
            f'{self.get_predicted_intent_display()} '
            f'({self.get_source_display()}, {self.confidence:.0%})'
        )


class CustomerActionProposal(models.Model):
    """
    고객에게 보여준 액션 제안 1건.

    IntentAnalysis 결과를 기반으로 생성. 고객이 확인/거절/만료 시 상태 전이.
    실제 action 실행은 status=CONFIRMED → EXECUTED 전이 시에만 수행.

    사용처:
    - customer_request_service._create_action_proposal() 에서 생성
    - customer_request_service.confirm_proposal() / decline_proposal() 에서 상태 전이 + 실행
    - customer_request_service.build_customer_ui_payload() 에서 프론트엔드 payload 빌드
    - templates/messaging/inbox.html 의 renderActionCards() 에서 확인/거절 버튼 렌더링
    """

    class Status(models.TextChoices):
        PROPOSED = 'PROPOSED', '제안됨'
        CONFIRMED = 'CONFIRMED', '고객 승인'
        DECLINED = 'DECLINED', '고객 거절'
        EXPIRED = 'EXPIRED', '만료'
        EXECUTED = 'EXECUTED', '실행 완료'
        FAILED = 'FAILED', '실행 실패'

    class ProposalType(models.TextChoices):
        SURVEY_REOPEN = 'SURVEY_REOPEN', '설문 재수정'
        SURVEY_RESUME = 'SURVEY_RESUME', '설문 이어쓰기'
        QUOTE_RESEND = 'QUOTE_RESEND', '견적 재발송'
        QUOTE_REVISION = 'QUOTE_REVISION', '견적 수정 요청'
        PAYMENT_LINK_RESEND = 'PAYMENT_LINK_RESEND', '결제 링크 재발송'
        HUMAN_REVIEW = 'HUMAN_REVIEW', '사람 검토 요청'
        INFO_REPLY = 'INFO_REPLY', '정보 안내'

    analysis = models.ForeignKey(
        CustomerRequestIntentAnalysis,
        on_delete=models.CASCADE,
        related_name='proposals',
        verbose_name='분류 결과',
    )
    proposal_type = models.CharField(
        max_length=30,
        choices=ProposalType.choices,
        db_index=True,
        verbose_name='제안 유형',
    )
    title = models.CharField(max_length=200, blank=True, verbose_name='제목')
    body = models.TextField(blank=True, verbose_name='본문')
    action_code = models.CharField(
        max_length=80,
        db_index=True,
        verbose_name='액션 코드',
        help_text='실행할 액션 식별자. 예: reopen_survey, resume_survey, resend_quote',
    )
    action_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='액션 파라미터',
        help_text='실행 시 필요한 추가 데이터 (submission_id, quote_id 등).',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROPOSED,
        db_index=True,
        verbose_name='상태',
    )
    submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_proposals',
        verbose_name='설문 제출',
    )
    quote = models.ForeignKey(
        'settlement.SettlementQuote',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_proposals',
        verbose_name='견적',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='action_proposals',
        verbose_name='대화',
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='만료 시각')
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='승인 시각')
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_proposals',
        verbose_name='승인자',
    )
    declined_at = models.DateTimeField(null=True, blank=True, verbose_name='거절 시각')
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name='실행 시각')
    failure_reason = models.TextField(blank=True, verbose_name='실패 사유')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '고객 액션 제안'
        verbose_name_plural = '고객 액션 제안'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['conversation', 'status']),
        ]

    def __str__(self):
        return (
            f'제안 #{self.id} '
            f'{self.get_proposal_type_display()} '
            f'({self.get_status_display()})'
        )


class CustomerActionFeedbackLog(models.Model):
    """
    제안에 대한 이벤트 로그 (불변, append-only).

    제안 노출·승인·거절·실행 시작·성공·실패·고객 정정·후속 성공 등
    모든 사용자 상호작용과 시스템 이벤트를 시간순으로 기록.
    event_payload에 structured learning signal 포함 (향후 ML 학습 export용).

    사용처:
    - customer_request_service._log_feedback() 으로 append-only 기록
    - confirm_proposal() / decline_proposal() 에서 learning signal payload 포함
    - detect_and_record_correction() 에서 USER_CORRECTED 기록
    - record_followup_success() 에서 FOLLOWUP_SUCCESS 기록
    - settlement/views.py api_proposal_mark_shown() 에서 PROPOSAL_VIEWED 기록
    """

    class EventType(models.TextChoices):
        PROPOSAL_SHOWN = 'PROPOSAL_SHOWN', '제안 노출'
        USER_CONFIRMED = 'USER_CONFIRMED', '고객 승인'
        USER_DECLINED = 'USER_DECLINED', '고객 거절'
        ACTION_STARTED = 'ACTION_STARTED', '액션 실행 시작'
        ACTION_SUCCEEDED = 'ACTION_SUCCEEDED', '액션 실행 성공'
        ACTION_FAILED = 'ACTION_FAILED', '액션 실행 실패'
        USER_CORRECTED = 'USER_CORRECTED', '고객 정정 요청'
        FOLLOWUP_SUCCESS = 'FOLLOWUP_SUCCESS', '후속 행동 완료'
        PROPOSAL_EXPIRED = 'PROPOSAL_EXPIRED', '제안 만료'
        ADMIN_OVERRIDE = 'ADMIN_OVERRIDE', 'Admin 수동 처리'

    proposal = models.ForeignKey(
        CustomerActionProposal,
        on_delete=models.CASCADE,
        related_name='feedback_logs',
        verbose_name='제안',
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        db_index=True,
        verbose_name='이벤트 유형',
    )
    event_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='이벤트 데이터',
        help_text='이벤트별 상세 데이터. 실패 시 error, 정정 시 원문 등.',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_feedback_logs',
        verbose_name='행위자',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '액션 피드백 로그'
        verbose_name_plural = '액션 피드백 로그'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['proposal', 'created_at']),
        ]

    def __str__(self):
        return (
            f'로그 #{self.id} '
            f'제안#{self.proposal_id} '
            f'{self.get_event_type_display()}'
        )


# ---------------------------------------------------------------------------
# 설문 수정 흐름 학습용 이벤트 로그 (추천 페이지 vs 실제 수정 페이지 추적)
# ---------------------------------------------------------------------------


class CustomerRequestFeedbackEvent(models.Model):
    """
    수정 요청 흐름에서 발생하는 이벤트를 학습용 feedback으로 기록.

    - message_received: 사용자 수정 요청 메시지 수신
    - route_predicted: 휴리스틱/LLM 추천 페이지 예측
    - suggestion_clicked: 사용자가 추천 항목(설문 수정하기 등) 클릭
    - page_viewed: 설문 특정 페이지(step/section) 조회
    - edit_saved: 특정 페이지에서 수정 저장 발생
    - feedback_clicked: 사용자 피드백 (corrected_here / used_other_page / could_not_find)

    request_id로 동일 요청 흐름의 이벤트를 묶어서 분석·학습에 사용.
    """

    class EventType(models.TextChoices):
        MESSAGE_RECEIVED = 'message_received', '메시지 수신'
        ROUTE_PREDICTED = 'route_predicted', '경로 예측'
        SUGGESTION_CLICKED = 'suggestion_clicked', '추천 클릭'
        PAGE_VIEWED = 'page_viewed', '페이지 조회'
        EDIT_SAVED = 'edit_saved', '수정 저장'
        FEEDBACK_CLICKED = 'feedback_clicked', '피드백 클릭'

    # feedback_clicked 시 선택 값 (metadata에도 저장 가능)
    class FeedbackValue(models.TextChoices):
        CORRECTED_HERE = 'corrected_here', '여기서 수정함'
        USED_OTHER_PAGE = 'used_other_page', '다른 페이지에서 수정함'
        COULD_NOT_FIND = 'could_not_find', '찾지 못함'
        THUMBS_UP = 'thumbs_up', '도움됨'
        THUMBS_DOWN = 'thumbs_down', '도움 안 됨'

    request_id = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name='요청 흐름 ID',
        help_text='동일 수정 요청 흐름을 묶는 식별자 (UUID 또는 analysis_id 등).',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='request_feedback_events',
        verbose_name='사용자',
    )
    survey_submission = models.ForeignKey(
        'survey.SurveySubmission',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='feedback_events',
        verbose_name='설문 제출',
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        db_index=True,
        verbose_name='이벤트 유형',
    )
    page_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name='페이지 키',
        help_text='step 번호, section id, 또는 페이지 식별자.',
    )
    message_text = models.TextField(
        blank=True,
        null=True,
        verbose_name='메시지 텍스트',
        help_text='message_received 시 원문, 기타 이벤트 시 보조 텍스트.',
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='메타데이터',
        help_text='이벤트별 상세 데이터. route_predicted: heuristic_page, llm_page, top_candidates, final_recommended_pages / edit_saved: changed_fields, save_result, entity_type, entity_id / feedback_clicked: value 등.',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='발생 시각')

    class Meta:
        verbose_name = '요청 피드백 이벤트'
        verbose_name_plural = '요청 피드백 이벤트'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_id', 'event_type']),
            models.Index(fields=['request_id', '-created_at']),
            models.Index(fields=['survey_submission', '-created_at']),
        ]

    def __str__(self):
        return f'{self.request_id} / {self.get_event_type_display()} @ {self.created_at}'


# ---------------------------------------------------------------------------
# 학습용 label 요약 (request_id 단위 materialized summary)
# ---------------------------------------------------------------------------


class CustomerRequestLearningSummary(models.Model):
    """
    request_id 단위로 이벤트를 집계한 학습용 summary.
    supervised learning training example 생성용. admin/debug 조회용.
    """
    request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name='요청 흐름 ID',
    )
    summary = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='학습 요약',
        help_text='user_message, predicted_primary_page, actual_edit_page, label_quality, positive_labels, negative_labels 등.',
    )
    label_quality = models.CharField(
        max_length=16,
        db_index=True,
        blank=True,
        verbose_name='라벨 품질',
        help_text='strong | medium | weak',
    )
    manual_confirmed_intent = models.CharField(
        max_length=60,
        blank=True,
        db_index=True,
        verbose_name='관리자 확정 의도',
        help_text='관리자가 수동으로 확정한 intent. 비어 있으면 자동 라벨 사용.',
    )
    manual_confirmed_page_key = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        verbose_name='관리자 확정 페이지 키',
        help_text='관리자가 수동으로 확정한 정답 페이지 키. 비어 있으면 자동 라벨 사용.',
    )
    manual_label_notes = models.TextField(
        blank=True,
        verbose_name='수동 라벨 메모',
        help_text='수동 확정 사유/메모.',
    )
    manual_labeled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_labeled_learning_summaries',
        verbose_name='수동 라벨 담당자',
    )
    manual_labeled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='수동 라벨 시각',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '요청 학습 요약'
        verbose_name_plural = '요청 학습 요약'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['label_quality']),
        ]

    def __str__(self):
        return f'{self.request_id} ({self.label_quality})'

    @property
    def label_source(self) -> str:
        if (self.manual_confirmed_intent or "").strip() or (self.manual_confirmed_page_key or "").strip():
            return "manual"
        return "auto"

    def get_effective_intent(self) -> str:
        manual_intent = (self.manual_confirmed_intent or "").strip()
        if manual_intent:
            return manual_intent
        summary = self.summary if isinstance(self.summary, dict) else {}
        return (summary.get("predicted_intent") or "").strip()

    def get_effective_page_keys(self) -> List[str]:
        manual_page = (self.manual_confirmed_page_key or "").strip()
        if manual_page:
            return [manual_page]
        summary = self.summary if isinstance(self.summary, dict) else {}
        positives = summary.get("positive_labels")
        if isinstance(positives, list):
            return [str(v).strip() for v in positives if str(v).strip()]
        return []


class CustomerRequestManualLabelRevision(models.Model):
    """
    관리자 수동 라벨 변경 이력.
    before/after를 저장해 학습 데이터에서 수정 전/후 신호를 함께 사용할 수 있게 한다.
    """

    learning_summary = models.ForeignKey(
        CustomerRequestLearningSummary,
        on_delete=models.CASCADE,
        related_name='manual_label_revisions',
        verbose_name='학습 요약',
    )
    request_id = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name='요청 흐름 ID',
    )
    before_intent = models.CharField(
        max_length=60,
        blank=True,
        verbose_name='수정 전 확정 의도',
    )
    after_intent = models.CharField(
        max_length=60,
        blank=True,
        verbose_name='수정 후 확정 의도',
    )
    before_page_key = models.CharField(
        max_length=128,
        blank=True,
        verbose_name='수정 전 확정 페이지 키',
    )
    after_page_key = models.CharField(
        max_length=128,
        blank=True,
        verbose_name='수정 후 확정 페이지 키',
    )
    before_notes = models.TextField(
        blank=True,
        verbose_name='수정 전 메모',
    )
    after_notes = models.TextField(
        blank=True,
        verbose_name='수정 후 메모',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_label_revision_events',
        verbose_name='변경한 관리자',
    )
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name='변경 시각')

    class Meta:
        verbose_name = '수동 라벨 변경 이력'
        verbose_name_plural = '수동 라벨 변경 이력'
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['request_id', '-changed_at']),
            models.Index(fields=['learning_summary', '-changed_at']),
        ]

    def __str__(self):
        return f'{self.request_id} manual_label_revision @ {self.changed_at}'


# ---------------------------------------------------------------------------
# 페이지 키별 피드백 점수 (추천 경로 보정용 학습 결과)
# ---------------------------------------------------------------------------


class PageKeyFeedbackScore(models.Model):
    """
    page_key 단위로 집계된 피드백 점수.
    rebuild_feedback_scores() 가 CustomerRequestLearningSummary 전체를 집계해 upsert 한다.

    score_boost: [-1, 1] 범위. 양수=추천 정확도 높음, 음수=추천 부정확.
    classify_customer_request() 의 _merge_candidates() 에서 base score 에 가중치로 적용된다.
    """
    page_key = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        verbose_name='페이지 키',
    )
    thumbs_up_count = models.PositiveIntegerField(default=0, verbose_name='👍 수')
    thumbs_down_count = models.PositiveIntegerField(default=0, verbose_name='👎 수')
    positive_label_count = models.PositiveIntegerField(
        default=0, verbose_name='positive 라벨 수',
        help_text='edit_saved success 기반 strong/medium label',
    )
    negative_label_count = models.PositiveIntegerField(
        default=0, verbose_name='negative 라벨 수',
        help_text='used_other_page 기반 negative label',
    )
    total_seen = models.PositiveIntegerField(
        default=0, verbose_name='예측 총 회수',
        help_text='이 page_key 가 predicted_primary_page 로 선택된 총 회수',
    )
    score_boost = models.FloatField(
        default=0.0,
        verbose_name='점수 보정값',
        help_text='[-1, 1] 범위. 집계 데이터 부족 시 신뢰도 감쇠 적용.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '페이지 키 피드백 점수'
        verbose_name_plural = '페이지 키 피드백 점수'
        ordering = ['-score_boost']

    def __str__(self):
        return f'{self.page_key} (boost={self.score_boost:+.3f})'

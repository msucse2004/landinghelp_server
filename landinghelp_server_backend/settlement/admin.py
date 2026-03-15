from django.contrib import admin
from django.utils import timezone
from .models import (
    SettlementService,
    ServiceStatePrice,
    SettlementQuoteRequest,
    AgentAppointmentRequest,
    UserSettlementPlan,
    SettlementQuote,
    PlanServiceTask,
    ServiceSchedulePlan,
    ServiceScheduleItem,
    AgentAvailabilityWindow,
    AvailabilityRequest,
    AvailabilityResponse,
    AvailabilitySlot,
    QuoteChangeRequest,
    QuoteChangeRequestItem,
    QuoteChangeAnalysis,
    QuoteChangeActionLog,
    CustomerActionOffer,
    HumanReviewRequest,
    ServiceCompletionForm,
    CaseDocument,
    DocumentSignature,
)


def _extract_service_codes_from_quote_items(items):
    codes = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        code = str(it.get('code') or '').strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def _sync_submission_service_fields_from_quote(quote):
    submission = getattr(quote, 'submission', None)
    if not submission:
        return False

    quote_codes = _extract_service_codes_from_quote_items(getattr(quote, 'items', None) or [])

    current_required = list(getattr(submission, 'requested_required_services', None) or [])
    current_optional = list(getattr(submission, 'requested_optional_services', None) or [])
    answers = dict(getattr(submission, 'answers', None) or {})

    next_answers = dict(answers)
    next_answers['requested_required_services'] = quote_codes
    next_answers['requested_optional_services'] = []

    per_service = next_answers.get('service_delivery_per_service')
    if isinstance(per_service, dict):
        next_answers['service_delivery_per_service'] = {
            k: v for k, v in per_service.items() if k in set(quote_codes)
        }

    has_changes = (
        current_required != quote_codes
        or current_optional != []
        or answers != next_answers
    )
    if not has_changes:
        return False

    submission.requested_required_services = quote_codes
    submission.requested_optional_services = []
    submission.answers = next_answers
    submission.save(update_fields=['requested_required_services', 'requested_optional_services', 'answers', 'updated_at'])
    return True


class ServiceStatePriceInline(admin.TabularInline):
    model = ServiceStatePrice
    extra = 0
    fields = ('state_code', 'customer_price', 'agent_price')
    verbose_name = 'State별 가격'
    verbose_name_plural = 'State별 가격 (없으면 위 기본 가격 사용)'


@admin.register(SettlementService)
class SettlementServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'required_time', 'customer_price', 'agent_price', 'is_active')
    list_filter = ('category', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)
    ordering = ('category', 'name')
    inlines = (ServiceStatePriceInline,)
    fieldsets = (
        (None, {
            'fields': ('code', 'name', 'category', 'is_active'),
        }),
        ('시간/기본 가격 (State별 가격 없을 때 사용)', {
            'fields': ('required_time', 'customer_price', 'agent_price'),
        }),
    )


@admin.register(SettlementQuoteRequest)
class SettlementQuoteRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'state', 'city', 'entry_date', 'checkout_total', 'service_summary', 'ai_suggested', 'created_at')
    list_filter = ('ai_suggested', 'created_at')
    search_fields = ('name', 'email', 'state', 'city', 'memo')
    readonly_fields = ('created_at',)

    def service_summary(self, obj):
        from .constants import get_service_label
        labels = [get_service_label(c) for c in (obj.services or [])]
        return ', '.join(labels[:5]) + (' ...' if len(labels) > 5 else '')
    service_summary.short_description = '서비스'


class PlanServiceTaskInline(admin.TabularInline):
    model = PlanServiceTask
    extra = 0
    readonly_fields = ('service_code', 'label', 'display_order', 'appointment')
    raw_id_fields = ('appointment',)
    ordering = ('display_order',)
    verbose_name = '필요 작업(견적 기준)'


@admin.register(UserSettlementPlan)
class UserSettlementPlanAdmin(admin.ModelAdmin):
    list_display = ('user', 'assigned_agent', 'state', 'city', 'entry_date', 'checkout_total', 'updated_at')
    list_filter = ('assigned_agent',)
    raw_id_fields = ('assigned_agent',)
    search_fields = ('user__username', 'city')
    readonly_fields = ('updated_at',)
    inlines = (PlanServiceTaskInline,)


@admin.register(SettlementQuote)
class SettlementQuoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'submission_email', 'status', 'draft_source', 'total_display', 'version', 'auto_generated_at', 'sent_at', 'updated_at')
    list_display_links = ('id', 'submission_email')
    list_filter = ('status', 'draft_source', 'updated_at')
    search_fields = ('submission__email', 'submission__user__email', 'region')
    readonly_fields = ('created_at', 'updated_at', 'sent_at', 'auto_generated_at')
    list_editable = ('status',)
    raw_id_fields = ('submission',)
    actions = ('regenerate_draft',)
    fieldsets = (
        (None, {
            'fields': ('submission', 'status', 'version', 'draft_source', 'auto_generated_at'),
        }),
        ('견적 내용', {
            'fields': ('region', 'items', 'total'),
            'description': 'items: [{"code":"X","label":"서비스명","price":50000,"_auto":true,"_needs_review":false}, ...]',
        }),
        ('시각', {
            'fields': ('created_at', 'updated_at', 'sent_at'),
        }),
    )

    def submission_email(self, obj):
        return obj.submission.email if obj.submission_id else '-'
    submission_email.short_description = '고객 이메일'
    submission_email.admin_order_field = 'submission__email'

    def total_display(self, obj):
        if obj.total is not None:
            return f'{int(obj.total):,} 원'
        return '-'
    total_display.short_description = '합계'

    @admin.action(description='선택 견적 초안 재생성(제출 데이터 기준)')
    def regenerate_draft(self, request, queryset):
        from .quote_draft import generate_quote_draft_from_submission
        count = 0
        for quote in queryset.filter(status=SettlementQuote.Status.DRAFT):
            if not quote.submission_id:
                continue
            try:
                q, _ = generate_quote_draft_from_submission(quote.submission, actor=request.user)
                if q:
                    count += 1
            except Exception as e:
                self.message_user(request, f'견적 #{quote.id} 오류: {e}', level=40)
        self.message_user(request, f'{count}건 견적 초안을 재생성했습니다.')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        _sync_submission_service_fields_from_quote(obj)
        if obj.status in (SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID):
            from .quote_approval import finalize_and_send_quote
            finalize_and_send_quote(obj, actor=request.user)


@admin.register(AgentAppointmentRequest)
class AgentAppointmentRequestAdmin(admin.ModelAdmin):
    list_display = ('agent', 'service_code', 'service_date', 'customer', 'customer_name', 'status', 'cancellation_reason', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('agent__username', 'customer_name', 'customer_email', 'message', 'cancellation_reason')
    readonly_fields = ('created_at',)


@admin.register(PlanServiceTask)
class PlanServiceTaskAdmin(admin.ModelAdmin):
    list_display = ('plan', 'service_code', 'label', 'display_order', 'appointment', 'appointment_status')
    list_filter = ('plan__user',)
    raw_id_fields = ('plan', 'appointment')
    search_fields = ('service_code', 'label')
    ordering = ('plan', 'display_order')

    def appointment_status(self, obj):
        return obj.appointment.get_status_display() if obj.appointment_id else '—'
    appointment_status.short_description = '약속 상태'


# --- 스케줄 도메인: ML/Admin 일정 플랜·항목·Agent 가용창 ---


class ServiceScheduleItemInline(admin.TabularInline):
    model = ServiceScheduleItem
    extra = 0
    ordering = ('sort_order', 'starts_at')
    raw_id_fields = ('assigned_agent',)
    fields = (
        'service_code', 'service_label', 'service_type', 'starts_at', 'ends_at', 'duration_minutes',
        'assigned_agent', 'location_text', 'status', 'sort_order', 'notes',
    )
    verbose_name = '일정 항목'
    verbose_name_plural = '일정 항목'


@admin.register(ServiceSchedulePlan)
class ServiceSchedulePlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'submission', 'quote', 'status', 'source', 'version', 'updated_at')
    list_display_links = ('id',)
    list_filter = ('status', 'source', 'updated_at')
    search_fields = ('customer__username', 'customer__email', 'submission__email')
    raw_id_fields = ('submission', 'quote', 'customer', 'created_by', 'updated_by')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (ServiceScheduleItemInline,)
    ordering = ('-updated_at',)


@admin.register(ServiceScheduleItem)
class ServiceScheduleItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'schedule_plan', 'service_code', 'service_label', 'starts_at', 'status', 'assigned_agent', 'sort_order')
    list_display_links = ('id',)
    list_filter = ('status', 'service_type', 'schedule_plan')
    search_fields = ('service_code', 'service_label')
    raw_id_fields = ('schedule_plan', 'assigned_agent')
    ordering = ('schedule_plan', 'sort_order', 'starts_at')


@admin.register(AgentAvailabilityWindow)
class AgentAvailabilityWindowAdmin(admin.ModelAdmin):
    list_display = ('id', 'agent', 'starts_at', 'ends_at', 'source', 'status', 'submission', 'schedule_plan', 'created_at')
    list_display_links = ('id',)
    list_filter = ('source', 'status', 'created_at')
    search_fields = ('agent__username',)
    raw_id_fields = ('agent', 'submission', 'schedule_plan')
    readonly_fields = ('created_at',)
    ordering = ('agent', 'starts_at')


class AvailabilitySlotInline(admin.TabularInline):
    model = AvailabilitySlot
    extra = 0
    fields = ('weekday', 'start_time', 'end_time', 'timezone_name', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('weekday', 'start_time', 'id')


@admin.register(AvailabilityRequest)
class AvailabilityRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'submission', 'target_user', 'participant_role', 'timezone_name',
        'status', 'schedule_plan', 'requested_by', 'created_at',
    )
    list_display_links = ('id',)
    list_filter = ('participant_role', 'status', 'timezone_name', 'created_at')
    search_fields = ('submission__email', 'target_user__username', 'target_user__email')
    raw_id_fields = ('submission', 'schedule_plan', 'target_user', 'requested_by')
    readonly_fields = ('created_at', 'updated_at', 'closed_at')
    ordering = ('-created_at',)


@admin.register(AvailabilityResponse)
class AvailabilityResponseAdmin(admin.ModelAdmin):
    list_display = ('id', 'request', 'responded_by', 'timezone_name', 'revision', 'submitted_at')
    list_display_links = ('id',)
    list_filter = ('timezone_name', 'submitted_at')
    search_fields = ('request__submission__email', 'responded_by__username', 'responded_by__email')
    raw_id_fields = ('request', 'responded_by')
    readonly_fields = ('submitted_at',)
    ordering = ('-submitted_at',)
    inlines = (AvailabilitySlotInline,)


# --- 견적 변경 요청: LLM 해석 + 실행 로그 ---


class QuoteChangeRequestItemInline(admin.TabularInline):
    model = QuoteChangeRequestItem
    extra = 0
    ordering = ('display_order', 'id')
    fields = ('action_type', 'service_code', 'service_label', 'payload', 'display_order')
    verbose_name = '요청 항목'
    verbose_name_plural = '요청 항목'


class QuoteChangeAnalysisInline(admin.TabularInline):
    model = QuoteChangeAnalysis
    extra = 0
    max_num = 10
    readonly_fields = (
        'model_name', 'raw_customer_message', 'normalized_summary', 'detected_intent',
        'confidence', 'extracted_actions', 'extracted_service_codes', 'requires_admin_confirmation',
        'recommended_next_step', 'raw_llm_output', 'created_at',
    )
    ordering = ('-created_at',)
    verbose_name = 'LLM 분석'
    verbose_name_plural = 'LLM 분석'
    can_delete = True
    show_change_link = True


class QuoteChangeActionLogInline(admin.TabularInline):
    model = QuoteChangeActionLog
    extra = 0
    max_num = 20
    readonly_fields = ('actor', 'action_type', 'detail', 'created_at')
    ordering = ('-created_at',)
    verbose_name = '액션 로그'
    verbose_name_plural = '액션 로그'
    can_delete = False
    show_change_link = True


@admin.register(QuoteChangeRequest)
class QuoteChangeRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'quote', 'submission', 'requested_by', 'source_type', 'status',
        'created_at', 'reviewed_at', 'resolved_at',
    )
    list_display_links = ('id', 'quote')
    list_filter = ('source_type', 'status', 'created_at')
    search_fields = ('customer_message', 'admin_note', 'quote__submission__email', 'requested_by__username')
    raw_id_fields = ('submission', 'quote', 'requested_by')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at', 'resolved_at')
    inlines = (QuoteChangeRequestItemInline, QuoteChangeAnalysisInline, QuoteChangeActionLogInline)
    fieldsets = (
        (None, {
            'fields': ('submission', 'quote', 'requested_by', 'source_type', 'status'),
        }),
        ('메시지', {
            'fields': ('customer_message', 'admin_note'),
        }),
        ('시각', {
            'fields': ('created_at', 'updated_at', 'reviewed_at', 'resolved_at'),
        }),
    )
    ordering = ('-created_at',)


@admin.register(QuoteChangeAnalysis)
class QuoteChangeAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'change_request', 'detected_intent', 'confidence', 'requires_admin_confirmation', 'created_at')
    list_display_links = ('id',)
    list_filter = ('detected_intent', 'requires_admin_confirmation', 'created_at')
    search_fields = ('raw_customer_message', 'normalized_summary', 'recommended_next_step')
    raw_id_fields = ('change_request',)
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(QuoteChangeActionLog)
class QuoteChangeActionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'change_request', 'actor', 'action_type', 'created_at')
    list_display_links = ('id',)
    list_filter = ('action_type', 'created_at')
    raw_id_fields = ('change_request', 'actor')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(CustomerActionOffer)
class CustomerActionOfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'button_action_key', 'status', 'submission', 'quote', 'change_request', 'can_execute', 'executed_at', 'created_at')
    list_display_links = ('id',)
    list_filter = ('status', 'button_action_key', 'created_at')
    raw_id_fields = ('submission', 'quote', 'change_request', 'conversation', 'trigger_message', 'executed_by')
    readonly_fields = ('created_at', 'updated_at', 'executed_at')
    ordering = ('-created_at',)


@admin.register(HumanReviewRequest)
class HumanReviewRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'review_target', 'status', 'detected_intent', 'requested_by',
        'submission', 'quote', 'change_request', 'assigned_to', 'created_at',
    )
    list_display_links = ('id',)
    list_filter = ('review_target', 'status', 'created_at')
    search_fields = ('original_message', 'detected_intent', 'requested_by__username', 'requested_by__email')
    raw_id_fields = ('conversation', 'trigger_message', 'submission', 'quote', 'change_request', 'requested_by', 'assigned_to', 'appointment')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    fieldsets = (
        (None, {
            'fields': ('conversation', 'trigger_message', 'submission', 'quote', 'change_request', 'requested_by', 'review_target', 'status', 'assigned_to', 'appointment'),
        }),
        ('정책/분석', {
            'fields': ('original_message', 'detected_intent', 'recommended_action', 'execution_mode', 'confidence', 'suggested_internal_next_step', 'suggested_customer_reply'),
        }),
        ('처리', {
            'fields': ('completed_at', 'completed_note'),
        }),
        ('시각', {
            'fields': ('created_at', 'updated_at'),
        }),
    )
    ordering = ('-created_at',)


@admin.register(ServiceCompletionForm)
class ServiceCompletionFormAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'submission',
        'agent',
        'schedule_plan',
        'status',
        'attachments_count',
        'submitted_at',
        'reviewed_at',
        'reviewed_by',
    )
    list_display_links = ('id',)
    list_filter = ('status', 'submitted_at', 'reviewed_at')
    search_fields = ('submission__email', 'agent__username', 'agent__email', 'summary')
    raw_id_fields = ('submission', 'agent', 'schedule_plan', 'reviewed_by')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-submitted_at', '-id')


@admin.register(CaseDocument)
class CaseDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'submission', 'document_type', 'visibility_level', 'status',
        'owner_user', 'uploaded_by', 'version', 'is_signed_final', 'created_at',
    )
    list_display_links = ('id',)
    list_filter = ('document_type', 'visibility_level', 'status', 'is_signed_final', 'created_at')
    search_fields = ('original_filename', 'submission__email', 'owner_user__username', 'uploaded_by__username')
    raw_id_fields = ('submission', 'conversation', 'uploaded_by', 'owner_user', 'replaces')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(DocumentSignature)
class DocumentSignatureAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'document',
        'signer',
        'signer_role',
        'signature_type',
        'signed_at',
        'created_at',
    )
    list_display_links = ('id',)
    list_filter = ('signer_role', 'signature_type', 'signed_at')
    search_fields = ('document__original_filename', 'signer__username', 'signer__email')
    raw_id_fields = ('document', 'signer')
    readonly_fields = ('created_at',)
    ordering = ('-signed_at', '-id')

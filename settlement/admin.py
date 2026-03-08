from django.contrib import admin
from django.utils import timezone
from .models import SettlementService, ServiceStatePrice, SettlementQuoteRequest, AgentAppointmentRequest, UserSettlementPlan, SettlementQuote, PlanServiceTask


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

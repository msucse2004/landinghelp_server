from django.contrib import admin
from .models import SettlementService, SettlementQuoteRequest, AgentAppointmentRequest, UserSettlementPlan


@admin.register(SettlementService)
class SettlementServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'required_time', 'customer_price', 'agent_price', 'is_active')
    list_filter = ('category', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)
    ordering = ('category', 'name')
    fieldsets = (
        (None, {
            'fields': ('name', 'category', 'is_active'),
        }),
        ('시간/가격', {
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


@admin.register(UserSettlementPlan)
class UserSettlementPlanAdmin(admin.ModelAdmin):
    list_display = ('user', 'state', 'city', 'entry_date', 'checkout_total', 'updated_at')
    search_fields = ('user__username', 'city')
    readonly_fields = ('updated_at',)


@admin.register(AgentAppointmentRequest)
class AgentAppointmentRequestAdmin(admin.ModelAdmin):
    list_display = ('agent', 'service_code', 'service_date', 'customer', 'customer_name', 'status', 'cancellation_reason', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('agent__username', 'customer_name', 'customer_email', 'message', 'cancellation_reason')
    readonly_fields = ('created_at',)

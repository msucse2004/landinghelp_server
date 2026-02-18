from django.contrib import admin
from django.utils.html import format_html
from .models import Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('code', 'target_role', 'tier', 'is_active', 'features_preview')
    list_filter = ('target_role', 'tier', 'is_active')
    search_fields = ('code',)
    ordering = ('target_role', 'tier')

    def features_preview(self, obj):
        if not obj.features:
            return '-'
        items = list(obj.features.items())[:3] if isinstance(obj.features, dict) else str(obj.features)[:50]
        return str(items)[:80] + '...' if len(str(items)) > 80 else str(items)

    features_preview.short_description = 'features'


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_end', 'started_at')
    list_filter = ('status', 'plan')
    search_fields = ('user__username', 'user__email')
    raw_id_fields = ('user',)
    readonly_fields = ('started_at',)
    ordering = ('-started_at',)

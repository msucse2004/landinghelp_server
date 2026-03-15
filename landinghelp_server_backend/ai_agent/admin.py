from django.contrib import admin
from .models import AssistantKnowledge, AssistantInteractionLog


@admin.register(AssistantKnowledge)
class AssistantKnowledgeAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'service_code', 'is_active', 'display_order', 'updated_at')
    list_filter = ('category', 'is_active')
    search_fields = ('title', 'content', 'service_code')
    ordering = ('display_order', 'id')


@admin.register(AssistantInteractionLog)
class AssistantInteractionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'role', 'uncertainty_flagged', 'created_at')
    list_filter = ('role', 'uncertainty_flagged', 'created_at')
    search_fields = ('user__username', 'input_text', 'output_text')
    readonly_fields = ('user', 'conversation', 'message', 'role', 'input_text', 'output_text', 'model_used', 'uncertainty_flagged', 'meta', 'created_at')
    ordering = ('-created_at',)

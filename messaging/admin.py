from django.contrib import admin
from .models import (
    Conversation, ConversationParticipant, Message, MessageRead,
    CustomerRequestIntentAnalysis, CustomerActionProposal, CustomerActionFeedbackLog,
)


class ConversationParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    raw_id_fields = ('user',)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    raw_id_fields = ('sender',)
    readonly_fields = ('created_at',)


# 대화·메시지·메시지 읽음을 관리 메뉴에서 하나로 합침: '대화'만 등록하고,
# 참여자·메시지는 대화 상세 인라인에서만 관리. Message/MessageRead는 별도 메뉴 제거.
@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'subject', 'appointment', 'created_at', 'updated_at')
    list_filter = ('type',)
    search_fields = ('subject',)
    raw_id_fields = ('appointment',)
    inlines = (ConversationParticipantInline, MessageInline)
    readonly_fields = ('created_at', 'updated_at')


# 메뉴를 하나로 하기 위해 Message, MessageRead는 등록하지 않음 (대화 인라인으로만 편집)
# 필요 시 아래처럼 다시 등록하면 '메시지'/'메시지 읽음' 메뉴가 복구됨.
# @admin.register(Message)
# class MessageAdmin(admin.ModelAdmin): ...
# @admin.register(MessageRead)
# class MessageReadAdmin(admin.ModelAdmin): ...


# ---------------------------------------------------------------------------
# 고객 요청 분류·제안·피드백 Admin
# ---------------------------------------------------------------------------

class CustomerActionProposalInline(admin.TabularInline):
    model = CustomerActionProposal
    extra = 0
    fields = (
        'proposal_type', 'action_code', 'status',
        'created_at', 'confirmed_at', 'executed_at',
    )
    readonly_fields = ('created_at', 'confirmed_at', 'executed_at')
    show_change_link = True


class CustomerActionFeedbackLogInline(admin.TabularInline):
    model = CustomerActionFeedbackLog
    extra = 0
    fields = ('event_type', 'actor', 'event_payload', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(CustomerRequestIntentAnalysis)
class CustomerRequestIntentAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'customer', 'predicted_intent', 'predicted_action',
        'execution_mode', 'source', 'confidence', 'created_at',
    )
    list_filter = ('predicted_intent', 'execution_mode', 'source')
    search_fields = ('original_text', 'customer__username', 'customer__email')
    raw_id_fields = ('customer', 'conversation', 'message')
    readonly_fields = ('created_at',)
    inlines = (CustomerActionProposalInline,)


@admin.register(CustomerActionProposal)
class CustomerActionProposalAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'proposal_type', 'action_code', 'status',
        'created_at', 'confirmed_at', 'executed_at',
    )
    list_filter = ('proposal_type', 'status')
    search_fields = ('title', 'action_code')
    raw_id_fields = ('analysis', 'submission', 'quote', 'conversation', 'confirmed_by')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (CustomerActionFeedbackLogInline,)


@admin.register(CustomerActionFeedbackLog)
class CustomerActionFeedbackLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'proposal', 'event_type', 'actor', 'created_at')
    list_filter = ('event_type',)
    raw_id_fields = ('proposal', 'actor')
    readonly_fields = ('created_at',)

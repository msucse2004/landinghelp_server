from django.contrib import admin
from .models import Conversation, ConversationParticipant, Message, MessageRead


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

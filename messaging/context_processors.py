# 메시지 미읽음 개수 (헤더 배지용) + 로그인 후 새 메시지 팝업 플래그
def messaging_unread(request):
    """템플릿에 messaging_unread_count, show_new_message_popup 제공. 로그인 사용자만."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'messaging_unread_count': 0, 'show_new_message_popup': False}
    from django.db.models import Exists, OuterRef
    from .models import ConversationParticipant, Message, MessageRead
    conv_ids = list(ConversationParticipant.objects.filter(user=request.user).values_list('conversation_id', flat=True))
    if not conv_ids:
        return {
            'messaging_unread_count': 0,
            'show_new_message_popup': bool(request.session.get('show_new_message_popup')),
        }
    # 본인이 보낸 메시지 제외, 본인이 읽은 메시지 제외 → 미읽음 개수
    read_by_me = MessageRead.objects.filter(message_id=OuterRef('pk'), user=request.user)
    count = Message.objects.filter(
        conversation_id__in=conv_ids
    ).exclude(sender=request.user).exclude(
        Exists(read_by_me)
    ).count()
    return {
        'messaging_unread_count': count,
        'show_new_message_popup': bool(request.session.get('show_new_message_popup')),
    }

# 메시지 미읽음 개수 (헤더 배지용) + 로그인/새 메시지 도착 시 팝업 플래그
def messaging_unread(request):
    """
    템플릿에 messaging_unread_count, show_new_message_popup 제공. 로그인 사용자만.
    메시지함 페이지에서는 팝업을 절대 표시하지 않음 (이미 메시지함을 보고 있으므로).
    """
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'messaging_unread_count': 0, 'show_new_message_popup': False}
    from django.db.models import Exists, OuterRef
    from .models import ConversationParticipant, Message, MessageRead
    conv_ids = list(ConversationParticipant.objects.filter(user=request.user).values_list('conversation_id', flat=True))
    if not conv_ids:
        return {
            'messaging_unread_count': 0,
            'show_new_message_popup': False,
        }
    read_by_me = MessageRead.objects.filter(message_id=OuterRef('pk'), user=request.user)
    count = Message.objects.filter(
        conversation_id__in=conv_ids
    ).exclude(sender=request.user).exclude(
        Exists(read_by_me)
    ).count()

    # 메시지함 페이지에서는 팝업 표시하지 않음
    if getattr(request, '_suppress_message_popup', False):
        request.session.pop('show_new_message_popup', None)
        return {
            'messaging_unread_count': count,
            'show_new_message_popup': False,
        }

    show_popup = bool(request.session.get('show_new_message_popup'))
    if count > 0 and not request.session.get('popup_dismissed'):
        request.session['show_new_message_popup'] = True
        show_popup = True
        request.session.modified = True
    return {
        'messaging_unread_count': count,
        'show_new_message_popup': show_popup,
    }

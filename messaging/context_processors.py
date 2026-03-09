# 메시지 미읽음 개수 (헤더 배지용) + 로그인/새 메시지 도착 시 팝업 플래그
def messaging_unread(request):
    """
    템플릿에 messaging_unread_count, show_new_message_popup 제공. 로그인 사용자만.
    미읽음이 있고 사용자가 팝업을 닫지 않았으면 show_new_message_popup=True 로 설정하여
    (이미 로그인한 상태에서 새 메시지가 와도) 팝업이 뜨도록 함.
    """
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
    show_popup = bool(request.session.get('show_new_message_popup'))
    # 미읽음이 있으면 팝업 표시(로그인 직후뿐 아니라 새 메시지 도착 후 페이지 접속 시에도)
    if count > 0 and not request.session.get('popup_dismissed'):
        request.session['show_new_message_popup'] = True
        show_popup = True
        request.session.modified = True
    return {
        'messaging_unread_count': count,
        'show_new_message_popup': show_popup,
    }

# messaging API: 대화 목록, 메시지 조회/전송, 읽음 처리, 공지 생성
import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone

from .models import Conversation, ConversationParticipant, Message, MessageRead


def _message_to_dict(msg, request, read_by_others=None):
    """메시지 객체를 API 응답용 dict로. image_url 포함."""
    d = {
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_username': msg.sender.username,
        'body': msg.body or '',
        'created_at': msg.created_at.isoformat(),
        'image_url': request.build_absolute_uri(msg.image.url) if msg.image else None,
    }
    if read_by_others is not None:
        d['read_by_others'] = read_by_others
    return d


def _user_conversations(user):
    """현재 사용자가 참여한 대화만."""
    return Conversation.objects.filter(
        participants__user=user
    ).distinct()


def _unread_count_for_user(conversation, user):
    """대화 내에서 user가 읽지 않은 메시지 수 (본인이 보낸 것 제외)."""
    return Message.objects.filter(
        conversation=conversation
    ).exclude(sender=user).exclude(
        read_by__user=user
    ).count()


@ensure_csrf_cookie
@login_required
def inbox(request):
    """메시지 함 페이지 (대화 목록 + 메시지 보기/답장)."""
    return render(request, 'messaging/inbox.html')


def _appointment_display_title(appointment):
    """약속 대화 제목: '약속 요청: {고객 이름}님 - {서비스}'"""
    if not appointment:
        return None
    from settlement.constants import get_service_label
    if appointment.customer_id:
        name = (appointment.customer.get_full_name() or '').strip() or appointment.customer.username or '고객'
    else:
        name = (appointment.customer_name or '').strip() or '고객'
    service_label = get_service_label(appointment.service_code or '')
    return f'약속 요청: {name}님 - {service_label}'


@require_GET
@ensure_csrf_cookie
@login_required
def api_conversation_list(request):
    """
    내 대화 목록. 각 대화별 미읽음 개수 포함.
    GET /api/messaging/conversations/
    """
    user = request.user
    qs = _user_conversations(user).select_related('appointment', 'appointment__customer').prefetch_related(
        'participants__user', 'messages'
    ).order_by('-updated_at')
    out = []
    for conv in qs:
        unread = Message.objects.filter(conversation=conv).exclude(sender=user).exclude(
            read_by__user=user
        ).count()
        last_msg = conv.messages.order_by('-created_at').first()
        if conv.type == Conversation.Type.NOTICE:
            display_title = conv.subject or '공지'
        elif conv.appointment_id:
            display_title = _appointment_display_title(conv.appointment) or f'약속 #{conv.appointment_id}'
        else:
            display_title = f'대화 #{conv.id}'
        item = {
            'id': conv.id,
            'type': conv.type,
            'subject': conv.subject or '',
            'appointment_id': conv.appointment_id,
            'display_title': display_title,
            'created_at': conv.created_at.isoformat(),
            'updated_at': conv.updated_at.isoformat(),
            'unread_count': unread,
            'last_message': None,
        }
        if last_msg:
            item['last_message'] = {
                'body': last_msg.body[:100] + ('...' if len(last_msg.body) > 100 else ''),
                'sender_username': last_msg.sender.username,
                'created_at': last_msg.created_at.isoformat(),
            }
        out.append(item)
    # 미읽음이 있는 대화를 맨 위로, 같은 그룹 내에서는 최신순(updated_at 내림차순)
    unread_first = [i for i in out if i['unread_count'] > 0]
    read_only = [i for i in out if i['unread_count'] == 0]
    unread_first.sort(key=lambda x: x['updated_at'], reverse=True)
    read_only.sort(key=lambda x: x['updated_at'], reverse=True)
    out = unread_first + read_only
    return JsonResponse({'conversations': out})


@ensure_csrf_cookie
@login_required
def api_conversation_messages(request, conversation_id):
    """
    GET: 대화 내 메시지 목록 (페이지네이션).
    POST: 메시지 전송. Body: { "body": "메시지 내용" }
    """
    user = request.user
    if not ConversationParticipant.objects.filter(conversation_id=conversation_id, user=user).exists():
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)
    conv = Conversation.objects.get(pk=conversation_id)

    if request.method == 'POST':
        body = ''
        image_file = None
        if request.content_type and 'multipart/form-data' in request.content_type:
            body = (request.POST.get('body') or '').strip()
            image_file = request.FILES.get('image')
            if image_file:
                allowed = getattr(image_file, 'content_type', '') or ''
                if not allowed.startswith('image/'):
                    return JsonResponse({'error': '이미지 파일만 첨부할 수 있습니다.'}, status=400)
        else:
            try:
                data = json.loads(request.body or '{}')
                body = (data.get('body') or '').strip()
            except (ValueError, TypeError):
                return JsonResponse({'error': 'body 필드가 필요합니다.'}, status=400)
        if not body and not image_file:
            return JsonResponse({'error': '메시지 내용을 입력하거나 사진을 첨부해 주세요.'}, status=400)
        if image_file and not body:
            body = '[사진]'
        msg = Message(conversation=conv, sender=user, body=body)
        if image_file:
            msg.image = image_file
        msg.save()
        MessageRead.objects.get_or_create(message=msg, user=user)
        conv.updated_at = timezone.now()
        conv.save(update_fields=['updated_at'])
        out = _message_to_dict(msg, request, read_by_others=False)
        return JsonResponse(out, status=201)

    page = int(request.GET.get('page', 1))
    page_size = min(int(request.GET.get('page_size', 50)), 100)
    start = (page - 1) * page_size
    msgs = conv.messages.select_related('sender').order_by('-created_at')[start:start + page_size + 1]
    has_more = len(msgs) > page_size
    if has_more:
        msgs = msgs[:page_size]
    msgs = list(reversed(msgs))
    read_ids = set(
        MessageRead.objects.filter(message__in=msgs, user=user).values_list('message_id', flat=True)
    )
    # 상대방이 내 메시지를 읽었는지 (카카오톡 스타일 읽음 표시용)
    other_user_ids = set(
        ConversationParticipant.objects.filter(conversation=conv)
        .exclude(user=user)
        .values_list('user_id', flat=True)
    )
    read_by_other = {}  # message_id -> True if all other participants have read
    my_msg_ids = [m.id for m in msgs if m.sender_id == user.id]
    if my_msg_ids and other_user_ids:
        from collections import defaultdict
        read_by_map = defaultdict(set)
        for mid, uid in MessageRead.objects.filter(
            message_id__in=my_msg_ids
        ).exclude(user=user).values_list('message_id', 'user_id'):
            read_by_map[mid].add(uid)
        for mid in my_msg_ids:
            read_by_other[mid] = other_user_ids <= read_by_map.get(mid, set())

    out = []
    for m in msgs:
        if m.sender_id == user.id:
            read_by_others = read_by_other.get(m.id, False) if other_user_ids else True
        else:
            read_by_others = True  # 상대 메시지는 읽음 표시 없음
        item = _message_to_dict(m, request, read_by_others=read_by_others)
        item['read'] = m.id in read_ids or m.sender_id == user.id
        out.append(item)
    return JsonResponse({
        'messages': out,
        'has_more': has_more,
        'page': page,
    })


@require_POST
@ensure_csrf_cookie
@login_required
def api_mark_read(request, conversation_id):
    """
    대화의 메시지들을 읽음 처리. (현재 사용자 기준)
    POST /api/messaging/conversations/<id>/read/
    Body (선택): { "up_to_message_id": 123 } — 해당 id 이하만 읽음. 없으면 전체.
    """
    user = request.user
    if not ConversationParticipant.objects.filter(conversation_id=conversation_id, user=user).exists():
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)
    conv = Conversation.objects.get(pk=conversation_id)
    try:
        data = json.loads(request.body or '{}')
        up_to = data.get('up_to_message_id')
    except (ValueError, TypeError):
        up_to = None
    qs = Message.objects.filter(conversation=conv).exclude(sender=user)
    if up_to is not None:
        qs = qs.filter(id__lte=up_to)
    created = 0
    for msg in qs:
        _, c = MessageRead.objects.get_or_create(message=msg, user=user)
        if c:
            created += 1
    return JsonResponse({'ok': True, 'marked_count': created})


@require_GET
@ensure_csrf_cookie
@login_required
def api_unread_count(request):
    """
    전체 미읽음 메시지 개수 (알림 배지용).
    GET /api/messaging/unread-count/
    """
    user = request.user
    conv_ids = ConversationParticipant.objects.filter(user=user).values_list('conversation_id', flat=True)
    count = Message.objects.filter(
        conversation_id__in=conv_ids
    ).exclude(sender=user).exclude(
        read_by__user=user
    ).count()
    return JsonResponse({'unread_count': count})


@require_POST
@ensure_csrf_cookie
@login_required
def api_dismiss_login_popup(request):
    """
    로그인 후 새 메시지 팝업을 닫았을 때 세션 플래그 제거.
    POST /api/messaging/dismiss-login-popup/
    """
    request.session.pop('show_new_message_popup', None)
    return JsonResponse({'ok': True})


@require_POST
@ensure_csrf_cookie
@login_required
def api_create_notice(request):
    """
    관리자 전용: 공지 대화 생성 + 참여자 추가 + 첫 메시지 전송.
    POST /api/messaging/notices/
    Body: {
      "subject": "공지 제목",
      "body": "공지 내용",
      "recipient_ids": [1, 2, 3]  // User PK (agent/customer)
    }
    """
    if not request.user.is_staff:
        return JsonResponse({'error': '관리자만 사용할 수 있습니다.'}, status=403)
    try:
        data = json.loads(request.body or '{}')
        subject = (data.get('subject') or '').strip()
        body = (data.get('body') or '').strip()
        recipient_ids = data.get('recipient_ids') or []
    except (ValueError, TypeError):
        return JsonResponse({'error': 'JSON 형식이 올바르지 않습니다.'}, status=400)
    if not subject:
        return JsonResponse({'error': '제목을 입력해 주세요.'}, status=400)
    if not body:
        return JsonResponse({'error': '내용을 입력해 주세요.'}, status=400)
    from accounts.models import User
    users = list(User.objects.filter(pk__in=recipient_ids).values_list('pk', flat=True))
    if not users:
        return JsonResponse({'error': '수신자를 한 명 이상 선택해 주세요.'}, status=400)
    conv = Conversation.objects.create(type=Conversation.Type.NOTICE, subject=subject)
    ConversationParticipant.objects.create(conversation=conv, user=request.user)
    for uid in users:
        ConversationParticipant.objects.get_or_create(conversation=conv, user_id=uid)
    msg = Message.objects.create(conversation=conv, sender=request.user, body=body)
    MessageRead.objects.get_or_create(message=msg, user=request.user)
    return JsonResponse({
        'conversation_id': conv.id,
        'message_id': msg.id,
        'recipient_count': len(users),
    }, status=201)


@require_GET
@ensure_csrf_cookie
@login_required
def api_conversation_detail(request, conversation_id):
    """
    대화 한 건 정보 (참여자, 약속 정보 등).
    GET /api/messaging/conversations/<id>/
    """
    user = request.user
    if not ConversationParticipant.objects.filter(conversation_id=conversation_id, user=user).exists():
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)
    conv = Conversation.objects.select_related('appointment').prefetch_related(
        'participants__user'
    ).get(pk=conversation_id)
    unread = Message.objects.filter(conversation=conv).exclude(sender=user).exclude(
        read_by__user=user
    ).count()
    participants = [
        {'id': p.user_id, 'username': p.user.username}
        for p in conv.participants.all()
    ]
    if conv.type == Conversation.Type.NOTICE:
        display_title = conv.subject or '공지'
    elif conv.appointment_id:
        display_title = _appointment_display_title(conv.appointment) or f'약속 #{conv.appointment_id}'
    else:
        display_title = f'대화 #{conv.id}'
    appointment = None
    if conv.appointment_id:
        a = conv.appointment
        # 에이전트가 로그인했고 약속이 PENDING일 때만 수락/수정요청 버튼 노출
        can_accept = (a.agent_id == user.id and a.status == 'PENDING')
        appointment = {
            'id': a.id,
            'service_code': a.service_code,
            'service_date': str(a.service_date),
            'status': a.status,
            'can_accept': can_accept,
        }
    return JsonResponse({
        'id': conv.id,
        'type': conv.type,
        'subject': conv.subject or '',
        'display_title': display_title,
        'appointment': appointment,
        'participants': participants,
        'unread_count': unread,
        'created_at': conv.created_at.isoformat(),
        'updated_at': conv.updated_at.isoformat(),
    })

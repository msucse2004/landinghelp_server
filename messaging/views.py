# messaging API: 대화 목록, 메시지 조회/전송, 읽음 처리, 공지 생성
import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone

from .models import Conversation, ConversationParticipant, Message, MessageRead, MessageTranslation


def _get_message_body_for_viewer(msg, viewer_user):
    """
    수신자(열람자) 기준으로 메시지 본문 반환.
    Returns: (body_preferred, body_en, preferred_lang)
    - 선호어가 영어면: 한 줄만 (body_preferred = body_en).
    - 그 외: 첫 줄 = 선호어, 둘째 줄 = 영어 (body_en).
    """
    pref = (getattr(viewer_user, 'preferred_language', None) or '').strip() or 'en'
    body = msg.body or ''
    body_en = getattr(msg, 'body_en', '') or ''
    detected = (getattr(msg, 'detected_lang', '') or '').strip()
    if not body_en and detected != 'en':
        body_en = body  # 영어 번역 없으면 원문 사용
    elif not body_en:
        body_en = body

    if pref == 'en':
        return (body_en or body, body_en or body, 'en')
    if detected and pref == detected:
        return (body, body_en or body, pref)

    # 선호어로 번역 캐시 조회 또는 번역 후 저장
    try:
        mt = MessageTranslation.objects.filter(message=msg, language_code=pref).first()
        if mt and (mt.body or '').strip():
            return (mt.body.strip(), body_en or body, pref)
    except Exception:
        pass
    source = detected or 'en'
    if source == 'en':
        source = 'en'
    from translations.services import _translate_one
    translated = _translate_one(body, pref, source)
    if translated:
        try:
            MessageTranslation.objects.update_or_create(
                message=msg,
                language_code=pref,
                defaults={'body': translated},
            )
        except Exception:
            pass
        return (translated, body_en or body, pref)
    return (body, body_en or body, pref)


def _detect_and_translate_to_en(body_text):
    """
    원문 언어 감지 후, 영어가 아니면 1순위 Google → 2순위 DeepL 로 영어 번역.
    Returns: (detected_lang, body_en). detected_lang은 항상 설정, body_en은 비영어일 때만.
    """
    if not body_text or not (body_text := (body_text or '').strip()):
        return ('', '')
    try:
        import langdetect
        detected = (langdetect.detect(body_text) or 'en').lower()
    except Exception:
        detected = 'en'
    if detected == 'en':
        return (detected, body_text)
    from translations.services import _translate_one
    from translations.utils import normalize_english_display
    body_en = _translate_one(body_text, 'en', detected)
    if body_en and body_en.strip():
        body_en = normalize_english_display(body_en.strip())
    return (detected, body_en or '')


def _message_to_dict(msg, request, read_by_others=None):
    """
    메시지 객체를 API 응답용 dict로.
    body_preferred: 열람자 선호어 본문 (첫 줄).
    body_en: 영어 본문 (선호어가 영어가 아니면 둘째 줄).
    viewer_preferred_language: 열람자 선호어 (영어면 한 줄만 표시).
    """
    body_pref, body_en, pref_lang = _get_message_body_for_viewer(msg, request.user)
    d = {
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_username': msg.sender.username,
        'body': msg.body or '',
        'body_preferred': body_pref,
        'body_en': body_en,
        'viewer_preferred_language': pref_lang,
        'detected_lang': getattr(msg, 'detected_lang', '') or '',
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
    """메시지 함 페이지 (대화 목록 + 메시지 보기/답장). 설정 언어로 UI 표시."""
    from translations.utils import get_display_text, get_request_language
    lang = get_request_language(request)
    i18n = {
        'page_title': get_display_text('메시지 함', lang),
        'page_desc': get_display_text('약속 요청·공지에 대한 대화를 확인하고 답장할 수 있습니다.', lang),
        'conversation_list': get_display_text('대화 목록', lang),
        'loading': get_display_text('불러오는 중...', lang),
        'select_conversation': get_display_text('왼쪽에서 대화를 선택하세요.', lang),
        'accept': get_display_text('수락', lang),
        'request_change': get_display_text('수정요청', lang),
        'attach_photo': get_display_text('사진 첨부', lang),
        'from_gallery': get_display_text('앨범에서 선택', lang),
        'from_camera': get_display_text('카메라로 촬영', lang),
        'message_placeholder': get_display_text('메시지를 입력하세요...', lang),
        'send': get_display_text('전송', lang),
        'no_conversations': get_display_text('대화가 없습니다.', lang),
        'load_failed': get_display_text('목록을 불러올 수 없습니다.', lang),
        'no_messages': get_display_text('아직 메시지가 없습니다.', lang),
        'messages_load_failed': get_display_text('메시지를 불러올 수 없습니다.', lang),
        'read': get_display_text('읽음', lang),
        'sent': get_display_text('전송됨', lang),
        'image_alt': get_display_text('첨부 이미지', lang),
        'accept_success': get_display_text('약속을 수락했습니다.', lang),
        'accept_failed': get_display_text('수락에 실패했습니다.', lang),
        'request_change_sent': get_display_text('일정 수정을 요청드립니다. 가능한 시간을 알려주세요.', lang),
        'send_failed': get_display_text('메시지 전송에 실패했습니다.', lang),
        'image_only': get_display_text('이미지 파일만 전송할 수 있습니다.', lang),
        'view_survey': get_display_text('고객 설문 확인', lang),
    }
    request.session.pop('show_new_message_popup', None)
    viewer_preferred = (getattr(request.user, 'preferred_language', None) or '').strip() or 'en'
    return render(request, 'messaging/inbox.html', {
        'inbox_i18n': i18n,
        'viewer_preferred_language': viewer_preferred,
    })


def _other_party_name(appointment, viewer_user):
    """약속에서 열람자 기준 '상대방' 이름. 고객이 보면 에이전트명, 에이전트가 보면 고객명."""
    if not appointment or not viewer_user:
        return None
    try:
        customer_id = getattr(appointment, 'customer_id', None) or (appointment.customer.id if appointment.customer else None)
        agent_id = getattr(appointment, 'agent_id', None) or (appointment.agent.id if appointment.agent else None)
    except Exception:
        customer_id = agent_id = None
    if viewer_user.id == customer_id and agent_id:
        other = getattr(appointment, 'agent', None)
        if other:
            return (getattr(other, 'get_full_name', lambda: '')() or '').strip() or getattr(other, 'username', '') or ''
    if viewer_user.id == agent_id:
        if getattr(appointment, 'customer_id', None):
            other = getattr(appointment, 'customer', None)
            if other:
                return (getattr(other, 'get_full_name', lambda: '')() or '').strip() or getattr(other, 'username', '') or '고객'
        return (getattr(appointment, 'customer_name', None) or '').strip() or '고객'
    return None


def _appointment_display_title(appointment, language_code='ko', viewer_user=None):
    """
    약속 대화 제목. viewer_user 기준:
    - 고객(c1)이 보면: 'a1님과의 약속 요청'
    - 에이전트(a1)가 보면: 'c1님과의 약속'
    - 그 외: 기존 형식 '약속 요청: 고객명님 - 서비스'
    """
    if not appointment:
        return None
    from settlement.constants import get_service_label
    from translations.utils import get_display_text
    pref = (language_code or '').strip() or 'en'
    other_name = _other_party_name(appointment, viewer_user) if viewer_user else None
    if other_name is not None:
        suffix_req = get_display_text('님과의 약속 요청', pref)
        suffix_only = get_display_text('님과의 약속', pref)
        is_customer_view = False
        try:
            cid = getattr(appointment, 'customer_id', None) or (appointment.customer.id if appointment.customer else None)
            is_customer_view = (viewer_user and cid and viewer_user.id == cid)
        except Exception:
            pass
        if is_customer_view:
            if pref == 'ko' or (suffix_req and '약속' in suffix_req):
                return (other_name + (suffix_req or '님과의 약속 요청')).strip()
            return ((suffix_req or 'Appointment request with ').strip() + ' ' + other_name).strip()
        else:
            if pref == 'ko' or (suffix_only and '약속' in suffix_only):
                return (other_name + (suffix_only or '님과의 약속')).strip()
            return ((suffix_only or 'Appointment with ').strip() + ' ' + other_name).strip()
    if appointment.customer_id:
        name = (appointment.customer.get_full_name() or '').strip() or appointment.customer.username or '고객'
    else:
        name = (appointment.customer_name or '').strip() or '고객'
    raw_service = get_service_label(appointment.service_code or '')
    service_label = get_display_text(raw_service, language_code) or raw_service
    part1 = get_display_text('약속 요청', language_code) or '약속 요청'
    suffix = get_display_text('님', language_code)
    if suffix and not suffix.isspace():
        name_part = name + suffix
    else:
        name_part = name
    return f'{part1}: {name_part} - {service_label}'


def _conversation_display_titles(conv, preferred_lang, viewer_user=None):
    """
    대화 제목을 선호어·영어로 반환. (display_title_preferred, display_title_en)
    viewer_user: 열람자. 약속 대화일 때 고객/에이전트에 따라 상대방 이름으로 제목 표시.
    """
    from translations.utils import get_display_text
    pref = (preferred_lang or '').strip() or 'en'
    if conv.type == Conversation.Type.NOTICE:
        raw = conv.subject or '공지'
        title_pref = get_display_text(raw, pref) or raw
        title_en = get_display_text(raw, 'en') or raw if pref != 'en' else title_pref
        return (title_pref, title_en)
    if conv.appointment_id:
        title_pref = _appointment_display_title(conv.appointment, pref, viewer_user) or f'약속 #{conv.appointment_id}'
        title_en = _appointment_display_title(conv.appointment, 'en', viewer_user) or f'약속 #{conv.appointment_id}' if pref != 'en' else title_pref
        return (title_pref, title_en)
    raw = '대화'
    title_pref = (get_display_text(raw, pref) or raw) + f' #{conv.id}'
    title_en = (get_display_text(raw, 'en') or raw) + f' #{conv.id}' if pref != 'en' else title_pref
    return (title_pref, title_en)


@require_GET
@ensure_csrf_cookie
@login_required
def api_conversation_list(request):
    """
    내 대화 목록. 각 대화별 미읽음 개수 포함.
    GET /api/messaging/conversations/
    """
    user = request.user
    viewer_preferred_language = (getattr(user, 'preferred_language', None) or '').strip() or 'en'
    qs = _user_conversations(user).select_related(
        'appointment', 'appointment__customer', 'appointment__agent', 'survey_submission'
    ).prefetch_related(
        'participants__user', 'messages'
    ).order_by('-updated_at')
    out = []
    for conv in qs:
        unread = _unread_count_for_user(conv, user)
        last_msg = conv.messages.order_by('-created_at').first()
        title_pref, title_en = _conversation_display_titles(conv, viewer_preferred_language, user)
        item = {
            'id': conv.id,
            'type': conv.type,
            'subject': conv.subject or '',
            'appointment_id': conv.appointment_id,
            'submission_id': getattr(conv, 'survey_submission_id', None),
            'display_title': title_pref,
            'display_title_preferred': title_pref,
            'display_title_en': title_en,
            'created_at': conv.created_at.isoformat(),
            'updated_at': conv.updated_at.isoformat(),
            'unread_count': unread,
            'last_message': None,
        }
        if last_msg:
            body_pref, body_en, pref_lang = _get_message_body_for_viewer(last_msg, user)
            item['last_message'] = {
                'body': last_msg.body[:100] + ('...' if len(last_msg.body) > 100 else ''),
                'body_preferred': (body_pref or '')[:100] + ('...' if len(body_pref or '') > 100 else ''),
                'body_en': (body_en or '')[:100] + ('...' if len(body_en or '') > 100 else ''),
                'viewer_preferred_language': pref_lang,
                'detected_lang': getattr(last_msg, 'detected_lang', '') or '',
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
    return JsonResponse({
        'conversations': out,
        'viewer_preferred_language': viewer_preferred_language,
    })


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
        # 다국어: 입력 언어 감지 후 영어가 아니면 body_en에 번역 저장
        if body:
            try:
                msg.detected_lang, msg.body_en = _detect_and_translate_to_en(body)
            except Exception:
                pass
        msg.save()
        MessageRead.objects.get_or_create(message=msg, user=user)
        conv.updated_at = timezone.now()
        conv.save(update_fields=['updated_at'])
        # 수신자 선호어로 번역 캐시 미리 생성 (열람 시 바로 표시)
        other_participants = list(
            ConversationParticipant.objects.filter(conversation=conv)
            .exclude(user=user)
            .select_related('user')
        )
        for cp in other_participants:
            try:
                _get_message_body_for_viewer(msg, cp.user)
            except Exception:
                pass
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
    viewer_preferred_language = (getattr(user, 'preferred_language', None) or '').strip() or 'en'
    return JsonResponse({
        'messages': out,
        'has_more': has_more,
        'page': page,
        'viewer_preferred_language': viewer_preferred_language,
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
    Staff일 때 설문 제출 연결된 공지면 submission_id, survey_review_url 포함.
    """
    from django.urls import reverse
    user = request.user
    if not ConversationParticipant.objects.filter(conversation_id=conversation_id, user=user).exists():
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)
    conv = Conversation.objects.select_related(
        'appointment', 'appointment__customer', 'appointment__agent', 'survey_submission'
    ).prefetch_related(
        'participants__user'
    ).get(pk=conversation_id)
    unread = Message.objects.filter(conversation=conv).exclude(sender=user).exclude(
        read_by__user=user
    ).count()
    participants = [
        {'id': p.user_id, 'username': p.user.username}
        for p in conv.participants.all()
    ]
    viewer_preferred_language = (getattr(user, 'preferred_language', None) or '').strip() or 'en'
    display_title_preferred, display_title_en = _conversation_display_titles(conv, viewer_preferred_language, user)
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
    payload = {
        'id': conv.id,
        'type': conv.type,
        'subject': conv.subject or '',
        'display_title': display_title_preferred,
        'display_title_preferred': display_title_preferred,
        'display_title_en': display_title_en,
        'viewer_preferred_language': viewer_preferred_language,
        'appointment': appointment,
        'participants': participants,
        'unread_count': unread,
        'created_at': conv.created_at.isoformat(),
        'updated_at': conv.updated_at.isoformat(),
    }
    if getattr(user, 'is_staff', False) and getattr(conv, 'survey_submission_id', None):
        payload['submission_id'] = conv.survey_submission_id
        try:
            payload['survey_review_url'] = reverse('app_submission_review', args=[conv.survey_submission_id])
        except Exception:
            payload['survey_review_url'] = '/admin/review/{}/'.format(conv.survey_submission_id)
    return JsonResponse(payload)

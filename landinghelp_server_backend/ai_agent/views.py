"""
Customer chat entry point for the AI assistant. Reuses messaging.Conversation (type=AI_ASSISTANT).
"""
import json
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .services import get_or_create_ai_conversation, respond

logger = logging.getLogger(__name__)


@require_GET
@login_required
@ensure_csrf_cookie
def assistant_chat(request):
    """
    Chat UI for the AI assistant. Lists messages in the user's AI conversation.
    """
    user = request.user
    conv = get_or_create_ai_conversation(user)
    messages = list(
        conv.messages.select_related('sender').order_by('created_at')
    )
    from translations.utils import get_request_language, get_display_text
    lang = get_request_language(request)
    i18n = {
        'title': get_display_text('AI 어시스턴트', lang) or 'AI 어시스턴트',
        'placeholder': get_display_text('질문을 입력하세요...', lang) or '질문을 입력하세요...',
        'send': get_display_text('보내기', lang) or '보내기',
        'back': get_display_text('돌아가기', lang) or '돌아가기',
    }
    return render(request, 'ai_agent/assistant_chat.html', {
        'conversation': conv,
        'messages': messages,
        'assistant_i18n': i18n,
    })


@require_POST
@login_required
@ensure_csrf_cookie
def assistant_send(request):
    """
    Accept a user message, save it, call the assistant, save the reply. Return JSON or redirect.
    """
    user = request.user
    body = request.POST.get('body') or ''
    if not body and request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body.decode('utf-8', errors='ignore'))
            body = data.get('body') or ''
        except Exception:
            pass
    body = (body or '').strip()
    if not body:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({'ok': False, 'error': 'Empty message.'}, status=400)
        return redirect('ai_agent:assistant_chat')

    conv = get_or_create_ai_conversation(user)
    from messaging.models import Message
    try:
        user_msg = Message.objects.create(conversation=conv, sender=user, body=body[:4000])
    except Exception as e:
        logger.warning("Failed to save user message: %s", e, exc_info=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
            return JsonResponse({'ok': False, 'error': 'Failed to save.'}, status=500)
        return redirect('ai_agent:assistant_chat')

    response_text, assistant_msg = respond(user, conv, body)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
        return JsonResponse({
            'ok': True,
            'user_message_id': user_msg.id,
            'assistant_message_id': assistant_msg.id if assistant_msg else None,
            'assistant_body': response_text,
        })
    return redirect('ai_agent:assistant_chat')

"""
Build context for the AI assistant from customer profile, survey, paid services, schedule, and knowledge.
Used by services.py before calling the LLM adapter.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_customer_profile(user) -> Dict[str, Any]:
    """Minimal customer profile for context (no PII overload)."""
    if not user or not getattr(user, 'id', None):
        return {}
    return {
        'user_id': user.id,
        'language': getattr(user, 'preferred_language', None) or 'ko',
        'role': getattr(user, 'role', None),
    }


def get_survey_and_quote_context(user) -> Dict[str, Any]:
    """Survey answers and quote summary for the customer's latest submission."""
    if not user or not getattr(user, 'id', None):
        return {}
    try:
        from survey.models import SurveySubmission
        from settlement.models import SettlementQuote
        sub = (
            SurveySubmission.objects.filter(user=user)
            .exclude(status=SurveySubmission.Status.DRAFT)
            .order_by('-submitted_at')
            .first()
        )
        if not sub:
            return {}
        out = {
            'submission_id': sub.id,
            'status': sub.status,
            'answers_summary': _summarize_answers(sub.answers or {}),
        }
        quote = (
            SettlementQuote.objects.filter(submission=sub)
            .filter(status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID))
            .order_by('-updated_at')
            .first()
        )
        if quote and getattr(quote, 'items', None):
            out['paid_services'] = [
                (item.get('code') or '', (item.get('label') or item.get('code') or ''))
                for item in (quote.items or []) if isinstance(item, dict)
            ]
        else:
            out['paid_services'] = []
        return out
    except Exception as e:
        logger.warning("get_survey_and_quote_context failed: %s", e, exc_info=True)
        return {}


def _summarize_answers(answers: dict) -> dict:
    """Reduce answers to a short summary (keys + truncated values) for context."""
    if not isinstance(answers, dict):
        return {}
    summary = {}
    for k, v in list(answers.items())[:30]:  # limit keys
        if v is None or v == '':
            continue
        if isinstance(v, (list, dict)):
            summary[k] = str(v)[:200]
        else:
            summary[k] = str(v)[:200]
    return summary


def get_schedule_context(user) -> Dict[str, Any]:
    """Current schedule (next 30 days) for the customer."""
    if not user or not getattr(user, 'id', None):
        return {}
    try:
        from settlement.schedule_utils import get_schedule_for_display, get_paid_service_codes_for_user, filter_schedule_to_paid_services
        from datetime import datetime, timedelta
        from django.utils import timezone
        schedule = get_schedule_for_display(user) or {}
        paid_codes = get_paid_service_codes_for_user(user)
        if paid_codes:
            schedule = filter_schedule_to_paid_services(schedule, paid_codes)
        today = timezone.now().date()
        end = today + timedelta(days=30)
        by_date = []
        for date_str, items in (schedule or {}).items():
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                continue
            if today <= dt <= end and items:
                by_date.append((date_str, [(i.get('label') or i.get('code') or '') for i in items if isinstance(i, dict)]))
        by_date.sort(key=lambda x: x[0])
        return {
            'schedule': schedule,
            'schedule_summary': _format_schedule_summary(by_date),
        }
    except Exception as e:
        logger.warning("get_schedule_context failed: %s", e, exc_info=True)
        return {'schedule': {}, 'schedule_summary': 'Error loading schedule.'}


def _format_schedule_summary(by_date: List[tuple]) -> str:
    if not by_date:
        return 'No upcoming scheduled services.'
    lines = []
    for date_str, labels in by_date[:14]:
        lines.append(f"{date_str}: {', '.join(labels[:5])}{'...' if len(labels) > 5 else ''}")
    return '\n'.join(lines)


def get_knowledge_context(service_codes: Optional[List[str]] = None) -> str:
    """
    Admin-managed knowledge: FAQs, service instructions. Optionally filtered by service_codes.
    Returns a single text block for the prompt.
    """
    from .models import AssistantKnowledge
    qs = AssistantKnowledge.objects.filter(is_active=True).order_by('display_order', 'id')
    if service_codes:
        from django.db.models import Q
        qs = qs.filter(Q(service_code='') | Q(service_code__in=service_codes))
    parts = []
    for k in qs:
        parts.append(f"[{k.get_category_display()}] {k.title}\n{k.content}")
    return '\n\n'.join(parts) if parts else '(No knowledge entries configured.)'


def build_context(user, service_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Full context for the assistant: profile, survey/quote, schedule, knowledge.
    """
    profile = get_customer_profile(user)
    survey_quote = get_survey_and_quote_context(user)
    schedule = get_schedule_context(user)
    if not service_codes and survey_quote.get('paid_services'):
        service_codes = [c for c, _ in survey_quote['paid_services'] if c]
    knowledge = get_knowledge_context(service_codes)
    return {
        'profile': profile,
        'survey_quote': survey_quote,
        'schedule': schedule,
        'knowledge': knowledge,
        'service_codes': service_codes or [],
    }

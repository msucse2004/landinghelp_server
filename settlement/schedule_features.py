from datetime import date
import ast

from survey.quote_input import get_quote_input_data

from .constants import get_schedule_ordered_services, _normalize_state_code
from .models import ServiceScheduleItem
from .schedule_training_data import get_training_eligible_schedule_items


DELIVERY_PREFERENCE_TO_SERVICE_TYPE = {
    'agent_direct': ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
    'ai_service': ServiceScheduleItem.ServiceType.AI_AGENT,
    'self_search': ServiceScheduleItem.ServiceType.SELF_SEARCH,
}


def _coerce_text(value):
    if value is None:
        return ''
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith('[') and raw.endswith(']'):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                return _coerce_text(parsed)
        return raw
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ', '.join(parts)
    return str(value).strip()


def normalize_service_code_set(service_codes):
    if isinstance(service_codes, str):
        service_codes = [service_codes]
    normalized = {
        str(code or '').strip().upper()
        for code in (service_codes or [])
        if str(code or '').strip()
    }
    if not normalized:
        return []
    return get_schedule_ordered_services(sorted(list(normalized)))


def parse_entry_date_or_none(value):
    if value is None:
        return None
    if hasattr(value, 'year'):
        return value
    raw = str(value or '').strip()
    if len(raw) < 10:
        return None
    try:
        return date(int(raw[:4]), int(raw[5:7]), int(raw[8:10]))
    except (ValueError, TypeError):
        return None


def normalize_region_fields(quote_input_data):
    data = quote_input_data or {}
    settlement_state = _coerce_text(data.get('settlement_state'))
    settlement_city = _coerce_text(data.get('settlement_city'))
    region = _coerce_text(data.get('region'))

    state_code = _normalize_state_code(settlement_state or region)

    city = settlement_city
    if not city and region and ',' in region:
        city = (region.split(',', 1)[1] or '').strip()

    canonical_region = ', '.join(part for part in [state_code, city] if part).strip()
    if not canonical_region:
        canonical_region = region

    return {
        'region': canonical_region,
        'state_code': state_code,
        'city': city,
    }


def build_entry_date_features(entry_date_value, today=None):
    today_date = today or date.today()
    entry_date = parse_entry_date_or_none(entry_date_value)
    if not entry_date:
        return {
            'entry_date': None,
            'remaining_days_to_entry': None,
        }
    return {
        'entry_date': entry_date,
        'remaining_days_to_entry': (entry_date - today_date).days,
    }


def _derive_service_types_by_code(answers, service_codes):
    answers = answers or {}
    mode = _coerce_text(answers.get('service_delivery_mode') or 'bulk') or 'bulk'
    bulk_pref = _coerce_text(answers.get('service_delivery_preference'))
    per_service = answers.get('service_delivery_per_service') or {}
    if not isinstance(per_service, dict):
        per_service = {}
    normalized_per_service = {
        str(key or '').strip().upper(): _coerce_text(value)
        for key, value in per_service.items()
        if str(key or '').strip()
    }

    out = {}
    for code in (service_codes or []):
        raw_pref = ''
        if mode == 'per_service':
            raw_pref = _coerce_text(
                normalized_per_service.get(str(code or '').strip().upper())
                or per_service.get(code)
                or per_service.get(str(code).strip())
                or ''
            )
        else:
            raw_pref = bulk_pref
        out[code] = DELIVERY_PREFERENCE_TO_SERVICE_TYPE.get(raw_pref, ServiceScheduleItem.ServiceType.AI_AGENT)
    return out


def _build_service_mix_features(service_types_by_code):
    values = list((service_types_by_code or {}).values())
    in_person = sum(1 for v in values if v == ServiceScheduleItem.ServiceType.IN_PERSON_AGENT)
    ai_count = sum(1 for v in values if v == ServiceScheduleItem.ServiceType.AI_AGENT)
    self_count = sum(1 for v in values if v == ServiceScheduleItem.ServiceType.SELF_SEARCH)
    total = len(values)
    return {
        'service_count': total,
        'in_person_service_count': in_person,
        'non_in_person_service_count': max(total - in_person, 0),
        'ai_service_count': ai_count,
        'self_search_service_count': self_count,
        'has_in_person_services': in_person > 0,
    }


def _build_customer_profile_features(submission, quote_input_data):
    """
    고객 프로필 피처. 추후 필드 추가 시 여기에만 반영하면 됩니다.
    추가 후보: visa_type, has_children, housing_type, language_code 등.
    """
    data = quote_input_data or {}
    answers = getattr(submission, 'answers', None) or {}
    special_requirements = _coerce_text(data.get('special_requirements'))
    return {
        'household_size': data.get('household_size'),
        'household_adults': data.get('household_adults'),
        'household_children': data.get('household_children'),
        'current_country': _coerce_text(data.get('current_country')),
        'entry_purpose': _coerce_text(data.get('entry_purpose')),
        'stay_status': _coerce_text(data.get('stay_status')),
        'stay_duration': _coerce_text(data.get('stay_duration')),
        'preferred_support_mode': _coerce_text(getattr(submission, 'preferred_support_mode', None)),
        'has_special_requirements': bool(special_requirements),
        'raw_special_requirements': special_requirements,
        'preferred_agent_id': _coerce_text(answers.get('preferred_agent_id')) or None,
    }


def _build_dependency_sensitive_services(normalized_services):
    ordered = get_schedule_ordered_services(list(normalized_services or []))
    return {
        'ordered_service_codes': ordered,
        'dependency_sensitive_service_codes': ordered[: min(5, len(ordered))],
    }


def build_current_submission_feature_context(submission, *, today=None):
    quote_input_data = get_quote_input_data(submission) if submission else {}
    region_features = normalize_region_fields(quote_input_data)
    entry_features = build_entry_date_features(quote_input_data.get('entry_date'), today=today)

    required_codes = normalize_service_code_set(getattr(submission, 'requested_required_services', None) or [])
    optional_codes = normalize_service_code_set(getattr(submission, 'requested_optional_services', None) or [])
    quote_codes = normalize_service_code_set(quote_input_data.get('service_codes') or [])
    requested_services = normalize_service_code_set(required_codes + optional_codes + quote_codes)

    service_types_by_code = _derive_service_types_by_code(
        getattr(submission, 'answers', None) or {},
        requested_services,
    )
    service_mix = _build_service_mix_features(service_types_by_code)
    dependency_features = _build_dependency_sensitive_services(requested_services)
    profile_features = _build_customer_profile_features(submission, quote_input_data)

    # 현재 고객이 사용 가능한 일정 창(주 단위). historical schedule_week_span 과 비교.
    remaining = entry_features['remaining_days_to_entry']
    expected_schedule_weeks = round(remaining / 7.0, 1) if remaining is not None and remaining > 0 else 2.0

    return {
        'submission_id': getattr(submission, 'id', None),
        'entry_date': entry_features['entry_date'],
        'remaining_days_to_entry': entry_features['remaining_days_to_entry'],
        'expected_schedule_weeks': expected_schedule_weeks,
        'region': region_features['region'],
        'state_code': region_features['state_code'],
        'city': region_features['city'],
        'requested_service_codes': requested_services,
        'required_service_codes': required_codes,
        'optional_service_codes': optional_codes,
        'service_types_by_code': service_types_by_code,
        **service_mix,
        **dependency_features,
        **profile_features,
    }


def build_historical_schedule_feature_contexts(*, service_codes=None, max_items=500, today=None):
    normalized_filter_codes = normalize_service_code_set(service_codes or [])
    rows = get_training_eligible_schedule_items(
        service_codes=normalized_filter_codes,
        service_types={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        max_items=max_items,
    )

    out = []
    for row in rows:
        submission = row.get('submission')
        quote_input_data = row.get('quote_input_data') or {}
        region_features = normalize_region_fields(quote_input_data)
        entry_features = build_entry_date_features(row.get('entry_date'), today=today)

        requested_services = normalize_service_code_set(
            list(getattr(submission, 'requested_required_services', None) or [])
            + list(getattr(submission, 'requested_optional_services', None) or [])
            + list(quote_input_data.get('service_codes') or [])
        )
        dependency_features = _build_dependency_sensitive_services(requested_services)
        service_types_by_code = _derive_service_types_by_code(
            getattr(submission, 'answers', None) or {},
            requested_services,
        )

        starts_at = row.get('starts_at')
        entry_date = entry_features['entry_date']  # 내부 계산용, feature로 노출하지 않음
        days_from_entry = None
        if starts_at and entry_date:
            days_from_entry = (starts_at.date() - entry_date).days

        out.append({
            'plan_id': row.get('plan_id'),
            'item_id': row.get('item_id'),
            'service_code': (row.get('service_code') or '').strip().upper(),
            'starts_at': starts_at,
            # entry_date(절대날짜)와 remaining_days_to_entry(today 기준 음수값)는
            # 일반화에 불리해 historical row에서 제외.
            # 입국 기준 상대 오프셋인 days_from_entry와 플랜 전체 주 스팬만 사용.
            'days_from_entry': days_from_entry,
            'schedule_week_span': row.get('schedule_week_span'),
            'assigned_agent_id': row.get('assigned_agent_id'),
            'region': region_features['region'],
            'state_code': region_features['state_code'],
            'city': region_features['city'],
            'requested_service_codes': requested_services,
            'service_types_by_code': service_types_by_code,
            **dependency_features,
            **_build_service_mix_features(service_types_by_code),
            **_build_customer_profile_features(submission, quote_input_data),
        })
    return out

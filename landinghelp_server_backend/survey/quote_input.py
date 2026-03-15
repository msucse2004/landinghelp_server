"""
견적 자동화용 설문 답변 정규화.
제출(submission)에서 기계 판독 가능한 견적 입력 딕셔너리를 추출합니다.
전체 가격 엔진은 구현하지 않고, 구조만 준비합니다.
"""
from datetime import date

# 견적·ML 로직에서 사용하는 캐노니컬 키. Admin 문항의 quote_mapping_key와 일치시키면 됨.
QUOTE_MAPPING_KEYS = (
    'service_codes',
    'region',
    'entry_date',
    'household_size',
    'household_adults',   # 입국 성인 수 (만 18세 이상) — ML/견적 draft용
    'household_children', # 입국 자녀 수 (만 19세 미만) — ML/견적 draft용
    'settlement_state',   # 정착 주 (state)
    'settlement_city',    # 정착 도시 — region 조합용
    'current_country',   # 현재 거주 국가 — ML용
    'entry_purpose',      # 미국 입국 목적 — ML용
    'stay_status',       # 체류 신분 — ML용
    'stay_duration',     # 예상 체류 기간 — ML용
    'add_on_codes',
    'special_requirements',
)


def _as_code_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        return [raw] if raw else []
    return [str(value).strip()] if str(value).strip() else []


def _normalize_value(value, value_type):
    """quote_value_type에 따라 값을 정규화."""
    if value is None:
        return None
    if value_type == 'service_codes' or value_type == 'add_on_codes':
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            try:
                import json
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except (ValueError, TypeError):
                pass
            return [value.strip()] if value.strip() else []
        return []
    if value_type == 'region' or value_type == 'text' or value_type == 'special_requirements':
        return str(value).strip() or None
    if value_type == 'date':
        if hasattr(value, 'isoformat'):
            return value.isoformat()[:10]
        s = str(value).strip()
        if len(s) >= 10:
            return s[:10]
        return s or None
    if value_type == 'number':
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    if value_type == 'options':
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return [str(value).strip()] if str(value).strip() else []
    return value


def get_quote_input_data(submission):
    """
    제출에서 견적 입력용 정규화 딕셔너리 추출.
    반환: {
        "service_codes": ["CODE1", ...],
        "region": "CA" or "CA, Los Angeles",
        "entry_date": "2025-03-01",
        "household_size": 2,
        "add_on_codes": [],
        "special_requirements": "...",
    }
    누락된 키는 None 또는 기본값.
    """
    from .models import SurveyQuestion
    if not submission:
        return _empty_quote_input()
    answers = submission.answers or {}
    out = {k: None for k in QUOTE_MAPPING_KEYS}
    out['service_codes'] = []
    out['add_on_codes'] = []

    # 설문 문항 중 quote_relevant + quote_mapping_key 있는 것만 매핑
    qs = SurveyQuestion.objects.filter(
        is_active=True,
        quote_relevant=True,
    ).exclude(quote_mapping_key='').values('key', 'quote_mapping_key', 'quote_value_type')
    for q in qs:
        mapping_key = (q.get('quote_mapping_key') or '').strip()
        if mapping_key not in QUOTE_MAPPING_KEYS:
            continue
        raw = answers.get(q['key'])
        # 제출 모델의 전용 필드와 키가 일치하면 그쪽 우선
        if q['key'] == 'requested_required_services' and hasattr(submission, 'requested_required_services'):
            raw = getattr(submission, 'requested_required_services', None) or raw
        if q['key'] == 'requested_optional_services' and hasattr(submission, 'requested_optional_services'):
            raw = getattr(submission, 'requested_optional_services', None) or raw
        value_type = (q.get('quote_value_type') or '').strip() or 'text'
        normalized = _normalize_value(raw, value_type)
        if normalized is None:
            continue
        if mapping_key == 'service_codes' or mapping_key == 'add_on_codes':
            existing = out.get(mapping_key) or []
            if isinstance(normalized, list):
                out[mapping_key] = list(set(existing) | set(normalized))
            else:
                out[mapping_key] = existing + [normalized]
        else:
            out[mapping_key] = normalized

    # service_codes: requested_required_services + requested_optional_services 병합 (문항 매핑 없어도)
    if getattr(submission, 'requested_required_services', None):
        out['service_codes'] = list(set(out['service_codes']) | set(_as_code_list(submission.requested_required_services)))
    if getattr(submission, 'requested_optional_services', None):
        out['service_codes'] = list(set(out['service_codes']) | set(_as_code_list(submission.requested_optional_services)))

    # region: settlement_state + settlement_city 조합 (기존 region 키 미설정 시)
    if out.get('region') is None and (out.get('settlement_state') or out.get('settlement_city')):
        parts = [out.get('settlement_state') or '', out.get('settlement_city') or '']
        out['region'] = ', '.join(p for p in parts if p).strip() or None
    # household_size: ML용 — adults + children 합산 (숫자만 사용 시)
    if out.get('household_size') is None and (out.get('household_adults') is not None or out.get('household_children') is not None):
        try:
            a = int(out.get('household_adults') or 0)
            c = int(out.get('household_children') or 0)
            out['household_size'] = a + c
        except (TypeError, ValueError):
            pass

    return out


def _empty_quote_input():
    d = {k: None for k in QUOTE_MAPPING_KEYS}
    d['service_codes'] = []
    d['add_on_codes'] = []
    return d

# config: 템플릿 컨텍스트 프로세서

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from content.models import CarouselSlide

# 정착 서비스 서브네비 라벨 (StaticTranslation 사용, locale과 중복 제거)
SETTLEMENT_NAV_KEYS = [
    ('nav_settlement', '정착서비스'),
    ('nav_intro', '정착 서비스 소개'),
    ('nav_plan', '정착 플랜'),
    ('nav_calendar', '고객예약 달력'),
    ('nav_reviews', '고객 후기'),
    ('nav_cost_estimate', '셀프 정착 비용 예상'),
]

# 정착 서비스 메인 대시보드 본문 (제목, 소개문, 번호 링크)
SETTLEMENT_MAIN_KEYS = [
    ('title', '정착서비스'),
    ('intro', '미국 이민·정착 관련 서비스를 제공합니다.'),
    ('link1', '1. 정착 서비스 소개'),
    ('link2', '2. 정착 플랜'),
    ('link3', '3. 고객 후기'),
    ('link4', '4. 셀프 정착 비용 예상'),
]

# 정착 서비스 소개 페이지
SETTLEMENT_INTRO_KEYS = [
    ('title', '정착 서비스 소개'),
    ('subtitle', '미국 이민·정착을 위한 맞춤 서비스를 소개합니다.'),
    ('preparing', '(준비 중)'),
]

# 고객 후기 페이지
SETTLEMENT_REVIEWS_KEYS = [
    ('title', '고객 후기'),
    ('subtitle', '정착서비스를 이용하신 고객님들의 후기입니다.'),
    ('preparing', '(준비 중)'),
]

# 셀프 정착 비용 예상 페이지
SETTLEMENT_COST_ESTIMATE_KEYS = [
    ('title', '셀프 정착 비용 예상'),
    ('subtitle', '직접 정착하실 경우 예상 비용을 계산해 보세요.'),
    ('preparing', '(준비 중)'),
]


def _settlement_i18n(request, keys_list):
    """StaticTranslation에서 현재 언어로 번역 dict 생성."""
    from translations.utils import get_display_text, get_request_language
    lang = get_request_language(request)
    try:
        return {key: get_display_text(msg_key, lang) for key, msg_key in keys_list}
    except Exception:
        return {key: msg_key for key, msg_key in keys_list}


def settlement_nav_i18n(request):
    """정착 서비스 서브네비·메인·소개·후기·비용예상 페이지 문구를 현재 언어로 제공 (StaticTranslation)."""
    return {
        'settlement_nav': _settlement_i18n(request, SETTLEMENT_NAV_KEYS),
        'settlement_main': _settlement_i18n(request, SETTLEMENT_MAIN_KEYS),
        'settlement_intro': _settlement_i18n(request, SETTLEMENT_INTRO_KEYS),
        'settlement_reviews': _settlement_i18n(request, SETTLEMENT_REVIEWS_KEYS),
        'settlement_cost_estimate': _settlement_i18n(request, SETTLEMENT_COST_ESTIMATE_KEYS),
    }


def ad_carousel_slides(request):
    """모든 화면 하단 광고 캐러셀 슬라이드 (placement=AD). 언어별 표시용 _display 보강."""
    slides = list(CarouselSlide.objects.filter(
        placement=CarouselSlide.Placement.AD,
        is_active=True
    ).order_by('order', 'id'))
    from translations.utils import get_request_language, enrich_objects_for_display
    lang = get_request_language(request)
    try:
        enrich_objects_for_display(slides, ['title', 'subtitle'], language_code=lang)
    except Exception:
        for s in slides:
            s.title_display = getattr(s, 'title', '') or ''
            s.subtitle_display = getattr(s, 'subtitle', '') or ''
    return {'ad_carousel_slides': slides}


# 팝업 자체 문구용 키 → 실패 목록에 넣지 않음 (목록에 노출 시 중복/혼동 방지)
_TRANSLATION_FAILED_POPUP_KEYS = frozenset({
    '번역 실패',
    '번역에 실패했습니다. 일부 문구가 원문으로 표시될 수 있습니다.',
})


def translation_failed_alert(request):
    """번역 실패 시 팝업용 플래그·제목·메시지·실패한 키·에러 목록."""
    from translations.utils import get_translation_failed, get_translation_failed_entries, get_display_text, get_request_language
    if not get_translation_failed():
        return {
            'translation_failed': False,
            'translation_failed_title': '',
            'translation_failed_message': '',
            'translation_failed_keys': [],
            'translation_failed_entries': [],
        }
    lang = get_request_language(request)
    title = get_display_text('번역 실패', lang) or 'Translation failed'
    msg = get_display_text('번역에 실패했습니다. 일부 문구가 원문으로 표시될 수 있습니다.', lang) or 'Some text may appear in the original language.'
    all_entries = get_translation_failed_entries()
    # 팝업 제목/메시지용 키는 실패 목록에서 제외
    failed_entries = [e for e in all_entries if e['key'] not in _TRANSLATION_FAILED_POPUP_KEYS]
    failed_keys = [e['key'] for e in failed_entries]  # 하위 호환
    return {
        'translation_failed': True,
        'translation_failed_title': title,
        'translation_failed_message': msg,
        'translation_failed_keys': failed_keys,
        'translation_failed_entries': failed_entries,
    }


@sensitive_variables('user', 'password')
def email_config_warning(request):
    """
    SMTP 백엔드 사용 시 EMAIL_HOST_USER, EMAIL_HOST_PASSWORD가 비어 있으면 경고 플래그 전달.
    admin(staff/superuser) 로그인 시에만 표시.
    """
    warning = False
    if getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_staff:
        if 'smtp' in (getattr(settings, 'EMAIL_BACKEND', '') or '').lower():
            user = getattr(settings, 'EMAIL_HOST_USER', '') or ''
            password = getattr(settings, 'EMAIL_HOST_PASSWORD', '') or ''
            if not user.strip() or not password.strip():
                warning = True
    return {'email_config_warning': warning}

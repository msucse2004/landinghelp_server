# 게스트(비로그인)는 영어, 로그인 사용자는 DB 선호 언어를 매 요청마다 적용
from django.utils import translation
from django.conf import settings

# settings.LANGUAGES 에 있는 언어 코드만 허용
_VALID_LANGS = None


def _get_valid_languages():
    global _VALID_LANGS
    if _VALID_LANGS is None:
        _VALID_LANGS = {code for code, _ in getattr(settings, 'LANGUAGES', [])}
    return _VALID_LANGS


class GuestDefaultLanguageMiddleware:
    """
    AuthenticationMiddleware 다음에 실행.
    - 비로그인: 세션의 django_language(드롭다운 선택)를 사용, 없으면 영어(en).
    - 로그인: 세션의 django_language(드롭다운)를 우선 사용, 없으면 DB preferred_language.
    (헤더 드롭다운으로 변경한 언어가 적용되도록 세션을 우선함)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        valid = _get_valid_languages()
        # 쿠키(방금 변경한 값) 우선, 없으면 세션, 그래도 없으면 DB(로그인 시) 또는 en(게스트)
        lang = (request.COOKIES.get('django_language') or request.session.get('django_language') or '').strip()
        if not lang or lang not in valid:
            lang = None
        if not lang and request.user.is_authenticated:
            lang = (getattr(request.user, 'preferred_language', None) or '').strip()
        if not lang or lang not in valid:
            lang = 'en'
        if request.session.get('django_language') != lang:
            request.session['django_language'] = lang
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        return response

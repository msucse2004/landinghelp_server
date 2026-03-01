# 디폴트 언어 en. 헤더 드롭다운/로그인 시 선호어로 세팅되면 모든 view에서 해당 언어 적용.
from django.utils import translation
from django.conf import settings
from translations.utils import get_valid_language_codes, clear_translation_failed


class CsrfTrustCloudflareMiddleware:
    """
    DEBUG 시 *.trycloudflare.com Origin을 CSRF 신뢰 목록에 동적 추가.
    CsrfViewMiddleware 보다 먼저 실행되어야 하므로 MIDDLEWARE 상단에 배치.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, 'DEBUG', False):
            host = request.get_host().split(':')[0]
            if host.endswith('.trycloudflare.com'):
                origin = f'https://{request.get_host()}'
                if origin not in settings.CSRF_TRUSTED_ORIGINS:
                    settings.CSRF_TRUSTED_ORIGINS = list(settings.CSRF_TRUSTED_ORIGINS) + [origin]
        return self.get_response(request)

class GuestDefaultLanguageMiddleware:
    """
    언어 우선순위:
    1) Guest: 기본 en. 쿠키/세션 있으면 그대로 사용.
    2) 헤더에서 언어 변경 시: 즉시 해당 언어로 (set_language → 리다이렉트).
    3) 로그인 시: DB 선호 언어로 즉시 변경. 이후 헤더에서 바꾸면 그때 그 언어로.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_translation_failed()
        valid = get_valid_language_codes()
        if request.user.is_authenticated:
            # 헤더에서 이번에 언어를 바꾼 적 있으면 → 그 언어로 즉시
            if request.session.get('language_explicitly_set') and request.session.get('django_language') in valid:
                lang = request.session['django_language']
            else:
                # 로그인 직후·헤더 미변경: DB 선호 언어
                try:
                    request.user.refresh_from_db(fields=['preferred_language'])
                except Exception:
                    pass
                lang = (getattr(request.user, 'preferred_language', None) or '').strip()
                if not lang or lang not in valid:
                    lang = (request.COOKIES.get('django_language') or '').strip()
                if not lang or lang not in valid:
                    lang = 'en'
                request.session['django_language'] = lang
                request.session.pop('language_explicitly_set', None)
                request.session.modified = True
        else:
            # Guest: 쿠키/세션에서 읽기만 하고, 세션에는 쓰지 않음.
            # (로그인 직후 같은 요청에서 signal이 세션을 선호어로 덮어쓸 수 있도록 함)
            lang = (request.COOKIES.get('django_language') or request.session.get('django_language') or '').strip()
            if not lang or lang not in valid:
                lang = 'en'
            # Guest일 때는 세션을 갱신하지 않음 → 로그인 POST 시 signal이 DB 선호어로 세팅 가능
        if request.user.is_authenticated and request.session.get('django_language') != lang:
            request.session['django_language'] = lang
            request.session.modified = True
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        # 응답 시 쿠키를 세션 언어와 동기화. 로그인 직후면 인증된 사용자 DB 선호어로 쿠키 확정
        cookie_lang = request.session.get('django_language') or lang
        if request.user.is_authenticated:
            try:
                request.user.refresh_from_db(fields=['preferred_language'])
                pref = (getattr(request.user, 'preferred_language', None) or '').strip()
                if pref and pref in valid:
                    cookie_lang = pref
                    if request.session.get('django_language') != pref:
                        request.session['django_language'] = pref
                        request.session.modified = True
            except Exception:
                pass
        if cookie_lang and cookie_lang in valid:
            response.set_cookie(
                'django_language',
                cookie_lang,
                max_age=365 * 24 * 60 * 60,
                path='/',
            )
        return response

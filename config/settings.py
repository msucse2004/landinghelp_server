"""
Django settings for landinghelp_server project.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 기준 .env 로드 (cwd와 무관하게 동일 경로에서 로드)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
# cwd의 .env도 있으면 로드 (override 없음이 기본이라 먼저 로드된 값 유지)
load_dotenv()

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', '0') in ('1', 'true', 'yes', 'True')

_allowed = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
ALLOWED_HOSTS = [h.strip() for h in _allowed if h.strip()]
if DEBUG and '*' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = list(ALLOWED_HOSTS) + [
        '127.0.0.1', 'localhost', '[::1]',
        '.trycloudflare.com',  # Cloudflare Tunnel 개발용 (예: xxx.trycloudflare.com)
    ]
    ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))  # 중복 제거

# Application definition
INSTALLED_APPS = [
    'adminsortable2',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Project apps
    'accounts',
    'billing',
    'content',
    'settlement',
    'survey',
    'community',
    'messaging',
    'translations',
    'ai_agent',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # LocaleMiddleware 제거: Accept-Language가 세션/쿠키보다 우선해 로그인 후 선호어가 덮어씌워짐.
    # config.middleware.GuestDefaultLanguageMiddleware 가 세션·쿠키·DB 선호어만으로 언어 제어.
    'django.middleware.common.CommonMiddleware',
    'config.middleware.CsrfTrustCloudflareMiddleware',  # DEBUG 시 Cloudflare Tunnel Origin 허용 (CsrfViewMiddleware 전에 실행)
    'django.middleware.csrf.CsrfViewMiddleware',
    'config.middleware.LogoutCsrfFallbackMiddleware',  # 로그아웃 POST 403 시 홈으로 리다이렉트
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.GuestDefaultLanguageMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'billing.context_processors.user_plan_info',
                'config.context_processors.email_config_warning',
                'config.context_processors.translation_failed_alert',
                'config.context_processors.settlement_nav_i18n',
                'config.context_processors.ad_carousel_slides',
                'messaging.context_processors.messaging_unread',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database (env: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'landinghelp'),
        'USER': os.environ.get('DB_USER', 'landinghelp'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'landinghelp'),
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Password validation (테스트용 잠시 비활성화 → 운영 시 아래 주석 해제)
AUTH_PASSWORD_VALIDATORS = []
# AUTH_PASSWORD_VALIDATORS = [
#     {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
#     {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
#     {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
#     {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
# ]

# Internationalization
LANGUAGE_CODE = 'en'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / 'locale']
LANGUAGES = [
    ('ko', 'KR 한국어'),
    ('en', 'EN English'),
    ('es', 'ES Español'),
    ('zh-hans', 'ZH 中文(简体)'),
    ('zh-hant', 'ZH 中文(繁體)'),
    ('vi', 'VI Tiếng Việt'),
]

# Static files
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (업로드 파일)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email: 환경변수로만 읽음. 키/비밀/계정은 코드·깃에 넣지 말 것. .env는 gitignore.
# 확인: python manage.py check_email_env
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend',
)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@landinghelp.local')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() in ('true', '1', 'yes')
EMAIL_HOST_USER = (os.environ.get('EMAIL_HOST_USER') or '').strip()
EMAIL_HOST_PASSWORD = (os.environ.get('EMAIL_HOST_PASSWORD') or '').strip()

# 설문 리마인드 등 이메일 링크용 절대 URL (예: https://yoursite.com). 미설정 시 상대 경로만 사용.
SITE_URL = os.environ.get('SITE_URL', '').strip().rstrip('/') or None

# 에러 페이지에서 민감 설정(이메일 등) 숨김
DEFAULT_EXCEPTION_REPORTER_FILTER = 'config.debug.SensitiveDataExceptionFilter'

# CSRF: POST 등 요청 시 Origin 검증. Cloudflare Tunnel 등은 아래에서 동적 추가 또는 env로 설정
_csrf_origins = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]

# Auth
LOGIN_REDIRECT_URL = 'app_entry'
LOGOUT_REDIRECT_URL = 'home'
LOGIN_URL = 'login'

# 번역 API: 1순위 Google, 2순위 DeepL
# Google: 비활성화 시 DeepL만 사용. 활성화하려면 True + GOOGLE_TRANSLATE_API_KEY 설정
GOOGLE_TRANSLATE_ENABLED = False
GOOGLE_TRANSLATE_API_KEY = os.environ.get('GOOGLE_TRANSLATE_API_KEY', '')
# DeepL: https://www.deepl.com/pro-api 에서 API 키 발급. 무료 tier: 500,000자/월.
# 웹 요청 시에도 config.deepl_env.get_deepl_auth_key()로 env+레지스트리 재조회함
from config.deepl_env import get_deepl_auth_key
DEEPL_AUTH_KEY = get_deepl_auth_key()

# AI assistant (ai_agent): stub by default; set AI_AGENT_LLM_ADAPTER to a dotted path for production.
# AI_AGENT_BOT_USER_ID: User pk to use as sender for assistant messages (default: first staff).
AI_AGENT_BOT_USER_ID = os.environ.get('AI_AGENT_BOT_USER_ID', None)
if AI_AGENT_BOT_USER_ID is not None:
    try:
        AI_AGENT_BOT_USER_ID = int(AI_AGENT_BOT_USER_ID)
    except (TypeError, ValueError):
        AI_AGENT_BOT_USER_ID = None
AI_AGENT_LLM_ADAPTER = os.environ.get('AI_AGENT_LLM_ADAPTER', 'stub')  # 'stub' or e.g. 'ai_agent.llm_ollama.Adapter'

# 견적서 공식 포맷 (Admin 검토 화면·이메일)
# QUOTATION_COMPANY_NAME = 'LifeAI US'
# QUOTATION_VALID_DAYS = 30
# QUOTATION_TERMS = 'Payment due upon acceptance. This quotation is valid until the date stated above.'
# QUOTATION_CONTACT = 'For questions, please contact us via message or email.'

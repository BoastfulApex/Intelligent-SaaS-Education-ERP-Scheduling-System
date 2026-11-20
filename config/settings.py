import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
import os
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env('SECRET_KEY')

# KPI (EEMSportedu) integratsiyasi — davomatni o'qish uchun (scheduling/kpi_client.py).
# Kalitni KPI tomoni `create_integration_key --scopes attendance:read` bilan
# yaratadi; bu yerga qo'yishdan oldin kodga qattiq yozmang, faqat .env orqali.
KPI_BASE_URL = env('KPI_BASE_URL', default='')
KPI_API_KEY  = env('KPI_API_KEY', default='')
KPI_TIMEOUT  = env.int('KPI_TIMEOUT', default=15)
# XAVFSIZ DEFAULT: `.env` da qator yo'q yoki xato yozilgan bo'lsa, production
# to'liq traceback (sozlama qiymatlari, SQL, fayl yo'llari bilan) ko'rsatmasin.
# Lokal ishlash uchun `.env` da `DEBUG=True` yozilgan bo'lishi kerak.
DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# Django admin manzili. Standart `admin/` — avtomatlashtirilgan skanerlar
# birinchi navbatda shuni sinaydi. `.env` da maxfiy qiymat bering
# (masalan `ADMIN_URL=ichki-boshqaruv-7f2a/`), bo'sh qoldirilsa admin
# umuman ulanmaydi (`config/urls.py`).
ADMIN_URL = env('ADMIN_URL', default='admin/')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',   # logout'da tokenni bekor qilish
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    # Local apps
    'accounts',
    'organizations',
    'academic',
    'scheduling',
    'reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.current_user.CurrentRequestMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL')
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    # Qo'lda qo'yiladigan admin parollari uchun — ommaviy generatsiya qilingan
    # o'qituvchi parollari tasodifiy, ularga baribir ta'sir qilmaydi.
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'uz'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # `collectstatic` shu yerga yig'adi (production, nginx serve qiladi)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # Integratsiya endpointlari uchun tezlik chegarasi — tashqi tizim
    # xato tsiklga tushib qolsa bazani bo'g'ib qo'ymasligi uchun.
    'EXCEPTION_HANDLER': 'config.exception_handler.exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'integration': '60/min',
        # Brute force himoyasi — chegara IP bo'yicha EMAS, LOGIN bo'yicha
        # (`accounts/throttling.py`). Sabab: tizim proksi ortida ishlaydi,
        # barcha so'rov bitta IP'dan kelib, IP bo'yicha blok butun
        # tashkilotni to'xtatib qo'yardi.
        'login': '10/min',
        'login_hour': '50/hour',
    },
    # Production'da DRF Browsable API o'chiriladi — u butun API yuzasini
    # HTML forma bilan ko'rsatadi. Lokalda (DEBUG) qulaylik uchun qoladi.
    'DEFAULT_RENDERER_CLASSES': (
        ['rest_framework.renderers.JSONRenderer']
        if not DEBUG else
        ['rest_framework.renderers.JSONRenderer',
         'rest_framework.renderers.BrowsableAPIRenderer']
    ),
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE':       'Education ERP & Scheduling API',
    'DESCRIPTION': 'Intelligent SaaS Education ERP tizimi uchun REST API',
    'VERSION':     '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    # Avval anonim ochiq edi — autentifikatsiyasiz `GET /api/schema/` 228 KB,
    # 95 endpointli to'liq API xaritasini qaytarardi (o'lchangan, 2026-11-20).
    # Endi faqat autentifikatsiyalangan foydalanuvchi ko'radi.
    'SERVE_PERMISSIONS': ['rest_framework.permissions.IsAuthenticated'],
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    # Chiqishda (`/api/auth/logout/`) refresh token BEKOR qilinishi uchun.
    # Avval blacklist umuman yo'q edi — o'g'irlangan refresh token 7 kun
    # davomida yangi access token olib turardi va uni to'xtatib bo'lmasdi.
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000',
    'http://localhost:5173',
    'http://localhost:5174',
])

# ── Production xavfsizlik sarlavhalari ──────────────────────────────────────
# Lokalda (DEBUG=True) o'chiq — aks holda `http://localhost` HTTPS'ga
# yo'naltirilib, ishlab bo'lmasdi.
if not DEBUG:
    # nginx HTTPS'ni tugatadi va `X-Forwarded-Proto` yuboradi — bu sarlavhasiz
    # Django so'rovni HTTP deb bilib, cheksiz redirect siklini hosil qiladi.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)

    # HSTS — brauzer shu domenga faqat HTTPS orqali boradi (SSL-stripping
    # hujumini to'sadi). DIQQAT: domen to'liq HTTPS'ga o'tganiga ishonch
    # hosil qilmasdan `INCLUDE_SUBDOMAINS` ni yoqmang.
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)  # 1 yil
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
        'SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
    SECURE_HSTS_PRELOAD = False

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    X_FRAME_OPTIONS = 'DENY'

    CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
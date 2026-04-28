
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - local fallback
    def load_dotenv(*args, **kwargs):
        return False


def _env_as_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _csv_env(name, default):
    """Lê uma variável de ambiente como lista separada por vírgula."""
    raw = os.environ.get(name, '')
    items = [x.strip() for x in raw.split(',') if x.strip()]
    return items or list(default)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega .env só em dev/local. Em produção (Coolify), env vars vêm do painel
# e o .env nem chega na imagem (está no .dockerignore). Mantemos a chamada
# para que devs locais não precisem exportar manualmente.
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

RUNNING_TESTS = "test" in sys.argv
USE_SQLITE = os.environ.get('USE_SQLITE') == 'True' or RUNNING_TESTS

# --- Configurações de Login ---
# Para onde ir depois de logar? (Para a raiz /)
LOGIN_REDIRECT_URL = '/'

# Para onde ir depois de deslogar? (Para a tela de login de novo)
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Qual a URL de login?
LOGIN_URL = '/accounts/login/'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_as_bool('DEBUG', False)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG or RUNNING_TESTS:
        SECRET_KEY = 'doc-dev-secret-key-NOT-FOR-PRODUCTION'
    else:
        raise RuntimeError(
            "SECRET_KEY não definida. Configure a variável de ambiente "
            "SECRET_KEY no painel do Coolify (gere com "
            "`python -c \"from django.core.management.utils import "
            "get_random_secret_key; print(get_random_secret_key())\"`)."
        )

ALLOWED_HOSTS = _csv_env('ALLOWED_HOSTS', [
    "localhost",
    "127.0.0.1",
    "192.168.0.31",
    "doc.mdr.local",
])
# Hosts internos da rede Docker do Coolify — sempre incluídos para que o
# processos-worker (que chama http://web:8000/...) não bata em DisallowedHost.
# Esses nomes só resolvem dentro da rede do compose, não são acessíveis externamente.
for _internal_host in ('web', 'processos-worker'):
    if _internal_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_internal_host)

CSRF_TRUSTED_ORIGINS = _csv_env('CSRF_TRUSTED_ORIGINS', [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.0.31:8000",
    "http://doc.mdr.local",
])

# --- Proxy reverso (Traefik no Coolify) ---
# Liga quando o Django está atrás de um proxy que termina TLS.
# Sem isso, request.is_secure() = False, cookies seguros não funcionam,
# e Django gera URLs http:// em ambiente https://.
SECURE_PROXY = _env_as_bool('DJANGO_SECURE_PROXY', False)
if SECURE_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Hardening adicional (P3) ---
# Ligar SOMENTE depois de validar que tudo passa por HTTPS no Coolify.
# HSTS é "via única" — começa baixo (3600 = 1h) e sobe gradualmente.
SECURE_HARDENING = _env_as_bool('DJANGO_HARDENING', False)
if SECURE_HARDENING and not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS') or 3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_as_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS', False)
    SECURE_HSTS_PRELOAD = _env_as_bool('DJANGO_HSTS_PRELOAD', False)
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_yasg',
    'calculadora',
    'docgen',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


if USE_SQLITE or not os.environ.get('DB_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST'),
            'PORT': os.environ.get('DB_PORT'),
        }
    }

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

if RUNNING_TESTS:
    STORAGES['staticfiles']['BACKEND'] = 'django.contrib.staticfiles.storage.StaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- CONFIGURAÇÕES DE TIMEOUT DA SESSÃO ---
# Opção A (escolhida): janela de 30 min com sliding expiration.
# A cada request o cookie é renovado por mais 30 min — o usuário só é
# deslogado por inatividade. EXPIRE_AT_BROWSER_CLOSE precisa ser False,
# senão o cookie vira "session cookie" e o COOKIE_AGE é ignorado.
SESSION_COOKIE_AGE = 1800  # 30 minutos
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Backend de email: SMTP só faz sentido se houver host configurado.
# Em dev/local sem SMTP, mostramos no console. Em prod sem SMTP, dummy
# (engole sem erro) para não travar reset-de-senha em background.
_default_email_backend = (
    'django.core.mail.backends.smtp.EmailBackend'
    if os.environ.get('EMAIL_HOST')
    else ('django.core.mail.backends.console.EmailBackend' if DEBUG
          else 'django.core.mail.backends.dummy.EmailBackend')
)
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', _default_email_backend)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT') or 25)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_as_bool('EMAIL_USE_TLS', False)
EMAIL_USE_SSL = _env_as_bool('EMAIL_USE_SSL', False)
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT') or 30)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@doc.local')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

PROCESSOS_WORKER_TOKEN = os.environ.get('PROCESSOS_WORKER_TOKEN', 'processos-worker-dev-token')
PROCESSOS_WORKER_POLL_SECONDS = int(os.environ.get('PROCESSOS_WORKER_POLL_SECONDS') or 15)
PROCESSOS_WORKER_HEADLESS = _env_as_bool('PROCESSOS_WORKER_HEADLESS', True)
PROCESSOS_WORKER_BROWSER_PROFILE = os.environ.get(
    'PROCESSOS_WORKER_BROWSER_PROFILE',
    str(BASE_DIR / '.processos-browser-profile'),
)
PROCESSOS_WORKER_API_BASE_URL = os.environ.get('PROCESSOS_WORKER_API_BASE_URL', 'http://web:8000')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # --- NOVO: LIMITAÇÃO DE TAXA (Throttling) ---
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle', # Para não logados
        'rest_framework.throttling.UserRateThrottle'  # Para logados
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10/minute',   # Desconhecidos: max 10 req/min
        'user': '100/minute',  # Usuários logados: max 100 req/min
        'doc_gen': '20/minute', # Específico para gerar documentos (pesado)
    }
}
_framework.throttling.AnonRateThrottle', # Para não logados
        'rest_framework.throttling.UserRateThrottle'  # Para logados
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10/minute',   # Desconhecidos: max 10 req/min
        'user': '100/minute',  # Usuários logados: max 100 req/min
        'doc_gen': '20/minute', # Específico para gerar documentos (pesado)
    }
}


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

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
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

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'doc-dev-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG') == 'True'

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.31", "doc.mdr.local", "doc.mdradvocacia.com", "doc-lab.mdradvocacia.com"]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000", 
    "http://127.0.0.1:8000", 
    "http://192.168.0.31:8000",
    "http://doc.mdr.local",
    "https://doc.mdradvocacia.com",
    "https://doc-lab.mdradvocacia.com"
]
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

# 1. Tempo de vida da sessão em segundos
# 1800 segundos = 30 minutos
# 3600 segundos = 1 hora
SESSION_COOKIE_AGE = 1800  

# 2. Timeout por Inatividade (Sliding Expiration)
# Se True: O tempo reseta a cada clique/página carregada (ex: banco).
# Se False: O tempo é absoluto e desloga mesmo se estiver usando.
SESSION_SAVE_EVERY_REQUEST = True

# 3. Segurança Extra: Fechar navegador encerra sessão?
# Se True: Se o usuário fechar o Chrome/Edge, ele é deslogado na hora.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
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
PROCESSOS_WORKER_HEADLESS = _env_as_bool('PROCESSOS_WORKER_HEADLESS', False)
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


import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

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
SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG') == 'True'

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.0.31", "doc.mdr.local", "https://doc.mdradvocacia.com"]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000", 
    "http://127.0.0.1:8000", 
    "http://192.168.0.31:8000",
    "http://doc.mdr.local",
    "https://doc.mdradvocacia.com"
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
# Compressão e cache para arquivos estáticos
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

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


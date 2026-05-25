from datetime import timedelta
from pathlib import Path

from rest_framework.settings import api_settings

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-0@%6ofi@er%=@4k25%lscf)w&isq*1%$sp4hhb@^4i9$#%b+7e"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
    "*",
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # third-party
    "rest_framework",
    "drf_yasg",
    "corsheaders",
    # custom apps
    "users",
    "auth_tokens",
    "pokerlogs",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # cors middleware must be placed before CommonMiddleware
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pokerlandapi.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "pokerlandapi.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Rest Framework
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.AcceptHeaderVersioning",
    "DEFAULT_PAGINATION_CLASS": "utils.paginations.ApiPageNumberPagination",
    "DEFAULT_AUTHENTICATION_CLASS": [
        "rest_framework.authentication.SessionAuthentication",
        "auth_tokens.auth.OptionalTokenAuthentication",
    ],
    "DATETIME_FORMAT": "%Y-%m-%d %H:%M:%S",
    "DATE_FORMAT": "%Y-%m-%d",
}

SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "api-key": {"type": "apiKey", "name": "api-key", "in": "header"},
        # "app-version": {"type": "apiKey", "name": "app-version", "in": "header"},
        "Token": {"type": "apiKey", "name": "TOKEN", "in": "header"},
    },
    "USE_SESSION_AUTH": False,
    "TRY_IT_OUT_ENABLED": True,
    "DEFAULT_PAGINATOR_INSPECTORS": [
        "utils.custom_swaggers.paginations.CustomDjangoRestResponsePagination",
    ],
}


# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_TOKEN_SETTING = {
    # Since the primary users are app users, the token validity period has been set to a relatively long 30 days.
    "TOKEN_TTL": timedelta(days=30),
    "USER_SERIALIZER": None,
    "TOKEN_LIMIT_PER_USER": None,
    "AUTO_REFRESH": True,
    # The token expiration time is extended on a daily basis.
    "MIN_REFRESH_INTERVAL_SECOND": 60 * 60 * 24,
    "AUTH_HEADER_PREFIX": "TOKEN",
    "EXPIRY_DATETIME_FORMAT": api_settings.DATETIME_FORMAT,
}

DEFAULT_PAGE_SIZE = 50
EMAIL_VERIFICATION_CODE_EXPIRY_MINUTES = 3
USE_IN_LOCAL = True

ALLOWED_IP_ADDRESSES = [
    "*",
]

ENV = "local"
ALLOWED_VERSIONS = [
    "*",
]

AUTH_USER_MODEL = "users.User"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "postgres",
        "PASSWORD": "Example1!",
        "HOST": "localhost",
        "PORT": 5434,
    }
}

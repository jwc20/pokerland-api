import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Locally, variables come from .env (see .env.example). On Lambda, .env is not
# packaged: Zappa sets DJANGO_ENV from zappa_settings.json and the rest from the
# stage's remote_env file uploaded by scripts/deploy.py.
load_dotenv(BASE_DIR / ".env")


def env_list(name):
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# local | dev | prod
DJANGO_ENV = os.environ["DJANGO_ENV"]

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = DJANGO_ENV == "local"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    # Allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    # dj-rest-auth
    "dj_rest_auth",
    "dj_rest_auth.registration",
    "corsheaders",
    # Local
    "users",
    "tracker",
    "hands",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]


ROOT_URLCONF = "pokerlandapi.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")

CORS_ALLOW_CREDENTIALS = True  # Required for cookies


SITE_ID = 1

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "pokerlandapi.authentication.JWTCookieAuthentication",
    ],
    # Endpoints need a signed-in user unless they opt out with AllowAny, as the
    # dj-rest-auth login, registration and token views do.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# OpenAPI schema, served at /api/schema/ outside prod. pokerland-client generates
# its typed API client from it with swagger-typescript-api (npm run generate:api).
SPECTACULAR_SETTINGS = {
    "TITLE": "Pokerland API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Separate request and response components, so read-only fields such as
    # `pk` are not required in the client's request types.
    "COMPONENT_SPLIT_REQUEST": True,
    # Tag each operation with the path segment after /api/ (auth, ...). The
    # client groups its generated API classes by that tag.
    "SCHEMA_PATH_PREFIX": r"/api",
    "ENUM_NAME_OVERRIDES": {
        "HandEventTypeEnum": "hands.serializers.EVENT_TYPES",
        "HandTagGroupEnum": "hands.filters.TAG_GROUPS",
    },
}


REST_AUTH = {
    "USE_JWT": True,
    "JWT_AUTH_COOKIE": "access-token",
    "JWT_AUTH_REFRESH_COOKIE": "refresh-token",
    "JWT_AUTH_HTTPONLY": True,
    "JWT_AUTH_SECURE": not DEBUG,  # HTTPS-only cookies outside local
    "JWT_AUTH_SAMESITE": "Lax",
    "JWT_AUTH_RETURN_EXPIRATION": True,
    "SESSION_LOGIN": False,
}

# Tracker uploads (see pokerland-trackers/protocol/PROTOCOL.md). Chunks are
# gzipped hand-history bytes; the compressed limit keeps a request within
# Lambda's 6 MB payload once API Gateway has base64-encoded the body.
TRACKER = {
    "MIN_CLIENT_VERSION": os.environ.get("TRACKER_MIN_CLIENT_VERSION", "0.1.0"),
    "MAX_CHUNK_BYTES": 4 * 1024 * 1024,
    "MAX_UNCOMPRESSED_BYTES": 64 * 1024 * 1024,
    "POLL_INTERVAL_SECONDS": 2,
    "FLUSH_INTERVAL_SECONDS": 10,
    "FLUSH_BYTES": 256 * 1024,
    "MAX_READ_BYTES": 1024 * 1024,
    # Raw chunks go to this S3 bucket; empty means a local directory (dev only:
    # the Lambda filesystem is read-only).
    "RAW_BUCKET": os.environ.get("TRACKER_RAW_BUCKET", ""),
    "RAW_LOCAL_DIR": BASE_DIR / "var",
    # A chunk unparsed for this long is picked up by tasks.sweep_stale_streams.
    "STALE_CHUNK_SECONDS": 300,
}

# Chunk uploads are read as one body; Django's default (2.5 MB) would reject them.
DATA_UPLOAD_MAX_MEMORY_SIZE = TRACKER["MAX_CHUNK_BYTES"] + 1024

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# Allauth configuration: sign up with a username, an optional email and a
# password; log in with the username. (Fields marked * are required.)
ACCOUNT_SIGNUP_FIELDS = ["username*", "email", "password1*", "password2*"]
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_EMAIL_VERIFICATION = "none"

WSGI_APPLICATION = "pokerlandapi.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

# PostgreSQL when DB_NAME is set. SQLite is for local development only: the
# Lambda filesystem is read-only outside /tmp.
if os.environ.get("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", ""),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

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


LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

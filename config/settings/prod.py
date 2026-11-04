from decouple import Csv, config

from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Database: SQLite now. When your cPanel MySQL database exists, set DB_ENGINE=mysql in .env (see Part 5).
if config("DB_ENGINE", default="sqlite") == "mysql":
    try:
        import pymysql
        pymysql.version_info = (1, 4, 6, "final", 0)   # lets Django accept PyMySQL in place of mysqlclient
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": config("DB_NAME"), "USER": config("DB_USER"), "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"), "PORT": config("DB_PORT", default="3306"),
        "OPTIONS": {"charset": "utf8mb4"}, "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# Static files: collected into staticfiles/ and served by WhiteNoise, so they work with DEBUG off
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 300

# Security
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = config("HSTS_SECONDS", default=0, cast=int)   # raise this once HTTPS has been working for a day
SECURE_REFERRER_POLICY = "same-origin"
if config("TRUST_PROXY_HTTPS", default=False, cast=bool):            # only if a login or CSRF problem needs it (see troubleshooting)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Email (password reset): falls back to the console if EMAIL_HOST is empty, so the site still starts
EMAIL_HOST = config("EMAIL_HOST", default="")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = config("EMAIL_PORT", default=465, cast=int)
    EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=True, cast=bool)
    EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
    EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
    SERVER_EMAIL = DEFAULT_FROM_EMAIL
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Rate-limit counters must be shared between server processes. Files work on shared hosting.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": BASE_DIR / "cache"}}

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
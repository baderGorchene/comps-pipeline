"""Django settings for the local shortlist app. Runs on this machine only; no database."""

import importlib.util
import os
import secrets
from pathlib import Path

_has_whitenoise = importlib.util.find_spec("whitenoise") is not None

BASE_DIR = Path(__file__).resolve().parent.parent

# Local & deployed settings
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(50))
DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1")
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [
    "https://*.hf.space",
    "https://*.huggingface.co",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

INSTALLED_APPS = ["django.contrib.staticfiles", "web"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if _has_whitenoise else []),
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "web.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
WSGI_APPLICATION = "web.wsgi.application"
DATABASES: dict = {}

STATIC_URL = "static/"
USE_TZ = False
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Paths used by the views (relative to the repo root, where run.bat starts the server).
CONFIG_FILE = BASE_DIR / "config" / "settings.yaml"
SAMPLE_CSV = BASE_DIR / "data" / "samples" / "mls_sample.csv"
SAMPLE_SUBJECT = BASE_DIR / "data" / "samples" / "subject.yaml"
INPUT_SUBJECT = BASE_DIR / "data" / "input" / "subject.yaml"

"""
config.py
Centralised configuration for the Automated Email Sender app.
All secrets are pulled from environment variables (.env file) - never hard-coded.
"""

import os
from dotenv import load_dotenv

# Load variables from .env into the environment
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ---- Flask ----
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"

    # ---- Database ----
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or \
        f"sqlite:///{os.path.join(BASE_DIR, 'email_sender.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- Gmail SMTP ----
    SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "")
    APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))

    # ---- File uploads ----
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    ATTACHMENT_FOLDER = os.path.join(BASE_DIR, "attachments")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    ALLOWED_ATTACHMENT_EXTENSIONS = {
        "pdf", "doc", "docx", "xls", "xlsx", "png", "jpg", "jpeg",
        "gif", "txt", "csv", "zip", "ppt", "pptx",
    }
    ALLOWED_CSV_EXTENSIONS = {"csv"}

    # ---- Scheduler ----
    SCHEDULER_API_ENABLED = True

    # ---- Pagination ----
    LOGS_PER_PAGE = 15


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}

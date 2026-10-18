# app/observability/logging.py
import datetime
import hashlib
import json
import logging
import re
from typing import Any
from .tracing import get_current_trace_id, get_current_span_id

# Regex scrubbing patterns
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
BEARER_REGEX = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
PASSWORD_REGEX = re.compile(r'("password"|"secret"|"token"|"api_key")\s*:\s*"[^"]+"', re.IGNORECASE)
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
UPI_REGEX = re.compile(r"\b[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}\b")


def hash_email(email: str) -> str:
    """Returns SHA-256 hash prefix for privacy-safe email logging."""
    return f"email_hash:{hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest()[:16]}"


def redact_text(text: str) -> str:
    """Scrub sensitive card, token, password, and credential details from text."""
    if not isinstance(text, str):
        return text

    # Redact Bearer tokens
    redacted = BEARER_REGEX.sub("Bearer [REDACTED_TOKEN]", text)

    # Redact password/token JSON fields
    redacted = PASSWORD_REGEX.sub(r'\1: "[REDACTED]"', redacted)

    # Redact potential credit/debit card numbers (13-16 digits)
    def _scrub_card(match):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 16:
            return "[REDACTED_CARD]"
        return match.group(0)

    redacted = CARD_REGEX.sub(_scrub_card, redacted)

    return redacted


def redact_data(obj: Any) -> Any:
    """Recursively scrub sensitive keys and text inside dicts or lists."""
    sensitive_keys = {
        "password",
        "password_hash",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "card_number",
        "cvv",
        "upi_id",
        "bank_account",
        "razorpay_signature",
    }

    if isinstance(obj, dict):
        scrubbed = {}
        for k, v in obj.items():
            if str(k).lower() in sensitive_keys:
                scrubbed[k] = "[REDACTED]"
            elif str(k).lower() == "email" and isinstance(v, str):
                scrubbed[k] = hash_email(v)
            else:
                scrubbed[k] = redact_data(v)
        return scrubbed
    elif isinstance(obj, list):
        return [redact_data(item) for item in obj]
    elif isinstance(obj, str):
        return redact_text(obj)
    return obj


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with scrubbed PII and OpenTelemetry trace metadata."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()

        message = record.getMessage()
        redacted_msg = redact_text(message)

        log_entry = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redacted_msg,
            "trace_id": trace_id if trace_id else None,
            "span_id": span_id if span_id else None,
        }

        # Include structured extra fields if provided
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_entry["extra"] = redact_data(record.extra)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(level: int = logging.INFO):
    """Configures root logger with structured JSON formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Returns a logger instance with structured capabilities."""
    return logging.getLogger(name)

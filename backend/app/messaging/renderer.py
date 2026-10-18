# app/messaging/renderer.py
import datetime
import re
from typing import Any
from icalendar import Calendar, Event
import jinja2

# Section 9.5 template catalog definitions: (Subject, HTML template, Text template, is_marketing)
TEMPLATES: dict[str, dict[str, Any]] = {
    "VERIFY_EMAIL": {
        "subject": "Verify your GymPro account",
        "is_marketing": False,
        "html": """<p>Welcome to GymPro, {{ name | default('Athlete') }}!</p>
<p>Please click the link below to verify your email address (valid for 24 hours):</p>
<p><a href="{{ link }}">Verify My Email</a></p>
<p>If you did not sign up for GymPro, please ignore this email.</p>""",
        "text": """Welcome to GymPro, {{ name | default('Athlete') }}!

Please verify your email address using this link (valid for 24 hours):
{{ link }}

If you did not sign up for GymPro, please ignore this email.""",
    },
    "RESET_PASSWORD": {
        "subject": "Reset your GymPro password",
        "is_marketing": False,
        "html": """<p>Hello,</p>
<p>We received a request to reset your GymPro password. Click the link below (valid for 30 minutes):</p>
<p><a href="{{ link }}">Reset Password</a></p>
<p>If you did not request a password reset, no action is needed.</p>""",
        "text": """Hello,

We received a request to reset your GymPro password. Use this link (valid for 30 minutes):
{{ link }}

If you did not request a password reset, no action is needed.""",
    },
    "PASSWORD_CHANGED": {
        "subject": "Your GymPro password has been changed",
        "is_marketing": False,
        "html": """<p>Security Notice: Your GymPro password was successfully changed.</p>
<p>If this was not you, please contact support or an administrator immediately.</p>""",
        "text": """Security Notice: Your GymPro password was successfully changed.

If this was not you, please contact support or an administrator immediately.""",
    },
    "ALREADY_REGISTERED": {
        "subject": "GymPro registration notice",
        "is_marketing": False,
        "html": """<p>Hello,</p>
<p>Someone attempted to register a GymPro account using your email address ({{ email }}).</p>
<p>If you already have an account, you can log in or request a password reset.</p>""",
        "text": """Hello,

Someone attempted to register a GymPro account using your email address ({{ email }}).
If you already have an account, you can log in or request a password reset.""",
    },
    "CLASS_CONFIRMED": {
        "subject": "Booking Confirmed: {{ class_name }}",
        "is_marketing": False,
        "html": """<p>Great news! Your spot in <strong>{{ class_name }}</strong> is confirmed.</p>
<p>Time: {{ class_time }}</p>
<p>Trainer: {{ trainer_name }}</p>""",
        "text": """Great news! Your spot in {{ class_name }} is confirmed.

Time: {{ class_time }}
Trainer: {{ trainer_name }}""",
    },
    "BOOKING_DETAILS": {
        "subject": "Booking Details: {{ class_name }}",
        "is_marketing": False,
        "html": """<p>Here are your booking details for <strong>{{ class_name }}</strong>:</p>
<ul>
  <li>Time: {{ class_time }}</li>
  <li>Trainer: {{ trainer_name }}</li>
  <li>Location: {{ room | default('Main Studio') }}</li>
</ul>""",
        "text": """Here are your booking details for {{ class_name }}:
- Time: {{ class_time }}
- Trainer: {{ trainer_name }}
- Location: {{ room | default('Main Studio') }}""",
    },
    "WAITLIST_PROMOTED": {
        "subject": "You're off the waitlist: {{ class_name }}",
        "is_marketing": False,
        "html": """<p>A spot opened up! You have been promoted off the waitlist for <strong>{{ class_name }}</strong>.</p>
<p>Time: {{ class_time }}</p>
<p>Your booking is now confirmed.</p>""",
        "text": """A spot opened up! You have been promoted off the waitlist for {{ class_name }}.

Time: {{ class_time }}
Your booking is now confirmed.""",
    },
    "CLASS_REMINDER": {
        "subject": "Reminder: {{ class_name }} is coming up",
        "is_marketing": False,
        "html": """<p>Reminder: You have an upcoming class: <strong>{{ class_name }}</strong>.</p>
<p>Time: {{ class_time }}</p>
<p>Please arrive 10 minutes prior to start time.</p>""",
        "text": """Reminder: You have an upcoming class: {{ class_name }}.

Time: {{ class_time }}
Please arrive 10 minutes prior to start time.""",
    },
    "CLASS_CANCELLED": {
        "subject": "Class Cancelled: {{ class_name }}",
        "is_marketing": False,
        "html": """<p>Notice: <strong>{{ class_name }}</strong> scheduled for {{ class_time }} has been cancelled.</p>
<p>Any credits or trial sessions used have been fully refunded to your account.</p>""",
        "text": """Notice: {{ class_name }} scheduled for {{ class_time }} has been cancelled.

Any credits or trial sessions used have been fully refunded to your account.""",
    },
    "PLAN_CHANGED": {
        "subject": "Your GymPro Membership Plan has been updated",
        "is_marketing": False,
        "html": """<p>Your membership plan has been updated to <strong>{{ new_plan }}</strong>.</p>
<p>Effective Date: {{ effective_date }}</p>""",
        "text": """Your membership plan has been updated to {{ new_plan }}.

Effective Date: {{ effective_date }}""",
    },
    "PAYMENT_RECEIPT": {
        "subject": "Payment Receipt: GymPro {{ plan }}",
        "is_marketing": False,
        "html": """<p>Thank you for your payment!</p>
<p>Plan: {{ plan }}</p>
<p>Amount: {{ currency }} {{ amount }}</p>
<p>Date: {{ payment_date }}</p>
<p>Reference: {{ payment_ref }}</p>""",
        "text": """Thank you for your payment!

Plan: {{ plan }}
Amount: {{ currency }} {{ amount }}
Date: {{ payment_date }}
Reference: {{ payment_ref }}""",
    },
    "PAYMENT_NEEDS_REVIEW": {
        "subject": "[Admin Alert] Payment Review Required: {{ payment_id }}",
        "is_marketing": False,
        "html": """<p>Payment {{ payment_id }} requires manual review by an administrator.</p>
<p>Reason: {{ reason }}</p>
<p>Amount: {{ currency }} {{ amount }}</p>""",
        "text": """Payment {{ payment_id }} requires manual review by an administrator.

Reason: {{ reason }}
Amount: {{ currency }} {{ amount }}""",
    },
    "ISSUE_RECEIVED": {
        "subject": "We received your report (Ref: {{ issue_id }})",
        "is_marketing": False,
        "html": """<p>Thank you for reaching out. We received your report (Reference: {{ issue_id }}).</p>
<p>Our safety and management team will review it promptly.</p>""",
        "text": """Thank you for reaching out. We received your report (Reference: {{ issue_id }}).

Our safety and management team will review it promptly.""",
    },
    "ISSUE_ADMIN_ALERT": {
        "subject": "[Urgent Alert] Safety Issue Reported: {{ severity }}",
        "is_marketing": False,
        "html": """<p><strong>Safety Alert</strong></p>
<p>Severity: {{ severity }}</p>
<p>Category: {{ category }}</p>
<p>Class: {{ class_label | default('N/A') }}</p>
<p><a href="{{ admin_link }}">Review in Admin Dashboard</a></p>
<p><em>(Reporter identity is strictly withheld for privacy.)</em></p>""",
        "text": """Safety Alert

Severity: {{ severity }}
Category: {{ category }}
Class: {{ class_label | default('N/A') }}
Review Link: {{ admin_link }}

(Reporter identity is strictly withheld for privacy.)""",
    },
    "TRAINER_DECISION": {
        "subject": "GymPro Trainer Application Update",
        "is_marketing": False,
        "html": """<p>Your trainer application has been updated.</p>
<p>Status: <strong>{{ status }}</strong></p>
<p>{{ message }}</p>""",
        "text": """Your trainer application has been updated.

Status: {{ status }}
{{ message }}""",
    },
    "ADMIN_CODE": {
        "subject": "GymPro Admin Sign-Up Verification Code",
        "is_marketing": False,
        "html": """<p>An administrator account was requested by {{ applicant_email }}.</p>
<p>One-Time Code (valid for 30 minutes):</p>
<h2 style="letter-spacing: 4px;">{{ code }}</h2>
<p>If this was unauthorized, you can reject it: <a href="{{ reject_link }}">Reject Request</a></p>""",
        "text": """An administrator account was requested by {{ applicant_email }}.

One-Time Code (valid for 30 minutes):
{{ code }}

Reject link: {{ reject_link }}""",
    },
    "NEW_ADMIN_ADDED": {
        "subject": "[Security Notice] New Administrator Activated",
        "is_marketing": False,
        "html": """<p>Security Notice: A new administrator account was activated.</p>
<p>Name: {{ admin_name }}</p>
<p>Time: {{ activated_at }}</p>
<p>A 24-hour cooling-off period is currently active.</p>
<p><a href="{{ suspend_link }}">Suspend Administrator</a></p>""",
        "text": """Security Notice: A new administrator account was activated.

Name: {{ admin_name }}
Time: {{ activated_at }}
A 24-hour cooling-off period is currently active.

Suspend Link: {{ suspend_link }}""",
    },
    "TRAINER_REQUESTS_DIGEST": {
        "subject": "Trainer Applications Digest ({{ pending_count }} pending)",
        "is_marketing": False,
        "html": """<p>There are currently {{ pending_count }} pending trainer applications awaiting review.</p>
<p><a href="{{ link }}">Review Applications</a></p>""",
        "text": """There are currently {{ pending_count }} pending trainer applications awaiting review.

Review link: {{ link }}""",
    },
    "DAILY_DIGEST": {
        "subject": "GymPro Daily Admin Digest: {{ digest_date }}",
        "is_marketing": True,
        "html": """<h2>Daily Admin Digest - {{ digest_date }}</h2>
<div>{{ summary }}</div>""",
        "text": """Daily Admin Digest - {{ digest_date }}

{{ summary }}""",
    },
    "WEEKLY_SUMMARY": {
        "subject": "Your GymPro Weekly Fitness Summary",
        "is_marketing": True,
        "html": """<h2>Your Weekly Fitness Summary</h2>
<p>{{ summary_stats }}</p>
<p><small><a href="{{ unsubscribe_link | default('#') }}">Unsubscribe from weekly summaries</a></small></p>""",
        "text": """Your Weekly Fitness Summary

{{ summary_stats }}

Unsubscribe: {{ unsubscribe_link | default('#') }}""",
    },
    "BROADCAST": {
        "subject": "{{ broadcast_title }}",
        "is_marketing": True,
        "html": """<div>{{ content }}</div>
<hr />
<p><small>To unsubscribe from marketing broadcasts, <a href="{{ unsubscribe_link | default('#') }}">click here</a>.</small></p>""",
        "text": """{{ content }}

To unsubscribe from marketing broadcasts: {{ unsubscribe_link | default('#') }}""",
    },
}

# Auto-escaping Jinja2 environment (Section 9.4: prevents HTML/XSS injection)
_jinja_env = jinja2.Environment(
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    undefined=jinja2.ChainableUndefined,
)


def render(template_name: str, params: dict[str, Any], locale: str = "en") -> tuple[str, str, str]:
    """
    Renders an email template returning (subject, html_part, text_part).
    Header safety: Subject is strictly template-driven to prevent header injection.
    """
    tpl_info = TEMPLATES.get(template_name)
    if not tpl_info:
        raise ValueError(f"Unknown email template: {template_name}")

    # Render subject using text-safe jinja string
    subj_tmpl = jinja2.Template(tpl_info["subject"], autoescape=False)
    # Sanitize newlines from subject to ensure header injection safety
    subject = re.sub(r"[\r\n]+", " ", subj_tmpl.render(**params)).strip()

    html_tmpl = _jinja_env.from_string(tpl_info["html"])
    html_part = html_tmpl.render(**params)

    text_tmpl = jinja2.Template(tpl_info["text"], autoescape=False)
    text_part = text_tmpl.render(**params)

    return subject, html_part, text_part


def is_marketing_template(template_name: str) -> bool:
    """Returns whether the template is categorized as marketing and subject to unsubscribes."""
    tpl = TEMPLATES.get(template_name)
    return bool(tpl and tpl.get("is_marketing", False))


def make_ics(params: dict[str, Any]) -> bytes:
    """Creates a standard iCalendar (.ics) invite byte payload for class bookings."""
    cal = Calendar()
    cal.add("prodid", "-//GymPro AI Booking//EN")
    cal.add("version", "2.0")

    event = Event()
    event.add("summary", params.get("class_name", "GymPro Class"))
    event.add("description", f"Trainer: {params.get('trainer_name', 'GymPro Trainer')}")

    dt_start = params.get("start_time")
    dt_end = params.get("end_time")
    now = datetime.datetime.now(datetime.timezone.utc)

    if isinstance(dt_start, str):
        try:
            dt_start = datetime.datetime.fromisoformat(dt_start)
        except Exception:
            dt_start = now
    if not isinstance(dt_start, datetime.datetime):
        dt_start = now

    if isinstance(dt_end, str):
        try:
            dt_end = datetime.datetime.fromisoformat(dt_end)
        except Exception:
            dt_end = dt_start + datetime.timedelta(hours=1)
    if not isinstance(dt_end, datetime.datetime):
        dt_end = dt_start + datetime.timedelta(hours=1)

    event.add("dtstart", dt_start)
    event.add("dtend", dt_end)
    event.add("dtstamp", now)
    event.add("uid", f"{params.get('booking_id', 'booking')}_{int(now.timestamp())}@gympro.local")

    cal.add_component(event)
    return cal.to_ical()

from fastmcp import FastMCP
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape
from config import settings
import smtplib
import ssl
import logging
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Notification Send Tool")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_RECIPIENTS = 50

# notification_type -> (subject template, required data fields, field labels for the body)
NOTIFICATION_TEMPLATES = {
    "task_created": {
        "subject": "New task created: {task_name}",
        "intro": "A new task has been created.",
        "required": ["task_name"],
        "fields": {
            "task_name": "Task name",
            "task_status": "Status",
            "start_date": "Start date",
            "end_date": "End date",
            "task_group_id": "Task group",
            "estimated_amount": "Estimated amount",
        },
    },
    "material_created": {
        "subject": "New material created: {material_name}",
        "intro": "A new material has been added to the material library.",
        "required": ["material_name"],
        "fields": {
            "material_name": "Material name",
            "specification": "Specification",
            "subcategory": "Subcategory",
            "brand_name": "Brand",
            "typeOfMaterial": "Type",
        },
    },
    # ShiftGuard: tell a manager / buddy that an employee's wellbeing risk is elevated
    "risk_alert": {
        "subject": "Wellbeing check-in suggested for {employee_name}",
        "intro": "ShiftGuard flagged an elevated wellbeing risk. Please arrange a supportive check-in.",
        "required": ["employee_name"],
        "fields": {
            "employee_name": "Employee",
            "risk_band": "Risk band",
            "risk_score": "Risk score (0-100)",
            "snapshot_date": "Date",
            "key_factors": "Main contributing factors",
            "recommended_action": "Recommended action",
        },
    },
    # ShiftGuard: remind an employee to answer their wellbeing check-in
    "checkin_reminder": {
        "subject": "A quick wellbeing check-in for you, {employee_name}",
        "intro": "You have a new wellbeing check-in waiting in the ShiftGuard app. It takes less than a minute.",
        "required": ["employee_name"],
        "fields": {
            "employee_name": "Name",
            "question_text": "Question",
            "expires_at": "Open until",
        },
    },
    "general": {
        "subject": "{subject}",
        "intro": "",
        "required": ["subject", "message"],
        "fields": {},
    },
}


def _normalize_recipients(value) -> list[str]:
    """Accept a single email string or a list of emails; return a de-duplicated, validated list."""
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        raise ValueError("'to' must be an email string or a list of email strings.")

    recipients = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        email = item.strip()
        if not EMAIL_PATTERN.match(email):
            raise ValueError(f"Invalid email address: {email}")
        if email.lower() not in (r.lower() for r in recipients):
            recipients.append(email)

    if not recipients:
        raise ValueError("At least one recipient email is required in 'to'.")
    if len(recipients) > MAX_RECIPIENTS:
        raise ValueError(f"Too many recipients ({len(recipients)}). Maximum is {MAX_RECIPIENTS}.")
    return recipients


def build_notification_content(notification_type: str, data: dict, organization_name: str | None = None) -> tuple[str, str, str]:
    """Build (subject, plain text body, html body) from the notification template and data."""
    template = NOTIFICATION_TEMPLATES[notification_type]

    missing = [field for field in template["required"] if data.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing required data fields for '{notification_type}': {', '.join(missing)}")

    subject = template["subject"].format(**{k: data.get(k, "") for k in template["required"]})
    if organization_name:
        subject = f"[{organization_name}] {subject}"

    if notification_type == "general":
        message = str(data["message"])
        text_body = message
        html_body = f"<p>{escape(message).replace(chr(10), '<br>')}</p>"
    else:
        # Known fields first (with labels), then any extra fields passed in data.
        rows = [(label, data[key]) for key, label in template["fields"].items() if data.get(key) not in (None, "")]
        rows += [(key, value) for key, value in data.items() if key not in template["fields"] and value not in (None, "")]

        text_body = template["intro"] + "\n\n" + "\n".join(f"{label}: {value}" for label, value in rows)
        html_rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0'><b>{escape(str(label))}</b></td><td>{escape(str(value))}</td></tr>"
            for label, value in rows
        )
        html_body = f"<p>{escape(template['intro'])}</p><table>{html_rows}</table>"

    footer = "This is an automated notification."
    return subject, f"{text_body}\n\n--\n{footer}", f"<html><body>{html_body}<hr><small>{footer}</small></body></html>"


def send_email(recipients: list[str], subject: str, text_body: str, html_body: str) -> None:
    """Send a multipart (plain text + HTML) email through the configured SMTP server."""
    if not all([settings.SMTP_HOST, settings.SMTP_FROM_EMAIL]):
        raise ValueError("SMTP is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL (and SMTP_USERNAME/SMTP_PASSWORD if required).")

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if settings.SMTP_USE_SSL:
        # Implicit TLS (usually port 465)
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=settings.SMTP_TIMEOUT) as server:
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            server.send_message(message)
    else:
        # STARTTLS (usually port 587)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls(context=context)
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            server.send_message(message)


@mcp.tool()
def send_notification_email(input_data: str) -> str:
    """
    Tool to send a notification email to one or more recipients.
    Input should be a JSON string with the following fields:
    - to (str | list[str]): Recipient email address(es)
    - notification_type (str): One of 'risk_alert', 'checkin_reminder', 'general', 'task_created', 'material_created'
    - data (dict): Values for the notification:
        - risk_alert (to a manager or buddy): employee_name (required), risk_band, risk_score, snapshot_date,
          key_factors (plain-language text), recommended_action
        - checkin_reminder (to the employee): employee_name (required), question_text, expires_at
        - general: subject (required), message (required)
        - task_created: task_name (required), task_status, start_date, end_date, task_group_id, estimated_amount
        - material_created: material_name (required), specification, subcategory, brand_name, typeOfMaterial
    - organization_id (str, optional): The organization id the notification belongs to
    - organization_name (str, optional): Shown as a prefix in the email subject
    - user_id (str, optional): The user who triggered the notification
    Example: {"to": ["a@x.com"], "notification_type": "task_created", "data": {"task_name": "Foundation"}, "organization_id": "1", "user_id": "u1"}
    """
    try:
        # Parse the JSON input
        data = json.loads(input_data)
        if not isinstance(data, dict):
            return "Error: Input must be a JSON object."

        notification_type = data.get("notification_type")
        notification_data = data.get("data") or {}
        organization_id = data.get("organization_id")
        organization_name = data.get("organization_name")
        user_id = data.get("user_id")

        # Validate required fields
        if notification_type not in NOTIFICATION_TEMPLATES:
            return f"Error: 'notification_type' must be one of {list(NOTIFICATION_TEMPLATES)}."
        if not isinstance(notification_data, dict):
            return "Error: 'data' must be a JSON object."
        recipients = _normalize_recipients(data.get("to"))
        subject, text_body, html_body = build_notification_content(notification_type, notification_data, organization_name)

    except json.JSONDecodeError:
        return "Error: Invalid JSON input. Please provide a valid JSON string with notification details."
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error parsing input: {str(e)}"

    try:
        send_email(recipients, subject, text_body, html_body)
        logger.info(
            "Notification email sent. type=%s recipients=%d organization_id=%s user_id=%s",
            notification_type, len(recipients), organization_id, user_id,
        )
        return f"Notification email '{subject}' sent successfully to {', '.join(recipients)}."
    except ValueError as e:
        return f"Error: {str(e)}"
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed.")
        return "Error: SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD."
    except Exception as e:
        logger.error(f"Error sending notification email: {e}")
        return f"Error sending notification email: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")

from datetime import date
from email.message import EmailMessage
import os
import smtplib


def send_email(report):
    email_from = os.environ.get("EMAIL_FROM")
    email_to = os.environ.get("EMAIL_TO")
    email_password = os.environ.get("EMAIL_PASSWORD")

    missing = [
        name for name, value in {
            "EMAIL_FROM": email_from,
            "EMAIL_TO": email_to,
            "EMAIL_PASSWORD": email_password,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(f"Missing email environment variables: {', '.join(missing)}")

    today = date.today().isoformat()

    msg = EmailMessage()
    msg["Subject"] = f"Ornitho Daily Report - {today}"
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(report)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email_from, email_password)
        smtp.send_message(msg)
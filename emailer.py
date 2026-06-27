from datetime import date
from email.message import EmailMessage
import os
import smtplib

DEFAULT_EMAIL_TO = object()


def build_subject():
    today = date.today().isoformat()
    return f"Ornitho Daily Report - {today}"


def send_email(report, dry_run=False, email_to=DEFAULT_EMAIL_TO):
    subject = build_subject()
    print("Reached email step.")

    if dry_run:
        print("DRY_RUN enabled; email not sent.")
        print()
        print("Email subject:")
        print(subject)
        print()
        print("Email body:")
        print(report)
        return

    email_from = os.environ.get("EMAIL_FROM")
    if email_to is DEFAULT_EMAIL_TO:
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

    print("Sending email via Gmail SMTP.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(report)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email_from, email_password)
        smtp.send_message(msg)

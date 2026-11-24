"""Send a single SMTP test message to the configured sender's own inbox."""
from email_validator import EmailNotValidError, validate_email
import os
import smtplib

from .delivery import send_email


def main():
    sender = os.getenv("SMTP_FROM")
    if not os.getenv("SMTP_HOST") or not sender:
        raise SystemExit("Set SMTP_HOST and SMTP_FROM in secure runtime configuration.")
    if os.getenv("SMTP_USERNAME") and not os.getenv("SMTP_PASSWORD"):
        raise SystemExit("Set the SMTP credential in secure runtime configuration.")
    try:
        address = validate_email(sender, check_deliverability=False).normalized
        send_email(address, "Drivewell SMTP test. This message is sent only to the configured sender.")
    except (EmailNotValidError, OSError, ValueError, KeyError, smtplib.SMTPException) as error:
        raise SystemExit(f"SMTP test failed ({type(error).__name__}). Check the sender, credential, and network settings.") from None
    print("SMTP accepted the test message. Check the configured sender inbox for delivery.")


if __name__ == "__main__":
    main()

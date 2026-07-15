import os=
from flask_mail import Mail, Message


MAIL_CONFIG = {
    "MAIL_SERVER": os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
    "MAIL_PORT": int(os.environ.get("MAIL_PORT", 587)),
    "MAIL_USE_TLS": os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    "MAIL_USE_SSL": os.environ.get("MAIL_USE_SSL", "false").lower() == "true",
    "MAIL_USERNAME": os.environ.get("MAIL_USERNAME"),
    "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD"),
    "MAIL_DEFAULT_SENDER": "T English Club",
}

mail = Mail()


def send_email(to, subject, body):
    msg = Message(subject=subject, recipients=[to], body=body)
    mail.send(msg)

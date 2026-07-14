import os
from flask_mail import Mail, Message


MAIL_CONFIG = {
    "MAIL_SERVER": os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
    "MAIL_PORT": int(os.environ.get("MAIL_PORT", 587)),
    "MAIL_USE_TLS": os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    "MAIL_USE_SSL": os.environ.get("MAIL_USE_SSL", "false").lower() == "true",
    "MAIL_USERNAME": os.environ.get("MAIL_USERNAME"),
    "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD"),
    "MAIL_DEFAULT_SENDER": os.environ.get("MAIL_DEFAULT_SENDER", os.environ.get("MAIL_USERNAME")),
}

mail = Mail()


def send_email(to, subject, body):
    """
    Pengganti resend.Emails.send() sebelumnya / mail.send(msg) manual.
    Dipakai untuk semua pengiriman OTP / notifikasi email di seluruh aplikasi,
    sekarang lewat Flask-Mail (SMTP, library resmi Flask untuk kirim email).

    to      : alamat email tujuan (string)
    subject : judul email
    body    : isi email (plain text)
    """
    msg = Message(subject=subject, recipients=[to], body=body)
    mail.send(msg)

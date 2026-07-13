import os
import resend

# API key Resend diambil dari environment variable, JANGAN hardcode di sini.
# Set di server/hosting kamu: RESEND_API_KEY=re_xxxxxxxx
resend.api_key = os.environ.get("RESEND_API_KEY")

# Alamat pengirim default. Selama domain sendiri belum diverifikasi di Resend,
# ini WAJIB "onboarding@resend.dev" dan hanya akan sukses terkirim ke email
# yang terdaftar di akun Resend kamu sendiri (mode testing/sandbox Resend).
# Setelah domain diverifikasi, ganti env RESEND_FROM_EMAIL, misal:
# RESEND_FROM_EMAIL=noreply@domainkamu.com
DEFAULT_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")


def send_email(to, subject, body):
    """
    Pengganti mail.send(msg) dari Flask-Mail lama.
    Dipakai untuk semua pengiriman OTP / notifikasi email di seluruh aplikasi.

    to      : alamat email tujuan (string)
    subject : judul email
    body    : isi email (plain text)
    """
    resend.Emails.send({
        "from": DEFAULT_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": body,
    })
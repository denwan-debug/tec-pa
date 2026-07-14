from flask import Flask
from dotenv import load_dotenv
import os


load_dotenv()

import cloudinary  # TAMBAHAN: Import library cloudinary

from extensions import mail, MAIL_CONFIG  # Konfigurasi Flask-Mail (SMTP)

# Mengimpor semua blueprint (rute)
from routes.orangtua import orangtua_bp
from routes.admin import admin_bp
from routes.pengajar import pengajar_bp

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

# --- KONFIGURASI FLASK-MAIL (TAMBAHAN) ---
# Mengambil kredensial SMTP dari file .env (lihat extensions.py untuk daftar
# environment variable yang dipakai: MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, dst)
app.config.update(MAIL_CONFIG)
mail.init_app(app)

# --- KONFIGURASI CLOUDINARY (TAMBAHAN) ---
# Mengambil kredensial dari file .env
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

# --- DAFTARKAN SEMUA ROUTING (BLUEPRINT) ---
app.register_blueprint(orangtua_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(pengajar_bp)

if __name__ == '__main__':
    app.run(debug=True)
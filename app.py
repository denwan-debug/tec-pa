from flask import Flask
from dotenv import load_dotenv
import os

# load_dotenv() dipindah ke PALING ATAS, sebelum import extensions/routes.
# Ini penting karena extensions.py membaca RESEND_API_KEY saat modul itu
# di-import -- kalau .env belum ke-load duluan, API key-nya akan kosong (None).
load_dotenv()

import cloudinary  # TAMBAHAN: Import library cloudinary

# Mengimpor semua blueprint (rute)
from routes.orangtua import orangtua_bp
from routes.admin import admin_bp
from routes.pengajar import pengajar_bp

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

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
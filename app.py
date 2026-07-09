from flask import Flask
from dotenv import load_dotenv
import os
import cloudinary # TAMBAHAN: Import library cloudinary
from extensions import mail

# Mengimpor semua blueprint (rute)
from routes.orangtua import orangtua_bp
from routes.admin import admin_bp
from routes.pengajar import pengajar_bp

load_dotenv()

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

# --- KONFIGURASI CLOUDINARY (TAMBAHAN) ---
# Mengambil kredensial dari file .env
cloudinary.config( 
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.getenv('CLOUDINARY_API_KEY'), 
    api_secret = os.getenv('CLOUDINARY_API_SECRET'),
    secure = True
)

# --- KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')      
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')    
app.config['MAIL_DEFAULT_SENDER'] = ('TEC Parent Portal', 'dennisdg273@gmail.com')

# Inisialisasi email dengan aplikasi Flask kita
mail.init_app(app)

# --- DAFTARKAN SEMUA ROUTING (BLUEPRINT) ---
app.register_blueprint(orangtua_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(pengajar_bp)

if __name__ == '__main__':
    app.run(debug=True)
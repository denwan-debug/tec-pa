from flask import Flask
from dotenv import load_dotenv
import os
from extensions import mail

# Mengimpor semua blueprint (rute)
from routes.orangtua import orangtua_bp
from routes.admin import admin_bp
from routes.pengajar import pengajar_bp

load_dotenv()

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

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
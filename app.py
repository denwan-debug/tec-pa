from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

import cloudinary  

from extensions import mail, MAIL_CONFIG 

from routes.orangtua import orangtua_bp
from routes.admin import admin_bp
from routes.pengajar import pengajar_bp

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

app.config.update(MAIL_CONFIG)
mail.init_app(app)

cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

app.register_blueprint(orangtua_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(pengajar_bp)

if __name__ == '__main__':
    app.run(debug=True)
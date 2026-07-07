import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()  # membaca file .env di root project


def get_db_connection():
    """
    Membuka koneksi ke TiDB Cloud Serverless.
    Semua routes yang sudah ada (admin.py, orangtua.py, dst) TIDAK PERLU diubah,
    karena tetap memakai conn.cursor(dictionary=True) + cursor.execute(%s, ...)
    seperti sebelumnya dengan Laragon/MySQL.
    """
    return mysql.connector.connect(
        host=os.getenv("TIDB_HOST"),        # contoh: gateway01.ap-southeast-1.prod.aws.tidbcloud.com
        port=int(os.getenv("TIDB_PORT", 4000)),
        user=os.getenv("TIDB_USER"),         # PENTING: harus pakai prefix cluster, contoh: 3aBcDeFg.root
        password=os.getenv("TIDB_PASSWORD"),
        database=os.getenv("TIDB_DB_NAME", "tec_english"),
        use_pure=True,          # WAJIB di Windows: hindari bug C-extension "SSL_CTX_set_default_verify_paths failed"
        ssl_verify_cert=True,
        ssl_verify_identity=True,
        # TiDB Serverless memakai sertifikat Let's Encrypt (ISRG Root X1) yang umumnya
        # sudah dipercaya oleh CA store bawaan sistem/Python. Kalau masih error SSL
        # setelah use_pure=True, baru perlu unduh CA cert dari dashboard TiDB Cloud dan aktifkan:
        # ssl_ca=os.getenv("TIDB_SSL_CA"),
    )
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()  

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("TIDB_HOST"),        
        port=int(os.getenv("TIDB_PORT", 4000)),
        user=os.getenv("TIDB_USER"),         
        password=os.getenv("TIDB_PASSWORD"),
        database=os.getenv("TIDB_DB_NAME", "tec_english"),
        use_pure=True,          
        ssl_verify_cert=True,
        ssl_verify_identity=True,
    )
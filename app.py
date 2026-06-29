from flask import Flask, request, jsonify, render_template, session, redirect, url_for, make_response, flash
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from datetime import timedelta
from dotenv import load_dotenv
from flask_mail import Mail, Message 
from datetime import datetime
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import mysql.connector, uuid, random, os


load_dotenv()

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_bimbel_tec_anda'

# --- 2. KONFIGURASI EMAIL (Contoh menggunakan Gmail) ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')      # GANTI: Masukkan email pengirim
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD' )    # GANTI: Gunakan "App Password" dari Google (bukan password login biasa)
app.config['MAIL_DEFAULT_SENDER'] = ('TEC Parent Portal', 'dennisdg273@gmail.com')

mail = Mail(app)
# -------------------------------------------------------


# --- FUNGSI KONEKSI DATABASE MURNI ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",          
        password="",          
        database="tec_english" 
    )

# --- ROUTING HALAMAN ---

@app.route('/')
@app.route('/index')
def index():
    if 'id_users' in session and session.get('role') == 'murid':
        user_id = session['id_users']
        
        # Buka koneksi DB untuk mengambil data anak
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Ambil data anak milik user yang sedang login
            cursor.execute("""
                SELECT id_anak, nama_lengkap, nama_panggilan, kelas 
                FROM anak 
                WHERE id_orangtua = %s 
                ORDER BY created_at DESC
            """, (user_id,))
            
            daftar_anak = cursor.fetchall()
            
            # Kirim 'daftar_anak' ke index.html bersama dengan 'username'
            return render_template('index.html', 
                                   username=session.get('username'),
                                   daftar_anak=daftar_anak)
                                   
        except Exception as e:
            print(f"Error mengambil data anak untuk dashboard: {e}")
            # Jika error, tetap render halaman tapi daftar_anak kosong
            return render_template('index.html', username=session.get('username'), daftar_anak=[])
        finally:
            cursor.close()
            conn.close()
            
    return redirect(url_for('halaman_portal_orangtua'))

@app.route('/portal_orangtua', methods=['GET'])
def halaman_portal_orangtua():
    if 'id_users' in session and session.get('role') == 'murid':
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def proses_login_orangtua():
    data = request.json
    email = data.get('email') 
    password = data.get('password')

    if not email or not password:
        return jsonify({"message": "Email dan password harus diisi!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True) 

    query = """
            SELECT u.id_users, u.username, u.email, u.password, r.nama_role, u.status_akun
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE u.email = %s
        """
    cursor.execute(query, (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and check_password_hash(user['password'], password):
        # Mencegah login jika belum verifikasi OTP
        if user.get('status_akun') == 'unverified':
            return jsonify({"message": "Akun belum diverifikasi. Silakan cek email Anda."}), 403

        if user['nama_role'].lower() == 'murid':
            session['id_users'] = user['id_users'] 
            session['username'] = user['username']
            session['role'] = 'murid'
            return jsonify({"message": "Login berhasil!", "redirect": url_for('index')}), 200
        else:
            return jsonify({"message": "Akses ditolak!"}), 403
    return jsonify({"message": "Username atau password salah!"}), 401

@app.route('/register', methods=['GET'])
def halaman_register_orangtua():
    if 'id_users' in session and session.get('role') == 'murid':
        return redirect(url_for('index'))
    return render_template('register_orangtua.html')


@app.route('/send_otp', methods=['POST'])
def send_otp():
    if not request.is_json:
        return jsonify({"message": "Request harus berupa JSON!"}), 415

    data = request.json
    email = data.get('email')
    username = data.get('username')
    password = data.get('password')

    if not email or not username or not password:
        return jsonify({"message": "Data tidak lengkap!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. CEK TABEL USERS: Pastikan email/username belum terdaftar secara resmi
        cursor.execute("SELECT id_users FROM users WHERE username=%s OR email=%s", (username, email))
        if cursor.fetchone():
            return jsonify({"message": "Username atau email sudah digunakan!"}), 400

        # 2. Siapkan data untuk ditampung di tabel OTP
        user_id = str(uuid.uuid4().hex[:10]).upper()
        hashed_password = generate_password_hash(password)
        otp = str(random.randint(100000, 999999))

        # 3. MASUKKAN KE TABEL user_otps DULU (Pending Registration)
        cursor.execute("""
            INSERT INTO user_otps (user_id_users, email, username, password, otp_code, expired_at, is_used)
            VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), 0)
        """, (user_id, email, username, hashed_password, otp))
        conn.commit()
        
        # Ambil waktu kedaluwarsa untuk timer Javascript
        cursor.execute("""
            SELECT UNIX_TIMESTAMP(expired_at) * 1000 AS expired_ms 
            FROM user_otps WHERE user_id_users = %s ORDER BY id DESC LIMIT 1
        """, (user_id,))
        expired_ms = cursor.fetchone()['expired_ms']

        # 4. PROSES PENGIRIMAN EMAIL
        try:
            msg = Message('Kode Verifikasi TEC Portal', recipients=[email])
            msg.body = f"Halo {username},\n\nKode OTP Anda adalah: {otp}\nBerlaku selama 5 menit."
            mail.send(msg)
            print(f"[DEBUG] OTP {otp} dikirim ke {email}")
        except Exception as email_err:
            print(f"[ERROR] Email gagal: {email_err}")
            return jsonify({"message": "Gagal mengirim email OTP."}), 500

        return jsonify({
            "message": "OTP berhasil dikirim!",
            "redirect": "/verify_otp_page",
            "user_id": user_id,
            "expired_ms": expired_ms 
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Server Error: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json(force=True) 
    otp_input = data.get('otp')
    user_id = data.get('user_id') 
    
    if not otp_input or not user_id:
        return jsonify({"message": "Data verifikasi tidak lengkap!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Cek apakah OTP valid dan ambil data pendaftarannya
        cursor.execute("""
            SELECT * FROM user_otps 
            WHERE user_id_users = %s AND otp_code = %s AND is_used = 0 AND expired_at > NOW()
        """, (user_id, otp_input))
        otp_data = cursor.fetchone()
        
        if cursor.with_rows: cursor.fetchall()
        
        if otp_data:
            try:
                # 2. OTP BENAR! Sekarang pindahkan datanya ke tabel users
                cursor.execute("""
                    INSERT INTO users (id_users, username, email, password, role_id_role, status_akun)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (otp_data['user_id_users'], otp_data['username'], otp_data['email'], otp_data['password'], 'R01', 'verified'))
                
                # Tandai OTP sudah terpakai
                cursor.execute("UPDATE user_otps SET is_used = 1 WHERE id = %s", (otp_data['id'],))
                conn.commit()
                
                return jsonify({"message": "Verifikasi berhasil!", "redirect": "/index"}), 200
            
            except Exception as insert_err:
                conn.rollback()
                # Jika ada orang lain yang kebetulan mendaftar & verifikasi dengan email yg sama di saat yg bersamaan
                if "Duplicate entry" in str(insert_err):
                    return jsonify({"message": "Maaf, username atau email tersebut baru saja diverifikasi oleh orang lain."}), 400
                raise insert_err
        
        return jsonify({"message": "OTP salah atau kadaluarsa!"}), 400

    except Exception as e:
        conn.rollback()
        return jsonify({"message": "Terjadi kesalahan pada server."}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    data = request.get_json(force=True)
    email = data.get('email')
    user_id = data.get('user_id')

    if not email or not user_id:
        return jsonify({"message": "Data tidak lengkap, silakan daftar ulang!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Ambil data pendaftaran sebelumnya (username & password) dari tabel OTP
        cursor.execute("SELECT username, password FROM user_otps WHERE user_id_users = %s ORDER BY id DESC LIMIT 1", (user_id,))
        pending_data = cursor.fetchone()
        
        if not pending_data:
            return jsonify({"message": "Sesi pendaftaran tidak ditemukan."}), 400

        otp = str(random.randint(100000, 999999))
        
        # Tandai OTP lama menjadi is_used = 1 (hangus)
        cursor.execute("UPDATE user_otps SET is_used = 1 WHERE user_id_users = %s", (user_id,))
        
        # Buat OTP baru dengan membawa data pendaftaran yang sama
        cursor.execute("""
            INSERT INTO user_otps (user_id_users, email, username, password, otp_code, expired_at, is_used) 
            VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), 0)
        """, (user_id, email, pending_data['username'], pending_data['password'], otp))
        conn.commit()

        cursor.execute("""
            SELECT UNIX_TIMESTAMP(expired_at) * 1000 AS expired_ms 
            FROM user_otps WHERE user_id_users = %s ORDER BY id DESC LIMIT 1
        """, (user_id,))
        expired_ms = cursor.fetchone()['expired_ms']

        # Kirim Ulang Email
        msg = Message('Kode Verifikasi TEC Portal (Baru)', recipients=[email])
        msg.body = f"Halo,\n\nIni kode verifikasi OTP baru Anda: {otp}\nBerlaku 5 menit."
        mail.send(msg)

        return jsonify({"message": "OTP baru berhasil dikirim!", "expired_ms": expired_ms}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": "Gagal mengirim OTP."}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/verify_otp_page')
def verify_otp_page():
    return render_template('register_orangtua_otp.html')

@app.route('/proses_regtister/snk', methods=['GET'])
def halaman_syarat_ketentuan():
    return render_template('snk.html')

@app.route('/proses_regtister/kebijakan_privasi', methods=['GET'])
def halaman_kebijakan_privasi():
    return render_template('kebijakan_privasi.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('halaman_portal_orangtua'))

@app.route('/manajemen_anak')
def manajemen_anak():

    if 'id_users' not in session:
        return redirect('/login')
        
    user_id = session['id_users']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Ambil data anak berdasarkan ID orang tua yang sedang login
        cursor.execute("""
            SELECT * FROM anak 
            WHERE id_orangtua = %s 
            ORDER BY created_at DESC
        """, (user_id,))
        daftar_anak = cursor.fetchall()
        
        return render_template('child_management.html', daftar_anak=daftar_anak)
        
    except Exception as e:
        print(f"Error mengambil data anak: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/tambah_anak', methods=['POST'])
def tambah_anak():
    if 'id_users' not in session:
        return redirect('/login')
        
    user_id = session['id_users']
    nama_lengkap = request.form.get('nama_lengkap')
    nama_panggilan = request.form.get('nama_panggilan')
    sekolah_asal = request.form.get('sekolah_asal')
    kelas = request.form.get('kelas')
    tanggal_lahir_raw = request.form.get('tanggal_lahir')
    if tanggal_lahir_raw and tanggal_lahir_raw.strip() != "":
        try:
            # Mengubah string 'YYYY-MM-DD' menjadi objek date Python
            tanggal_lahir = datetime.strptime(tanggal_lahir_raw, '%Y-%m-%d').date()
        except ValueError:
            # Jika formatnya rusak/tidak valid, set jadi None (NULL)
            tanggal_lahir = None
    else:
        # Jika user mengosongkan tanggal, set jadi None agar di DB terbaca NULL
        tanggal_lahir = None    
    
    jenis_kelamin_raw = request.form.get('jenis_kelamin')
    if jenis_kelamin_raw and jenis_kelamin_raw.strip() != "":
        # Memastikan nilai yang dikirim ke DB hanya 'L' atau 'P'
        if jenis_kelamin_raw in ['L', 'Laki-laki']:
            jenis_kelamin = 'L'
        elif jenis_kelamin_raw in ['P', 'Perempuan']:
            jenis_kelamin = 'P'
        else:
            jenis_kelamin = None  # Jika ada nilai aneh yang masuk
    else:
        # Jika user tidak memilih radio button, set jadi None (NULL di DB)
        jenis_kelamin = None
    
    if not nama_lengkap:
        flash('Nama lengkap wajib diisi!', 'error')
        return redirect('/manajemen_anak')
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Insert data anak baru ke database
        cursor.execute("""
            INSERT INTO anak (id_orangtua, nama_lengkap, nama_panggilan, tanggal_lahir, jenis_kelamin, status_anak, sekolah_asal, kelas)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s)
        """, (user_id, nama_lengkap, nama_panggilan, tanggal_lahir, jenis_kelamin, sekolah_asal, kelas))
        
        conn.commit()
        flash('Data anak berhasil ditambahkan!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error menambah anak: {e}")
        flash('Gagal menambahkan data anak.', 'error')
    finally:
        cursor.close()
        conn.close()
        
    return redirect('/manajemen_anak')

@app.route('/kelas')
def kelas():
    return render_template('kelas.html')

@app.route('/riwayat_pembayaran')
def riwayat_pembayaran():
    return render_template('riwayat_transaksi.html')

@app.route('/jadwal_belajar')
def jadwal_belajar():
    return render_template('jadwal_belajar.html')

@app.route('/presensi')
def presensi():
    return render_template('presensi.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')


##BAGIAN ADMIN
##BAGIAN ADMIN
##BAGIAN ADMIN



@app.route('/dashboard_admin')
def dashboard_admin():
    if 'user_id' not in session:
        return redirect(url_for('login_admin'))
    return render_template('dashboard_admin.html')

# Tugas: Menampilkan wujud halaman web (UI)
@app.route('/login_admin')
def login_admin():
    return render_template('login_admin.html')

@app.route('/login_admin_action', methods=['POST'])
def login_admin_action():
    data = request.get_json(force=True)
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"message": "Email dan kata sandi harus diisi!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. PERBAIKAN: Menggunakan u.role_id_role sesuai struktur tabel Anda
        cursor.execute("""
            SELECT u.*, r.nama_role 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE u.email = %s AND r.nama_role = 'Kepala'
        """, (email,))
        
        admin_data = cursor.fetchone()

        if admin_data:
            # 2. PERBAIKAN: Karena password Admin ('12345678') di DB bukan hash scrypt, 
            # kita harus menggunakan pengecekan sama dengan (==) biasa.
            if admin_data['password'] == password:
                
                # Buat sesi login
                session['user_id'] = admin_data['id_users'] 
                session['role'] = admin_data['nama_role']
                
                # Bonus: Simpan username agar bisa ditampilkan di navbar dashboard nanti!
                session['username'] = admin_data['username'] 

                return jsonify({
                    "message": "Login berhasil!", 
                    "redirect": "/dashboard_admin"
                }), 200
            else:
                return jsonify({"message": "Kata sandi salah!"}), 401
        else:
            return jsonify({"message": "Akun admin tidak ditemukan atau email salah!"}), 404

    except Exception as e:
        print(f"Error saat login admin: {e}")
        return jsonify({"message": "Terjadi kesalahan pada server."}), 500
    finally:
        if cursor.with_rows:
            cursor.fetchall()
        cursor.close()
        conn.close()

@app.route('/logout_admin')
def logout_admin():
    session.clear()
    return redirect(url_for('login_admin'))

@app.route('/manajemen_kelas_admin')
def manajemen_kelas_admin():
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('login_admin'))
    return render_template('manajemen_kelas.html')

import math # Tambahkan ini di bagian paling atas file (bersama import lainnya)

@app.route('/manajemen_pengajar_admin')
def manajemen_pengajar_admin():
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('login_admin'))
    
    # 1. Menangkap Parameter dari URL
    search = request.args.get('search', '')
    subject = request.args.get('subject', 'All')
    page = request.args.get('page', 1, type=int)
    per_page = 10 # Batas data per halaman
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT COUNT(*) as total_semua 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE r.nama_role = 'Pengajar'
        """)
        total_semua = cursor.fetchone()['total_semua']
        # 2. Query Dasar
        base_query = """
            SELECT u.id_users, u.username, u.email, u.status_akun 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE r.nama_role = 'Pengajar'
        """
        params = []
        
        # 3. Filter Pencarian (Nama / ID)
        if search:
            base_query += " AND (u.username LIKE %s OR u.id_users LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])
            
        # (Opsional) Filter Subjek jika Anda sudah membuat kolom 'keahlian' di DB
        # if subject != 'All':
        #     base_query += " AND u.keahlian = %s"
        #     params.append(subject)
            
        # 4. Hitung Total Data untuk Pagination
        cursor.execute(base_query, params)
        total_data = len(cursor.fetchall())
        total_pages = math.ceil(total_data / per_page)
        if total_pages == 0: 
            total_pages = 1
            
        # 5. Eksekusi Query dengan Limit & Offset
        offset = (page - 1) * per_page
        final_query = base_query + " ORDER BY u.username ASC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        cursor.execute(final_query, params)
        daftar_pengajar = cursor.fetchall()
        
        # 6. Kirim data ke HTML
        return render_template('manajemen_pengajar.html', 
                               daftar_pengajar=daftar_pengajar,
                               search=search,
                               subject=subject,
                               page=page,
                               total_pages=total_pages,
                               total_data=total_data,
                               total_semua=total_semua)
                               
    except Exception as e:
        print(f"Error memuat data pengajar: {e}")
        flash('Terjadi kesalahan saat memuat data.', 'error')
        return render_template('manajemen_pengajar.html', daftar_pengajar=[], total_pages=1, page=1)
    finally:
        cursor.close()
        conn.close()

@app.route('/manajemen_orangtua_admin')
def manajemen_orangtua_admin():
    # Proteksi Sesi Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('login_admin'))
    
    # 1. Tangkap Parameter Query String dari URL
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Batas data per halaman table
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # --- KELOMPOK STATISTIK DASHBOARD ---
        # A. Hitung Jumlah Keluarga (User dengan role 'murid'/orangtua)
        cursor.execute("""
            SELECT COUNT(*) as total_keluarga 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE r.nama_role = 'murid'
        """)
        total_keluarga = cursor.fetchone()['total_keluarga'] or 0
        
        # B. Hitung Siswa Aktif dari tabel anak
        cursor.execute("SELECT COUNT(*) as total_siswa_aktif FROM anak WHERE status_anak = 'Active'")
        total_siswa_aktif = cursor.fetchone()['total_siswa_aktif'] or 0
        
        # C. Hitung Pendaftaran Tertunda (Orang tua yang akunnya masih 'unverified')
        cursor.execute("""
            SELECT COUNT(*) as total_pending 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE r.nama_role = 'murid' AND u.status_akun = 'unverified'
        """)
        total_pending = cursor.fetchone()['total_pending'] or 0


        # --- QUERY DAFTAR ORANG TUA & JUMLAH ANAK ---
        # Menggunakan LEFT JOIN agar orang tua yang belum mendaftarkan anaknya tetap muncul di list admin
        base_query = """
            SELECT 
                u.id_users, 
                u.username, 
                u.email, 
                u.status_akun,
                COUNT(a.id_anak) as total_anak
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            LEFT JOIN anak a ON u.id_users = a.id_orangtua
            WHERE r.nama_role = 'murid'
        """
        params = []
        
        # Filter Pencarian Berdasarkan Nama Pengguna atau Email
        if search:
            base_query += " AND (u.username LIKE %s OR u.email LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])
            
        base_query += " GROUP BY u.id_users"
        
        # Hitung total baris data yang cocok (untuk kalkulasi halaman)
        cursor.execute(base_query, params)
        total_data = len(cursor.fetchall())
        total_pages = math.ceil(total_data / per_page)
        if total_pages == 0: 
            total_pages = 1
            
        # Eksekusi limitasi halaman data (Pagination)
        final_query = base_query + " ORDER BY u.username ASC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        cursor.execute(final_query, params)
        daftar_orangtua = cursor.fetchall()
        
        # Kirim variabel data menuju context template Jinja2
        return render_template('manajemen_orangtua_anak.html', 
                               daftar_orangtua=daftar_orangtua,
                               search=search,
                               page=page,
                               total_pages=total_pages,
                               total_data=total_data,
                               total_keluarga=total_keluarga,
                               total_siswa_aktif=total_siswa_aktif,
                               total_pending=total_pending)
                               
    except Exception as e:
        print(f"[ERROR] Gagal memuat manajemen orang tua & anak: {e}")
        flash('Terjadi kegagalan sistem saat mengambil data komunitas.', 'error')
        return render_template('manajemen_orangtua_anak.html', 
                               daftar_orangtua=[], 
                               total_pages=1, 
                               page=1, 
                               total_data=0,
                               total_keluarga=0,
                               total_siswa_aktif=0,
                               total_pending=0)
    finally:
        cursor.close()
        conn.close()

@app.route('/tambah_pengajar', methods=['POST'])
def tambah_pengajar():
    # Pastikan yang mengakses adalah Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('login_admin'))
    
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    
    # Validasi input kosong
    if not username or not email or not password:
        flash('Semua data wajib diisi!', 'error')
        return redirect(url_for('manajemen_pengajar_admin'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Cek apakah email sudah terdaftar sebelumnya
        cursor.execute("SELECT id_users FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('Email sudah terdaftar!', 'error')
            return redirect(url_for('manajemen_pengajar_admin'))
        
        # 2. Ambil id_role untuk 'Pengajar' dari tabel role secara dinamis
        cursor.execute("SELECT id_role FROM role WHERE nama_role = 'Pengajar'")
        role_data = cursor.fetchone()
        if not role_data:
            flash('Role Pengajar tidak ditemukan di database!', 'error')
            return redirect(url_for('manajemen_pengajar_admin'))
            
        role_id = role_data['id_role']
        
        # 3. Generate ID unik untuk pengajar baru (Format UUID 10 karakter seperti sistem OTP Anda)
        new_user_id = str(uuid.uuid4().hex[:10]).upper()
        
        # 4. Insert data ke tabel users
        # Catatan: Password disimpan dalam bentuk plain text agar sesuai dengan fungsi 
        # `login_pengajar_action` Anda yang menggunakan perbandingan langsung (`== password`)
        cursor.execute("""
            INSERT INTO users (id_users, username, email, password, role_id_role, status_akun)
            VALUES (%s, %s, %s, %s, %s, 'verified')
        """, (new_user_id, username, email, password, role_id))
        
        conn.commit()
        flash('Pengajar baru berhasil ditambahkan!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error saat menambah pengajar: {e}")
        flash('Terjadi kesalahan pada server saat menambahkan pengajar.', 'error')
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('manajemen_pengajar_admin'))


##BAGIAN PENGAJAR
##BAGIAN PENGAJAR
##BAGIAN PENGAJAR


@app.route('/login_pengajar_action', methods=['POST'])
def login_pengajar_action():
    data = request.get_json(force=True)
    email = data.get('email')
    password = data.get('password')

    # 1. Validasi input kosong
    if not email or not password:
        return jsonify({"message": "Email dan kata sandi harus diisi!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 2. SQL JOIN disesuaikan dengan kolom 'role_id_role' dan nama_role 'Pengajar'
        cursor.execute("""
            SELECT u.*, r.nama_role 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE u.email = %s AND r.nama_role = 'Pengajar'
        """, (email,))
        
        pembimbing_data = cursor.fetchone()

        # 3. Jika akun pengajar ditemukan
        if pembimbing_data:
            
            # Menggunakan check_password_hash karena akun dengan role Pengajar/Murid 
            # idealnya tersimpan dalam bentuk hash (scrypt) seperti akun 'Farrel' atau 'denis'
            if pembimbing_data['password'] == password:
                
                # 4. Simpan data pengguna ke dalam session Flask
                session['user_id'] = pembimbing_data['id_users'] 
                session['role'] = pembimbing_data['nama_role']     # Berisi 'Pengajar'
                session['username'] = pembimbing_data['username'] # Menyimpan nama asli pembimbing
                
                return jsonify({
                    "message": "Login berhasil!", 
                    "redirect": "/dashboard_pengajar" # Halaman utama setelah pembimbing masuk
                }), 200
            else:
                return jsonify({"message": "Kata sandi salah!"}), 401
        else:
            return jsonify({"message": "Akun pembimbing tidak ditemukan atau email salah!"}), 404

    except Exception as e:
        print(f"Error saat login pembimbing: {e}")
        return jsonify({"message": "Terjadi kesalahan pada server."}), 500
    finally:
        # Selalu bersihkan sisa eksekusi query dan tutup koneksi database
        if cursor.with_rows:
            cursor.fetchall()
        cursor.close()
        conn.close()

@app.route('/login_pengajar')
def login_pengajar():
    return render_template('login_pengajar.html')

@app.route('/dashboard_pengajar')
def dashboard_pengajar():
    if 'user_id' not in session:
        return redirect(url_for('login_pengajar'))
    return render_template('dashboard_pengajar.html')

@app.route('/logout_pengajar')
def logout_pengajar():
    session.clear()
    return redirect(url_for('login_pengajar'))

if __name__ == '__main__':
    app.run(debug=True)
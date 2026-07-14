from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
import uuid, random, re, os, logging, cloudinary.uploader
from db import get_db_connection
from extensions import send_email
from google_calendar import (
    get_authorization_url, exchange_code_for_credentials, save_credentials,
    is_connected, disconnect, sync_jadwal_to_calendar,
    GoogleCalendarNotConfigured, GoogleCalendarNotConnected,
)

orangtua_bp = Blueprint('orangtua', __name__,)

# Folder penyimpanan file bukti pembayaran yang diupload orang tua
UPLOAD_FOLDER_BUKTI_BAYAR = os.path.join('static', 'uploads', 'bukti_bayar')
EKSTENSI_DIIZINKAN = {'png', 'jpg', 'jpeg', 'pdf'}


def ekstensi_valid(nama_file):
    return '.' in nama_file and nama_file.rsplit('.', 1)[1].lower() in EKSTENSI_DIIZINKAN


def generate_kode_pembayaran(id_pembayaran, tanggal_bayar=None):
    """
    Program tambahan: generate kode unik untuk id_pembayaran secara otomatis.
    Format: PAY-YYYYMMDD-XXXXXX (tanggal transaksi + id_pembayaran 6 digit).

    Kode ini diturunkan langsung dari `id_pembayaran` (Primary Key yang sudah
    unik) sehingga TIDAK memerlukan kolom baru di tabel `pembayaran` dan akan
    selalu sama tiap kali dipanggil untuk id_pembayaran yang sama.
    """
    tanggal_bayar = tanggal_bayar or datetime.now()
    return f"PAY-{tanggal_bayar.strftime('%Y%m%d')}-{id_pembayaran:06d}"

@orangtua_bp.route('/')
@orangtua_bp.route('/index')
def index():
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    user_id = session['id_users']
    selected_anak_id = request.args.get('anak_id') 
    
    conn = get_db_connection()
    cursor = conn.cursor    (dictionary=True)
    
    try:
        # 1. Ambil daftar anak milik orang tua ini (hanya yang aktif -- anak
        # nonaktif tidak ditampilkan di dropdown maupun jadwal/kelasnya)
        cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s AND status_anak = 'Active' ORDER BY created_at DESC", (user_id,))
        daftar_anak = cursor.fetchall()
        
        anak_aktif = None
        kelas_anak = []
        statistik_presensi = {'hadir': 0, 'tidak_hadir': 0, 'total': 0, 'persentase': 0}
        riwayat_transaksi = []
        
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (user_id,))
        user_data = cursor.fetchone()
        # Gunakan foto dari database, jika kosong gunakan default_parent.png
        foto_profil_user = user_data['foto_profil'] if user_data and user_data['foto_profil'] else 'default_parent.png'
        # --------------------------------------------------------------

        # 1. Ambil daftar anak milik orang tua ini (hanya yang aktif)
        cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s AND status_anak = 'Active' ORDER BY created_at DESC", (user_id,))
        daftar_anak = cursor.fetchall()

        if daftar_anak:
            if selected_anak_id:
                for anak in daftar_anak:
                    if str(anak['id_anak']) == str(selected_anak_id):
                        anak_aktif = anak
                        break
            
            if not anak_aktif:
                anak_aktif = daftar_anak[0]
                
            # 2. Ambil informasi kelas yang dimiliki si anak aktif
            query_kelas = """
                SELECT k.id_kelas, k.nama_kelas, k.hari_jadwal, k.jam_mulai, k.jam_selesai, u.username AS nama_tutor
                FROM pendaftaran p
                JOIN kelas k ON p.id_kelas = k.id_kelas
                LEFT JOIN users u ON k.id_pengajar = u.id_users
                WHERE p.id_anak = %s AND p.status_pendaftaran = 'Aktif'
            """
            cursor.execute(query_kelas, (anak_aktif['id_anak'],))
            kelas_anak = cursor.fetchall()
            
            # Format jam kelas
            for k in kelas_anak:
                if k['jam_mulai'] and hasattr(k['jam_mulai'], 'total_seconds'):
                    ts = int(k['jam_mulai'].total_seconds())
                    k['jam_mulai'] = f"{ts // 3600:02d}:{(ts % 3600) // 60:02d}"
                if k['jam_selesai'] and hasattr(k['jam_selesai'], 'total_seconds'):
                    ts = int(k['jam_selesai'].total_seconds())
                    k['jam_selesai'] = f"{ts // 3600:02d}:{(ts % 3600) // 60:02d}"

            # 3. Hitung presensi si anak berdasarkan sesi kelas
            query_presensi = """
                SELECT status_kehadiran, COUNT(*) as jumlah
                FROM presensi
                JOIN pendaftaran p ON presensi.id_pendaftaran = p.id_pendaftaran
                WHERE p.id_anak = %s
                GROUP BY status_kehadiran
            """
            cursor.execute(query_presensi, (anak_aktif['id_anak'],))
            presensi_data = cursor.fetchall()
            
            for p in presensi_data:
                if p['status_kehadiran'] == 'Hadir':
                    statistik_presensi['hadir'] += p['jumlah']
                else:
                    statistik_presensi['tidak_hadir'] += p['jumlah']
            
            statistik_presensi['total'] = statistik_presensi['hadir'] + statistik_presensi['tidak_hadir']
            if statistik_presensi['total'] > 0:
                statistik_presensi['persentase'] = round((statistik_presensi['hadir'] / statistik_presensi['total']) * 100)

        # 4. Ambil riwayat transaksi keseluruhan orang tua (5 transaksi terakhir)
        query_transaksi = """
            SELECT p.id_pembayaran, p.jumlah_bayar, p.tanggal_bayar, p.status_pembayaran, k.nama_kelas
            FROM pembayaran p
            JOIN pendaftaran pd ON p.id_pendaftaran = pd.id_pendaftaran
            JOIN anak a ON pd.id_anak = a.id_anak
            JOIN kelas k ON pd.id_kelas = k.id_kelas
            WHERE a.id_orangtua = %s
            ORDER BY p.tanggal_bayar DESC
            LIMIT 5
        """
        cursor.execute(query_transaksi, (user_id,))
        riwayat_transaksi = cursor.fetchall()

        return render_template('orangtua/index.html', 
                               username=session.get('username'), 
                               daftar_anak=daftar_anak, 
                               anak_aktif=anak_aktif,
                               kelas_anak=kelas_anak,
                               statistik_presensi=statistik_presensi,
                               riwayat_transaksi=riwayat_transaksi,
                               foto_profil=foto_profil_user)
                               
    except Exception as e:
        print(f"Error loading dashboard: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/portal_orangtua', methods=['GET'])
def halaman_portal_orangtua():
    if 'id_users' in session and session.get('role') == 'murid':
        return redirect(url_for('orangtua.index'))
    return render_template('orangtua/login.html')

@orangtua_bp.route('/login', methods=['POST'])
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

        # Mencegah login jika akun dibekukan (suspended) oleh admin
        if user.get('status_akun') == 'suspended':
            return jsonify({"message": "Akun Anda telah dibekukan (suspended). Silakan hubungi admin."}), 403

        if user['nama_role'].lower() == 'murid':
            session['id_users'] = user['id_users'] 
            session['username'] = user['username']
            session['role'] = 'murid'
            return jsonify({"message": "Login berhasil!", "redirect": url_for('orangtua.index')}), 200
        else:
            return jsonify({"message": "Akses ditolak!"}), 403
    return jsonify({"message": "Username atau password salah!"}), 401

@orangtua_bp.route('/register', methods=['GET'])
def halaman_register_orangtua():
    if 'id_users' in session and session.get('role') == 'murid':
        return redirect(url_for('orangtua.index'))
    return render_template('orangtua/register_orangtua.html')


@orangtua_bp.route('/send_otp', methods=['POST'])
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

        # 4. PROSES PENGIRIMAN EMAIL (via SMTP / Flask-Mail)
        try:
            send_email(
                to=email,
                subject='Kode Verifikasi TEC Portal',
                body=f"Halo {username},\n\nKode OTP Anda adalah: {otp}\nBerlaku selama 5 menit."
            )
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


@orangtua_bp.route('/verify_otp', methods=['POST'])
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


@orangtua_bp.route('/resend_otp', methods=['POST'])
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

        # Kirim Ulang Email (via SMTP / Flask-Mail)
        send_email(
            to=email,
            subject='Kode Verifikasi TEC Portal (Baru)',
            body=f"Halo,\n\nIni kode verifikasi OTP baru Anda: {otp}\nBerlaku 5 menit."
        )

        return jsonify({"message": "OTP baru berhasil dikirim!", "expired_ms": expired_ms}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": "Gagal mengirim OTP."}), 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/verify_otp_page')
def verify_otp_page():
    return render_template('orangtua/register_orangtua_otp.html')

@orangtua_bp.route('/proses_regtister/snk', methods=['GET'])
def halaman_syarat_ketentuan():
    return render_template('orangtua/snk.html')

@orangtua_bp.route('/proses_regtister/kebijakan_privasi', methods=['GET'])
def halaman_kebijakan_privasi():
    return render_template('orangtua/kebijakan_privasi.html')

@orangtua_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    # Jika GET, tampilkan halaman form Lupa Password
    if request.method == 'GET':
        return render_template('orangtua/lupa_password.html')
    
    # Jika POST, proses pencarian email
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'message': 'Email wajib diisi.'}), 400

        # Koneksi ke database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Cari user berdasarkan email dan rolenya (R01 = Murid/Orangtua)
        cursor.execute("SELECT id_users FROM users WHERE email = %s AND role_id_role = 'R01'", (email,))
        user = cursor.fetchone()
        
        if user:
            # 1. Buat kode OTP dan catat ID user
            otp = str(random.randint(100000, 999999))
            user_id = user['id_users']
            
            # 2. Simpan OTP ke database user_otps
            cursor.execute("""
                INSERT INTO user_otps (user_id_users, email, otp_code, expired_at, is_used) 
                VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), 0)
            """, (user_id, email, otp))
            conn.commit()
            
            # 3. Kirim email (via SMTP / Flask-Mail)
            try:
                send_email(
                    to=email,
                    subject='Kode OTP Reset Password',
                    body=f"Kode OTP untuk mereset kata sandi Anda adalah: {otp}\nBerlaku selama 5 menit."
                )
                print(f"[DEBUG] OTP Lupa Password {otp} dikirim ke {email}")
            except Exception as e:
                print(f"Gagal mengirim email: {e}")
                
        cursor.close()
        conn.close()
            
        # Selalu kembalikan respon sukses + redirect ke input OTP dengan membawa URL parameter email
        return jsonify({
            'message': 'Jika email terdaftar, kode OTP telah dikirim.',
            'redirect': url_for('orangtua.verify_reset_otp', email=email)
        }), 200

@orangtua_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    # Menampilkan halaman input OTP
    if request.method == 'GET':
        email = request.args.get('email')
        if not email:
            return redirect(url_for('orangtua.forgot_password'))
        return render_template('orangtua/lupa_password_otp.html', email=email)
        
    # Memproses validasi kode OTP
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        otp = data.get('otp')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Cek OTP berdasarkan email (Ambil data paling baru jika ada multiple)
        cursor.execute("""
            SELECT * FROM user_otps 
            WHERE email = %s AND otp_code = %s AND is_used = 0 AND expired_at > NOW()
            ORDER BY id DESC LIMIT 1
        """, (email, otp))
        otp_data = cursor.fetchone()
        
        if otp_data:
            # OTP Valid: Tandai sudah dipakai (hangus)
            cursor.execute("UPDATE user_otps SET is_used = 1 WHERE id = %s", (otp_data['id'],))
            conn.commit()
            
            # Simpan Sesi (session) bahwa email ini telah tervalidasi OTP-nya untuk reset password
            session['reset_email'] = email
            
            cursor.close()
            conn.close()
            
            return jsonify({
                'message': 'OTP Valid. Silakan buat password baru.',
                'redirect': url_for('orangtua.reset_password')
            }), 200
        else:
            cursor.close()
            conn.close()
            return jsonify({'message': 'Kode OTP salah atau telah kadaluarsa!'}), 400

@orangtua_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    # Mencegah user mengakses halaman ini jika belum verifikasi OTP
    if request.method == 'GET':
        if 'reset_email' not in session:
            return redirect(url_for('orangtua.forgot_password'))
        return render_template('orangtua/reset_password.html')
        
    # Proses update password baru ke database
    if request.method == 'POST':
        if 'reset_email' not in session:
            return jsonify({'message': 'Sesi telah berakhir, silakan ulang dari awal.'}), 400
            
        data = request.get_json()
        new_password = data.get('password')
        email = session['reset_email'] # Email didapat dengan aman dari Session
        
        # Enkripsi password baru
        hashed_password = generate_password_hash(new_password)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update ke tabel users
        cursor.execute("""
            UPDATE users SET password = %s WHERE email = %s AND role_id_role = 'R01'
        """, (hashed_password, email))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        # Hapus sesi agar tidak bisa dikunjungi lagi 
        session.pop('reset_email', None)
        
        return jsonify({
            'message': 'Kata sandi berhasil diubah! Silakan login.',
            'redirect': url_for('orangtua.halaman_portal_orangtua')
        }), 200
@orangtua_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('orangtua.halaman_portal_orangtua'))

@orangtua_bp.route('/manajemen_anak')
def manajemen_anak():
    if 'id_users' not in session:
        return redirect('/login')
        
    user_id = session['id_users']

    # Tab mana yang sebaiknya aktif saat halaman pertama kali dibuka
    # (dipakai oleh JS di frontend, bukan untuk memfilter query -- karena
    # data Aktif & Nonaktif sekalian diambil semua di bawah, supaya
    # perpindahan tab Aktif/Nonaktif di frontend tidak perlu reload halaman).
    status_filter = request.args.get('status', 'Active')
    if status_filter not in ('Active', 'Inactive'):
        status_filter = 'Active'

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Ambil SEMUA data anak (baik Aktif maupun Nonaktif) sekaligus.
        # Pemisahan tampilan per status dilakukan di JavaScript (client-side),
        # supaya switch tab Aktif/Nonaktif instan tanpa perlu request baru ke server.
        cursor.execute("""
            SELECT * FROM anak 
            WHERE id_orangtua = %s
            ORDER BY created_at DESC
        """, (user_id,))
        daftar_anak = cursor.fetchall()

        # Hitung jumlah anak per status untuk ditampilkan sebagai counter di tab
        total_aktif = sum(1 for a in daftar_anak if a['status_anak'] == 'Active')
        total_nonaktif = sum(1 for a in daftar_anak if a['status_anak'] == 'Inactive')
        
        # Tambahkan informasi tambahan untuk setiap anak (Jumlah Kelas & Kelas Mendatang)
        for anak in daftar_anak:
            # 1. Hitung jumlah kelas aktif
            cursor.execute("""
                SELECT COUNT(*) as jumlah_kelas 
                FROM pendaftaran 
                WHERE id_anak = %s AND status_pendaftaran = 'Aktif'
            """, (anak['id_anak'],))
            anak['jumlah_kelas'] = cursor.fetchone()['jumlah_kelas']
            
            # 2. Ambil data kelas mendatang
            cursor.execute("""
                SELECT k.nama_kelas, k.hari_jadwal, k.jam_mulai, u.username as nama_pengajar
                FROM pendaftaran p
                JOIN kelas k ON p.id_kelas = k.id_kelas
                LEFT JOIN users u ON k.id_pengajar = u.id_users
                WHERE p.id_anak = %s AND p.status_pendaftaran = 'Aktif'
            """, (anak['id_anak'],))
            jadwal = cursor.fetchall()
            
            # Format jam mulai
            for j in jadwal:
                if j['jam_mulai'] and hasattr(j['jam_mulai'], 'total_seconds'):
                    ts = int(j['jam_mulai'].total_seconds())
                    j['jam_mulai'] = f"{ts // 3600:02d}:{(ts % 3600) // 60:02d}"
            
            anak['jadwal_mendatang'] = jadwal
            
        # Ambil foto profil user (untuk topbar), sama seperti route lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (user_id,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        return render_template('orangtua/child_management.html',
                               daftar_anak=daftar_anak,
                               status_filter=status_filter,
                               total_aktif=total_aktif,
                               total_nonaktif=total_nonaktif,
                               username=session.get('username'),
                               foto_profil=foto_profil_user)
        
    except Exception as e:
        print(f"Error mengambil data anak: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/toggle_status_anak', methods=['POST'])
def toggle_status_anak():
    """
    Menonaktifkan atau mengaktifkan kembali akun anak (toggle status_anak
    antara 'Active' <-> 'Inactive'). Dipanggil dari tombol "Nonaktifkan" /
    "Aktifkan Kembali" di halaman Manajemen Anak.
    """
    if 'id_users' not in session:
        return redirect('/login')

    user_id = session['id_users']
    id_anak = request.form.get('id_anak')
    # Dipakai supaya setelah proses selesai, halaman kembali ke tab (Aktif/Nonaktif)
    # yang sedang dilihat orang tua saat menekan tombol
    redirect_status = request.form.get('redirect_status', 'Active')
    if redirect_status not in ('Active', 'Inactive'):
        redirect_status = 'Active'

    if not id_anak:
        flash('Data anak tidak valid.', 'error')
        return redirect(f'/manajemen_anak?status={redirect_status}')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Pastikan anak ini benar milik orang tua yang sedang login
        cursor.execute("""
            SELECT status_anak, nama_lengkap FROM anak 
            WHERE id_anak = %s AND id_orangtua = %s
        """, (id_anak, user_id))
        anak = cursor.fetchone()

        if not anak:
            flash('Data anak tidak ditemukan.', 'error')
            return redirect(f'/manajemen_anak?status={redirect_status}')

        status_baru = 'Inactive' if anak['status_anak'] == 'Active' else 'Active'

        cursor.execute("""
            UPDATE anak SET status_anak = %s 
            WHERE id_anak = %s AND id_orangtua = %s
        """, (status_baru, id_anak, user_id))
        conn.commit()

        if status_baru == 'Inactive':
            flash(f'Akun anak "{anak["nama_lengkap"]}" berhasil dinonaktifkan.', 'success')
        else:
            flash(f'Akun anak "{anak["nama_lengkap"]}" berhasil diaktifkan kembali.', 'success')

    except Exception as e:
        conn.rollback()
        print(f"Error mengubah status anak: {e}")
        flash('Gagal mengubah status akun anak.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(f'/manajemen_anak?status={redirect_status}')

@orangtua_bp.route('/tambah_anak', methods=['POST'])
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

    # Tangani Upload Foto ke Cloudinary (kalau orang tua mengisi foto saat menambah anak)
    foto = request.files.get('foto_profil')
    url_foto_cloudinary = None

    if foto and foto.filename != '':
        if foto_valid(foto.filename):
            try:
                upload_result = cloudinary.uploader.upload(
                    foto,
                    folder="tec_portal/foto_anak"
                )
                url_foto_cloudinary = upload_result.get('secure_url')
            except Exception as e:
                flash(f'Gagal mengunggah foto: {str(e)}', 'error')
                return redirect('/manajemen_anak')
        else:
            flash('Format foto tidak valid. Gunakan JPG atau PNG.', 'error')
            return redirect('/manajemen_anak')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if url_foto_cloudinary:
            # Insert data anak baru berikut URL foto dari Cloudinary
            cursor.execute("""
                INSERT INTO anak (id_orangtua, nama_lengkap, nama_panggilan, tanggal_lahir, jenis_kelamin, status_anak, sekolah_asal, kelas, foto_profil)
                VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, %s)
            """, (user_id, nama_lengkap, nama_panggilan, tanggal_lahir, jenis_kelamin, sekolah_asal, kelas, url_foto_cloudinary))
        else:
            # Insert data anak baru tanpa foto (biarkan pakai default_anak.png dari DB)
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

UPLOAD_FOLDER_FOTO = os.path.join('static', 'img')
EKSTENSI_FOTO_VALID = {'png', 'jpg', 'jpeg'}

def foto_valid(nama_file):
    return '.' in nama_file and nama_file.rsplit('.', 1)[1].lower() in EKSTENSI_FOTO_VALID

@orangtua_bp.route('/edit_anak', methods=['POST'])
def edit_anak():
    if 'id_users' not in session:
        return redirect('/login')
        
    user_id = session['id_users']
    id_anak = request.form.get('id_anak')
    nama_lengkap = request.form.get('nama_lengkap')
    nama_panggilan = request.form.get('nama_panggilan')
    sekolah_asal = request.form.get('sekolah_asal')
    kelas = request.form.get('kelas')
    tanggal_lahir_raw = request.form.get('tanggal_lahir')
    jenis_kelamin = request.form.get('jenis_kelamin')
    
    if not id_anak or not nama_lengkap:
        flash('Data wajib tidak lengkap!', 'error')
        return redirect('/manajemen_anak')
        
    # 1. Format tanggal lahir
    tanggal_lahir = None
    if tanggal_lahir_raw and tanggal_lahir_raw.strip() != "":
        try:
            tanggal_lahir = datetime.strptime(tanggal_lahir_raw, '%Y-%m-%d').date()
        except ValueError:
            tanggal_lahir = None

    # 2. Tangani Upload Foto ke Cloudinary
    foto = request.files.get('foto_profil')
    url_foto_cloudinary = None

    if foto and foto.filename != '':
        if foto_valid(foto.filename):
            try:
                # Mengunggah ke Cloudinary ke folder khusus
                upload_result = cloudinary.uploader.upload(
                    foto,
                    folder="tec_portal/foto_anak"
                )
                url_foto_cloudinary = upload_result.get('secure_url')
            except Exception as e:
                flash(f'Gagal mengunggah foto: {str(e)}', 'error')
                return redirect('/manajemen_anak')
        else:
            flash('Format foto tidak valid. Gunakan JPG atau PNG.', 'error')
            return redirect('/manajemen_anak')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 3. Jalankan Query Update 
        if url_foto_cloudinary:
            # Simpan secure_url dari Cloudinary ke database
            cursor.execute("""
                UPDATE anak 
                SET nama_lengkap = %s, nama_panggilan = %s, sekolah_asal = %s, 
                    kelas = %s, tanggal_lahir = %s, jenis_kelamin = %s, foto_profil = %s
                WHERE id_anak = %s AND id_orangtua = %s
            """, (nama_lengkap, nama_panggilan, sekolah_asal, kelas, tanggal_lahir, jenis_kelamin, url_foto_cloudinary, id_anak, user_id))
        else:
            # Jika user TIDAK mengunggah foto
            cursor.execute("""
                UPDATE anak 
                SET nama_lengkap = %s, nama_panggilan = %s, sekolah_asal = %s, 
                    kelas = %s, tanggal_lahir = %s, jenis_kelamin = %s
                WHERE id_anak = %s AND id_orangtua = %s
            """, (nama_lengkap, nama_panggilan, sekolah_asal, kelas, tanggal_lahir, jenis_kelamin, id_anak, user_id))
        
        conn.commit()
        flash('Profil anak berhasil diperbarui!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error update anak: {e}")
        flash('Gagal memperbarui profil anak.', 'error')
    finally:
        cursor.close()
        conn.close()
        
    return redirect('/manajemen_anak')
        
    

@orangtua_bp.route('/kelas')
def halaman_pendaftaran_kelas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user_id = session['id_users']

    # ... (Biarkan query daftar_kelas tetap seperti aslinya) ...
    query = """
        SELECT k.*, u.username AS nama_tutor,
        (
            SELECT COUNT(*)
            FROM pendaftaran p
            JOIN pembayaran pay ON pay.id_pendaftaran = p.id_pendaftaran
            WHERE p.id_kelas = k.id_kelas
              AND p.status_pendaftaran = 'Aktif'
              AND pay.status_pembayaran = 'Lunas'
        ) AS jumlah_siswa
        FROM kelas k
        LEFT JOIN users u ON k.id_pengajar = u.id_users
        WHERE k.status_kelas = 'Aktif'
    """
    cursor.execute(query)
    daftar_kelas = cursor.fetchall()
    
    # --- UBAH BAGIAN INI: Tambahkan no_telp dan alamat ke dalam query ---
    cursor.execute("SELECT foto_profil, no_telp, alamat FROM users WHERE id_users = %s", (user_id,))
    user_data = cursor.fetchone()
    
    # Cek apakah profil sudah lengkap
    profil_lengkap = True
    if not user_data or not user_data.get('no_telp') or not user_data.get('alamat'):
        profil_lengkap = False
        
    foto_profil_user = user_data['foto_profil'] if user_data and user_data['foto_profil'] else 'default_parent.png'
    # --------------------------------------------------------------

    # 1. Ambil daftar anak milik orang tua ini
    cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s ORDER BY created_at DESC", (user_id,))
    daftar_anak = cursor.fetchall()
    
    # Format waktu jam_mulai dan jam_selesai jadi string HH:MM
    for k in daftar_kelas:
        if k['jam_mulai']:
            k['jam_mulai'] = str(k['jam_mulai'])[:5]
        if k['jam_selesai']:
            k['jam_selesai'] = str(k['jam_selesai'])[:5]

    cursor.close()
    conn.close()
    
    # --- UBAH BAGIAN INI JUGA: Kirim variabel profil_lengkap ke HTML ---
    return render_template('orangtua/kelas.html', 
                           foto_profil=foto_profil_user, 
                           daftar_kelas=daftar_kelas, 
                           username=session.get('username'),
                           profil_lengkap=profil_lengkap)

@orangtua_bp.route('/konfirmasi_kelas/<id_kelas>')
def konfirmasi_kelas(id_kelas):
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Ambil detail kelas yang diklik (sertakan nama & foto pengajar)
        cursor.execute("""
            SELECT k.*, u.username AS nama_tutor, u.foto_profil AS foto_pengajar, u.deskripsi AS deskripsi_pengajar
            FROM kelas k
            LEFT JOIN users u ON k.id_pengajar = u.id_users
            WHERE k.id_kelas = %s
        """, (id_kelas,))
        detail_kelas = cursor.fetchone()
        
        # 2. Ambil daftar anak milik orang tua yang sedang login ini
        # (hanya yang berstatus aktif -- anak nonaktif tidak boleh didaftarkan ke kelas)
        cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s AND status_anak = 'Active'", (session['id_users'],))
        daftar_anak = cursor.fetchall()

        # 2b. Cek anak mana saja yang SUDAH terdaftar aktif di kelas ini,
        # supaya orang tua tidak bisa mendaftarkan anak yang sama dua kali.
        cursor.execute("""
            SELECT id_anak FROM pendaftaran
            WHERE id_kelas = %s AND status_pendaftaran = 'Aktif'
        """, (id_kelas,))
        anak_terdaftar_ids = [str(r['id_anak']) for r in cursor.fetchall()]

        if not detail_kelas:
            flash('Kelas tidak ditemukan.', 'error')
            return redirect(url_for('orangtua.kelas'))

        # Ambil foto profil user (untuk topbar), sama seperti route lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (session['id_users'],))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        # Tampilkan halaman konfirmasi dengan membawa data kelas dan daftar anak
        return render_template('orangtua/konfirmasi_kelas.html', 
                               username=session.get('username'),
                               foto_profil=foto_profil_user,
                               kelas=detail_kelas,
                               deskripsi=detail_kelas.get('deskripsi') or 'Belum ada deskripsi',
                               daftar_anak=daftar_anak,
                               anak_terdaftar_ids=anak_terdaftar_ids)
    except Exception as e:
        print(f"Error halaman konfirmasi: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()



@orangtua_bp.route('/kelas/daftar/<string:id_kelas>', methods=['GET'])
def konfirmasi_pendaftaran(id_kelas):
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    user_id = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Inisialisasi default di awal, SEBELUM try, agar selalu terikat nilai
    kelas_detail = None
    daftar_anak = []
    kriteria_kelas = ''
    deskripsi_text = ''

    try:
        query_kelas = """
            SELECT k.*, u.username AS nama_tutor, u.foto_profil AS foto_pengajar, u.deskripsi AS deskripsi_pengajar
            FROM kelas k
            LEFT JOIN users u ON k.id_pengajar = u.id_users
            WHERE k.id_kelas = %s
        """
        cursor.execute(query_kelas, (id_kelas,))
        kelas_detail = cursor.fetchone()

        if not kelas_detail:
            flash("Kelas tidak ditemukan.", "danger")
            return redirect(url_for('orangtua.halaman_pendaftaran_kelas'))

        # Ambil kriteria/tingkat langsung dari kelas_detail (sudah ada dari SELECT k.*)
        kriteria_kelas = kelas_detail.get('tingkat') or ''
        deskripsi_text = kelas_detail.get('deskripsi') or 'Belum ada deskripsi'

        # Konversi jam_mulai jika berupa timedelta
        if kelas_detail.get('jam_mulai') and hasattr(kelas_detail['jam_mulai'], 'total_seconds'):
            total_sec = int(kelas_detail['jam_mulai'].total_seconds())
            kelas_detail['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

        if kelas_detail.get('jam_selesai') and hasattr(kelas_detail['jam_selesai'], 'total_seconds'):
            total_sec = int(kelas_detail['jam_selesai'].total_seconds())
            kelas_detail['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

        # Ambil daftar anak aktif milik orang tua ini
        cursor.execute(
            "SELECT * FROM anak WHERE id_orangtua = %s AND status_anak = 'Active'",
            (user_id,)
        )
        daftar_anak = cursor.fetchall()

        # Cek anak mana saja yang SUDAH terdaftar aktif di kelas ini,
        # supaya orang tua tidak bisa mendaftarkan anak yang sama dua kali.
        cursor.execute("""
            SELECT id_anak FROM pendaftaran
            WHERE id_kelas = %s AND status_pendaftaran = 'Aktif'
        """, (id_kelas,))
        anak_terdaftar_ids = [str(r['id_anak']) for r in cursor.fetchall()]

        # Ambil foto profil user (untuk topbar), sama seperti route lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (user_id,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        return render_template('orangtua/konfirmasi_kelas.html',
                               kelas=kelas_detail,
                               daftar_anak=daftar_anak,
                               username=session.get('username'),
                               foto_profil=foto_profil_user,
                               deskripsi=deskripsi_text,
                               kriteria_kelas=kriteria_kelas,
                               anak_terdaftar_ids=anak_terdaftar_ids)

    except Exception as e:
        print(f"Error pendaftaran kelas: {e}")
        return f"Terjadi kesalahan internal: {str(e)}", 500
    finally:
        cursor.close()
        conn.close()



@orangtua_bp.route('/pembayaran', methods=['GET', 'POST'])
def pembayaran():
    # 1. Pastikan user (orang tua) sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
    
    # 2. Jika ada pengiriman data dari form pendaftaran kelas (Metode POST)
    if request.method == 'POST':
        id_anak = request.form.get('id_anak')
        id_kelas = request.form.get('id_kelas')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Ambil data anak
            cursor.execute("SELECT * FROM anak WHERE id_anak = %s AND id_orangtua = %s", (id_anak, session['id_users']))
            detail_anak = cursor.fetchone()

            # Ambil data kelas
            query_kelas = """
                SELECT k.*, u.username AS nama_tutor 
                FROM kelas k
                LEFT JOIN users u ON k.id_pengajar = u.id_users
                WHERE k.id_kelas = %s
            """
            cursor.execute(query_kelas, (id_kelas,))
            kelas_detail = cursor.fetchone()

            if not kelas_detail or not detail_anak:
                flash('Data kelas atau anak tidak ditemukan.', 'error')
                return redirect(url_for('orangtua.kelas'))

            # Keamanan tambahan: tolak pendaftaran kalau anak berstatus nonaktif,
            # meskipun request ini tidak lewat dropdown normal di halaman.
            if detail_anak.get('status_anak') != 'Active':
                flash('Anak dengan status nonaktif tidak dapat didaftarkan ke kelas.', 'error')
                return redirect(url_for('orangtua.kelas'))

            # --- VALIDASI BENTROK JADWAL ---
            # Tolak pendaftaran kalau anak ini sudah punya kelas lain (status Aktif
            # atau masih Pending menunggu verifikasi) yang jadwalnya bentrok --
            # hari yang sama DAN jam yang tumpang tindih -- dengan kelas yang mau diambil.
            # Dilakukan pakai perbandingan langsung nilai TIME dari database (timedelta),
            # jadi harus dijalankan SEBELUM jam_mulai/jam_selesai diformat jadi string di bawah.
            cursor.execute("""
                SELECT k.nama_kelas, k.hari_jadwal, k.jam_mulai, k.jam_selesai
                FROM pendaftaran pd
                JOIN kelas k ON pd.id_kelas = k.id_kelas
                WHERE pd.id_anak = %s
                  AND pd.status_pendaftaran IN ('Aktif', 'Pending')
                  AND k.id_kelas != %s
                  AND k.hari_jadwal = %s
            """, (id_anak, id_kelas, kelas_detail['hari_jadwal']))
            kelas_lain_di_hari_sama = cursor.fetchall()

            jam_mulai_baru = kelas_detail['jam_mulai']
            jam_selesai_baru = kelas_detail['jam_selesai']

            for kl in kelas_lain_di_hari_sama:
                # Dua rentang waktu tumpang tindih kalau: mulai_baru < selesai_lama DAN mulai_lama < selesai_baru
                if jam_mulai_baru < kl['jam_selesai'] and kl['jam_mulai'] < jam_selesai_baru:
                    nama_anak_display = detail_anak.get('nama_panggilan') or detail_anak.get('nama_lengkap')
                    jam_bentrok_mulai = str(kl['jam_mulai'])[:5] if kl['jam_mulai'] is not None else '-'
                    jam_bentrok_selesai = str(kl['jam_selesai'])[:5] if kl['jam_selesai'] is not None else '-'
                    flash(
                        f"Jadwal bentrok! {nama_anak_display} sudah punya kelas \"{kl['nama_kelas']}\" "
                        f"pada hari {kl['hari_jadwal']} jam {jam_bentrok_mulai}-{jam_bentrok_selesai} WIB. "
                        f"Tidak bisa mendaftarkan kelas ini karena jadwalnya bertabrakan.",
                        'error'
                    )
                    return redirect(url_for('orangtua.konfirmasi_kelas', id_kelas=id_kelas))

            # Format jam kelas
            if kelas_detail.get('jam_mulai') and hasattr(kelas_detail['jam_mulai'], 'total_seconds'):
                total_sec = int(kelas_detail['jam_mulai'].total_seconds())
                kelas_detail['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

            if kelas_detail.get('jam_selesai') and hasattr(kelas_detail['jam_selesai'], 'total_seconds'):
                total_sec = int(kelas_detail['jam_selesai'].total_seconds())
                kelas_detail['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

            # ========================================================
            # LOGIKA PEMBUATAN ID PEMBAYARAN OTOMATIS (AUTO INCREMENT)
            # ========================================================
            
            # Langkah A: Cek apakah pendaftaran kelas ini sudah ada
            cursor.execute("SELECT id_pendaftaran, status_pendaftaran FROM pendaftaran WHERE id_kelas = %s AND id_anak = %s", (id_kelas, id_anak))
            pendaftaran = cursor.fetchone()

            # Tolak jika anak ini SUDAH terdaftar aktif ATAU masih menunggu verifikasi
            # pembayaran di kelas yang sama, supaya tidak ada pendaftaran/tagihan ganda
            # untuk anak & kelas yang sama.
            if pendaftaran and pendaftaran['status_pendaftaran'] in ('Aktif', 'Pending'):
                nama_anak_display = detail_anak.get('nama_panggilan') or detail_anak.get('nama_lengkap')
                if pendaftaran['status_pendaftaran'] == 'Pending':
                    flash(f"{nama_anak_display} sudah mendaftar di kelas \"{kelas_detail['nama_kelas']}\" dan masih menunggu verifikasi pembayaran dari admin.", 'error')
                else:
                    flash(f"{nama_anak_display} sudah terdaftar di kelas \"{kelas_detail['nama_kelas']}\". Tidak bisa mendaftarkan anak yang sama pada kelas ini lagi.", 'error')
                return redirect(url_for('orangtua.konfirmasi_kelas', id_kelas=id_kelas))

            if not pendaftaran:
                # Jika belum ada, buat pendaftaran baru dengan status Pending --
                # baru menjadi 'Aktif' setelah admin memverifikasi pembayarannya
                # (lihat setujui_pembayaran / tolak_pembayaran di admin.py)
                cursor.execute("INSERT INTO pendaftaran (id_kelas, id_anak, status_pendaftaran) VALUES (%s, %s, 'Pending')", (id_kelas, id_anak))
                id_pendaftaran = cursor.lastrowid  # Ambil ID Auto Increment
            else:
                id_pendaftaran = pendaftaran['id_pendaftaran']
                # Kalau pendaftaran lama ini sebelumnya Ditolak/Berhenti dan sekarang
                # didaftarkan ulang, kembalikan statusnya ke Pending supaya menunggu
                # verifikasi pembayaran lagi dari admin
                if pendaftaran['status_pendaftaran'] in ('Ditolak', 'Berhenti'):
                    cursor.execute(
                        "UPDATE pendaftaran SET status_pendaftaran = 'Pending' WHERE id_pendaftaran = %s",
                        (id_pendaftaran,)
                    )
                
            # Langkah B: Cek apakah sudah ada tagihan yang 'Pending' untuk pendaftaran ini
            cursor.execute("SELECT id_pembayaran, tanggal_bayar FROM pembayaran WHERE id_pendaftaran = %s AND status_pembayaran = 'Pending'", (id_pendaftaran,))
            pembayaran_pending = cursor.fetchone()
            
            if not pembayaran_pending:
                # Jika belum ada tagihan Pending, buat tagihan baru
                jumlah_bayar = kelas_detail['harga']
                cursor.execute(
                    "INSERT INTO pembayaran (id_pendaftaran, jumlah_bayar, status_pembayaran) VALUES (%s, %s, 'Pending')",
                    (id_pendaftaran, jumlah_bayar)
                )
                id_pembayaran_db = cursor.lastrowid  # Ambil ID Auto Increment
                tanggal_bayar = datetime.now()
            else:
                id_pembayaran_db = pembayaran_pending['id_pembayaran']
                tanggal_bayar = pembayaran_pending['tanggal_bayar']
                
            # Simpan perubahan ke Database
            conn.commit()
            
            # Langkah C: Kode unik diturunkan otomatis dari id_pembayaran (lihat generate_kode_pembayaran)
            kode_pembayaran = generate_kode_pembayaran(id_pembayaran_db, tanggal_bayar)
            invoice_id = kode_pembayaran

            # Ambil foto profil user (untuk topbar), sama seperti route lain
            cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (session['id_users'],))
            user_row = cursor.fetchone()
            foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

            # Tampilkan ke halaman pembayaran
            return render_template('orangtua/pembayaran.html', 
                                   username=session.get('username'),
                                   foto_profil=foto_profil_user,
                                   kelas=kelas_detail,
                                   anak=detail_anak,
                                   id_pembayaran=id_pembayaran_db,
                                   kode_pembayaran=kode_pembayaran,
                                   invoice_id=invoice_id)

        except Exception as e:
            conn.rollback() # Batalkan transaksi jika terjadi error
            print(f"Error memuat halaman pembayaran: {e}")
            return "Terjadi kesalahan pada server", 500
        finally:
            cursor.close()
            conn.close()
            
    # 3. Jika diakses langsung tanpa lewat form kelas
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (session['id_users'],))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None
    finally:
        cursor.close()
        conn.close()

    return render_template('orangtua/pembayaran.html', username=session.get('username'), foto_profil=foto_profil_user)

@orangtua_bp.route('/riwayat_pembayaran')
def riwayat_pembayaran():
    # 1. Pastikan user (orang tua) sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    user_id = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1b. Ambil daftar anak & foto profil orang tua untuk topbar (konsisten dengan index.html)
        cursor.execute("SELECT id_anak, nama_lengkap, nama_panggilan, kelas FROM anak WHERE id_orangtua = %s ORDER BY created_at DESC", (user_id,))
        daftar_anak = cursor.fetchall()

        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (user_id,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else 'default_parent.png'

        # 2. Ambil SELURUH riwayat transaksi milik anak-anak dari orang tua yang login.
        #    Filter periode/status TIDAK dilakukan di sini lagi — semua data dikirim
        #    sekaligus ke halaman, lalu difilter di sisi browser (JS) agar mengganti
        #    dropdown tidak perlu reload halaman.
        query = """
            SELECT
                p.id_pembayaran,
                p.jumlah_bayar,
                p.tanggal_bayar,
                p.status_pembayaran,
                p.bukti_bayar,
                k.nama_kelas,
                a.nama_panggilan,
                a.nama_lengkap
            FROM pembayaran p
            JOIN pendaftaran pd ON p.id_pendaftaran = pd.id_pendaftaran
            JOIN anak a ON pd.id_anak = a.id_anak
            JOIN kelas k ON pd.id_kelas = k.id_kelas
            WHERE a.id_orangtua = %s
            ORDER BY p.tanggal_bayar DESC
        """
        cursor.execute(query, (user_id,))
        rows = cursor.fetchall()

        # 3. Normalisasi status & siapkan data untuk ditampilkan di tabel
        # `status_pembayaran` di DB cuma ENUM('Pending','Lunas','Ditolak'), tapi status yang
        # ditampilkan ke user dibagi jadi 4 berdasarkan kombinasi status_pembayaran + bukti_bayar:
        #   - Ditolak                       -> Gagal
        #   - Lunas                         -> Sukses (sudah divalidasi admin)
        #   - Pending + ada bukti_bayar     -> Pending (sudah kirim bukti, menunggu validasi admin)
        #   - Pending + bukti_bayar kosong  -> Menunggu Pembayaran (belum kirim bukti sama sekali)
        daftar_transaksi = []
        total_tahun_ini = 0
        total_pending = 0
        pending_count = 0
        jumlah_sukses = 0

        tahun_sekarang = datetime.now().year

        for row in rows:
            status_db = row.get('status_pembayaran') or 'Pending'
            ada_bukti_bayar = bool(row.get('bukti_bayar'))

            if status_db == 'Lunas':
                status_kategori = 'sukses'
                status_label = 'Sukses'
                jumlah_sukses += 1
                if row.get('tanggal_bayar') and row['tanggal_bayar'].year == tahun_sekarang:
                    total_tahun_ini += float(row['jumlah_bayar'] or 0)
            elif status_db == 'Ditolak':
                status_kategori = 'gagal'
                status_label = 'Gagal'
            elif status_db == 'Pending' and ada_bukti_bayar:
                status_kategori = 'pending'
                status_label = 'Pending'
                total_pending += float(row['jumlah_bayar'] or 0)
                pending_count += 1
            else:  # 'Pending' tanpa bukti_bayar sama sekali
                status_kategori = 'menunggu'
                status_label = 'Menunggu Pembayaran'
                total_pending += float(row['jumlah_bayar'] or 0)
                pending_count += 1

            daftar_transaksi.append({
                'id_pembayaran': row['id_pembayaran'],
                'kode_pembayaran': generate_kode_pembayaran(row['id_pembayaran'], row.get('tanggal_bayar')),
                'nama_kelas': row.get('nama_kelas'),
                'nama_anak': row.get('nama_panggilan') or row.get('nama_lengkap'),
                'jumlah_bayar': row.get('jumlah_bayar') or 0,
                'tanggal': row['tanggal_bayar'].strftime('%d %b %Y') if row.get('tanggal_bayar') else '-',
                'tanggal_iso': row['tanggal_bayar'].strftime('%Y-%m-%d') if row.get('tanggal_bayar') else '',
                'status_asli': status_label,
                'status_kategori': status_kategori,
            })

        total_transaksi = len(daftar_transaksi)
        success_rate = round((jumlah_sukses / total_transaksi) * 100, 1) if total_transaksi else 0

        return render_template('orangtua/riwayat_transaksi.html',
                               username=session.get('username'),
                               daftar_anak=daftar_anak,
                               foto_profil=foto_profil_user,
                               daftar_transaksi=daftar_transaksi,
                               total_tahun_ini=total_tahun_ini,
                               total_pending=total_pending,
                               pending_count=pending_count,
                               success_rate=success_rate,
                               total_transaksi=total_transaksi)

    except Exception as e:
        print(f"Error memuat riwayat transaksi: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()


@orangtua_bp.route('/riwayat_pembayaran/detail/<int:id_pembayaran>', methods=['GET', 'POST'])
def detail_pembayaran(id_pembayaran):
    # 1. Pastikan user (orang tua) sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    user_id = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 2. Ambil detail transaksi, PASTIKAN transaksi ini memang milik anak dari
        #    orang tua yang sedang login (supaya tidak bisa lihat/upload punya orang lain)
        query = """
            SELECT
                p.id_pembayaran, p.jumlah_bayar, p.tanggal_bayar,
                p.status_pembayaran, p.bukti_bayar, p.keterangan,
                k.nama_kelas, k.hari_jadwal, k.jam_mulai, k.jam_selesai,
                a.nama_panggilan, a.nama_lengkap
            FROM pembayaran p
            JOIN pendaftaran pd ON p.id_pendaftaran = pd.id_pendaftaran
            JOIN anak a ON pd.id_anak = a.id_anak
            JOIN kelas k ON pd.id_kelas = k.id_kelas
            WHERE p.id_pembayaran = %s AND a.id_orangtua = %s
        """
        cursor.execute(query, (id_pembayaran, user_id))
        trx = cursor.fetchone()

        if not trx:
            flash('Transaksi tidak ditemukan.', 'error')
            return redirect(url_for('orangtua.riwayat_pembayaran'))

        # 3. Tentukan kategori status (logika sama persis dengan halaman riwayat)
        status_db = trx.get('status_pembayaran') or 'Pending'
        ada_bukti_bayar = bool(trx.get('bukti_bayar'))

        if status_db == 'Lunas':
            status_kategori = 'sukses'
        elif status_db == 'Ditolak':
            status_kategori = 'gagal'
        elif status_db == 'Pending' and ada_bukti_bayar:
            status_kategori = 'pending'
        else:
            status_kategori = 'menunggu'

        # 4. Proses upload bukti bayar (hanya berlaku saat status masih "menunggu")
        if request.method == 'POST':
            # Kalau request datang dari fetch/AJAX (misal dari halaman checkout
            # pembayaran.html), balas dengan JSON supaya user tetap di halaman
            # itu, bukan redirect ke halaman detail_pembayaran.
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            if status_kategori != 'menunggu':
                msg = 'Bukti pembayaran untuk transaksi ini sudah tidak bisa diupload lagi.'
                if is_ajax:
                    return jsonify(success=False, message=msg), 400
                flash(msg, 'error')
                return redirect(url_for('orangtua.detail_pembayaran', id_pembayaran=id_pembayaran))

            file = request.files.get('bukti_bayar')
            if not file or file.filename == '':
                msg = 'Silakan pilih file bukti pembayaran terlebih dahulu.'
                if is_ajax:
                    return jsonify(success=False, message=msg), 400
                flash(msg, 'error')
                return redirect(url_for('orangtua.detail_pembayaran', id_pembayaran=id_pembayaran))

            if not ekstensi_valid(file.filename):
                msg = 'Format file tidak didukung. Gunakan JPG, PNG, atau PDF.'
                if is_ajax:
                    return jsonify(success=False, message=msg), 400
                flash(msg, 'error')
                return redirect(url_for('orangtua.detail_pembayaran', id_pembayaran=id_pembayaran))

            try:
                # Mengunggah ke Cloudinary
                # resource_type="auto" sangat penting karena file bisa berupa PDF!
                upload_result = cloudinary.uploader.upload(
                    file,
                    folder="tec_portal/bukti_bayar",
                    resource_type="auto" 
                )
                url_bukti = upload_result.get('secure_url')
                
                cursor.execute(
                    "UPDATE pembayaran SET bukti_bayar = %s WHERE id_pembayaran = %s",
                    (url_bukti, id_pembayaran)
                )
                conn.commit()

                msg = 'Bukti pembayaran berhasil dikirim! Menunggu validasi dari admin.'
                if is_ajax:
                    return jsonify(success=True, message=msg, bukti_bayar=url_bukti)
                flash(msg, 'success')
            except Exception as e:
                conn.rollback()
                msg = f'Gagal mengunggah bukti pembayaran: {str(e)}'
                if is_ajax:
                    return jsonify(success=False, message=msg), 500
                flash(msg, 'error')

            return redirect(url_for('orangtua.detail_pembayaran', id_pembayaran=id_pembayaran))

        # 5. Siapkan data untuk ditampilkan (GET)
        jam_mulai = trx.get('jam_mulai')
        jam_selesai = trx.get('jam_selesai')

        data_trx = {
            'id_pembayaran': trx['id_pembayaran'],
            'kode_pembayaran': generate_kode_pembayaran(trx['id_pembayaran'], trx.get('tanggal_bayar')),
            'nama_kelas': trx.get('nama_kelas'),
            'hari_jadwal': trx.get('hari_jadwal'),
            'jam_mulai': str(jam_mulai)[:5] if jam_mulai else '',
            'jam_selesai': str(jam_selesai)[:5] if jam_selesai else '',
            'nama_anak': trx.get('nama_panggilan') or trx.get('nama_lengkap'),
            'jumlah_bayar': trx.get('jumlah_bayar') or 0,
            'tanggal': trx['tanggal_bayar'].strftime('%d %B %Y, %H:%M') if trx.get('tanggal_bayar') else '-',
            'bukti_bayar': trx.get('bukti_bayar'),
            'keterangan': trx.get('keterangan') or 'Admin tidak menyertakan alasan spesifik untuk penolakan ini. Silakan hubungi customer service TEC Portal untuk informasi lebih lanjut.',
        }

        # Ambil foto profil user (untuk topbar), sama seperti route lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (user_id,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        return render_template('orangtua/detail_pembayaran.html',
                               username=session.get('username'),
                               foto_profil=foto_profil_user,
                               trx=data_trx,
                               status_kategori=status_kategori)

    except Exception as e:
        conn.rollback()
        print(f"Error memuat detail pembayaran: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()


def _gabung_tanggal_jam(tanggal, jam):
    """
    Menggabungkan kolom `date` (tanggal) dan `time` (jam_mulai/jam_selesai) dari MySQL
    menjadi satu objek datetime. Driver MySQL biasanya mengembalikan kolom TIME
    sebagai timedelta, jadi kita tangani dua kemungkinan tipe sekaligus.
    """
    if isinstance(jam, timedelta):
        return datetime.combine(tanggal, datetime.min.time()) + jam
    return datetime.combine(tanggal, jam)


def _format_jam(jam):
    """Format kolom TIME (timedelta ATAU time) menjadi string 'HH:MM'."""
    if isinstance(jam, timedelta):
        total_menit = jam.seconds // 60
        return f"{total_menit // 60:02d}:{total_menit % 60:02d}"
    return jam.strftime('%H:%M')


def _ambil_daftar_jadwal(cursor, id_anak, nama_anak=None):
    """
    Ambil semua kelas yang diikuti seorang anak beserta sesi_kelas-nya
    (dipakai bersama oleh halaman Jadwal Belajar dan sinkronisasi Google
    Calendar, supaya logikanya tidak dobel).

    `nama_anak` opsional -- kalau diisi, setiap item jadwal akan ditandai
    milik anak yang mana (dipakai saat menampilkan jadwal gabungan "Semua Anak").
    """
    query_jadwal = """
        SELECT
            sk.id_sesi, sk.tanggal, sk.topik_pembahasan,
            k.id_kelas, k.nama_kelas, k.hari_jadwal, k.jam_mulai, k.jam_selesai, k.status_kelas,
            k.tanggal_berakhir,
            u.username AS nama_pengajar, pd.tanggal_daftar
        FROM pendaftaran pd
        JOIN kelas k ON pd.id_kelas = k.id_kelas
        JOIN users u ON k.id_pengajar = u.id_users
        LEFT JOIN sesi_kelas sk ON sk.id_kelas = k.id_kelas
        WHERE pd.id_anak = %s AND pd.status_pendaftaran = 'Aktif'
        ORDER BY (sk.tanggal IS NULL) ASC, sk.tanggal ASC, k.jam_mulai ASC
    """
    cursor.execute(query_jadwal, (id_anak,))
    rows = cursor.fetchall()

    hari_map = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    bulan_map = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
                 7: 'Jul', 8: 'Agu', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Des'}
    sekarang = datetime.now()

    daftar_jadwal = []
    for row in rows:
        tanggal = row['tanggal']

        if tanggal is not None:
            # Kelas ini sudah punya sesi terjadwal dengan tanggal pasti (tabel sesi_kelas)
            mulai_dt = _gabung_tanggal_jam(tanggal, row['jam_mulai'])
            selesai_dt = _gabung_tanggal_jam(tanggal, row['jam_selesai'])

            # Tentukan status sesi (Akan Datang / Sedang Berlangsung / Selesai) secara dinamis
            if sekarang < mulai_dt:
                status_sesi = 'Akan Datang'
            elif mulai_dt <= sekarang <= selesai_dt:
                status_sesi = 'Sedang Berlangsung'
            else:
                status_sesi = 'Selesai'

            hari_display = hari_map[tanggal.weekday()]
            tanggal_display = f"{tanggal.day:02d} {bulan_map[tanggal.month]}"
        else:
            # Kelas sudah terdaftar (pendaftaran Aktif) tapi belum ada sesi_kelas
            # spesifik yang diinput -> tampilkan sebagai jadwal rutin mingguan
            status_sesi = 'Terjadwal Rutin'
            hari_display = row['hari_jadwal']
            tanggal_display = None

        daftar_jadwal.append({
            'id_sesi': row['id_sesi'],
            'id_kelas': row['id_kelas'],
            'id_anak': id_anak,
            'nama_anak': nama_anak,
            'hari': hari_display,
            'tanggal_display': tanggal_display,
            'tanggal_iso': tanggal.isoformat() if tanggal is not None else None,
            'jam_mulai': _format_jam(row['jam_mulai']),
            'jam_selesai': _format_jam(row['jam_selesai']),
            'nama_kelas': row['nama_kelas'],
            'nama_pengajar': row['nama_pengajar'],
            'topik': row['topik_pembahasan'],
            'status_kelas': row['status_kelas'],
            'status_sesi': status_sesi,
            # Dipakai buat membatasi kemunculan kelas "Terjadwal Rutin" -- jangan
            # tampil di tanggal sebelum anak terdaftar di kelas ini.
            'tanggal_daftar_iso': row['tanggal_daftar'].date().isoformat() if row['tanggal_daftar'] else None,
            # Dipakai buat membatasi kemunculan kelas "Terjadwal Rutin" -- jangan
            # tampil terus tanpa akhir; berhenti begitu melewati tanggal
            # berakhir kelas yang sebenarnya (kalau ada).
            'tanggal_berakhir_iso': row['tanggal_berakhir'].isoformat() if row['tanggal_berakhir'] else None,
        })

    return daftar_jadwal


def _kelompokkan_per_mapel(daftar_jadwal):
    """
    `_ambil_daftar_jadwal` sengaja mengembalikan SATU BARIS PER SESI (dipakai
    untuk kalender, supaya tiap sesi bisa ditaruh di tanggalnya masing-masing).
    Akibatnya kalau dipakai apa adanya untuk tampilan Daftar (kartu), satu mata
    pelajaran/kelas bisa muncul berkali-kali -- satu kartu per sesi.

    Fungsi ini meringkasnya jadi SATU KARTU PER MATA PELAJARAN (per kombinasi
    anak + kelas), dengan memilih sesi yang paling relevan untuk ditampilkan:
      1. Yang sedang berlangsung sekarang (kalau ada)
      2. Kalau tidak, sesi "Akan Datang" yang paling dekat tanggalnya
      3. Kalau belum ada sesi bertanggal sama sekali, tampilkan sebagai jadwal rutin
      4. Kalau semua sesi sudah lewat, tampilkan sesi "Selesai" yang paling baru
    """
    prioritas_status = {
        'Sedang Berlangsung': 0,
        'Akan Datang': 1,
        'Terjadwal Rutin': 2,
        'Selesai': 3,
    }

    terpilih = {}  # key: (id_anak, id_kelas) -> item jadwal terbaik

    for item in daftar_jadwal:
        kunci = (item['id_anak'], item['id_kelas'])
        kandidat_sekarang = terpilih.get(kunci)

        if kandidat_sekarang is None:
            terpilih[kunci] = item
            continue

        prio_baru = prioritas_status.get(item['status_sesi'], 99)
        prio_lama = prioritas_status.get(kandidat_sekarang['status_sesi'], 99)

        if prio_baru < prio_lama:
            terpilih[kunci] = item
        elif prio_baru == prio_lama:
            # Untuk status yang sama: "Akan Datang" ambil yang paling dekat (tanggal terkecil),
            # sedangkan "Selesai" ambil yang paling baru (tanggal terbesar)
            tgl_baru = item.get('tanggal_iso')
            tgl_lama = kandidat_sekarang.get('tanggal_iso')
            if tgl_baru and tgl_lama:
                if item['status_sesi'] == 'Selesai':
                    if tgl_baru > tgl_lama:
                        terpilih[kunci] = item
                else:
                    if tgl_baru < tgl_lama:
                        terpilih[kunci] = item

    return list(terpilih.values())


@orangtua_bp.route('/jadwal_belajar')
def jadwal_belajar():
    # 1. Pastikan user (orang tua/murid) sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    id_orangtua = session['id_users']
    selected_anak_id = request.args.get('anak_id')  # dikirim dari dropdown pilih anak

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 2. Ambil semua anak milik orang tua yang sedang login (untuk mengisi dropdown)
        # Hanya anak berstatus aktif -- anak nonaktif tidak bisa dilihat jadwalnya
        cursor.execute(
            "SELECT id_anak, nama_lengkap, nama_panggilan FROM anak WHERE id_orangtua = %s AND status_anak = 'Active' ORDER BY created_at DESC",
            (id_orangtua,)
        )
        daftar_anak = cursor.fetchall()

        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (id_orangtua,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else 'default_parent.png'

        anak_aktif = None
        daftar_jadwal = []
        mode_semua = False

        if daftar_anak:
            # 3. Tentukan anak mana yang datanya mau ditampilkan
            if selected_anak_id == 'semua':
                # Mode gabungan: tampilkan jadwal SEMUA anak jadi satu kalender
                mode_semua = True
                for anak in daftar_anak:
                    nama_anak = anak['nama_panggilan'] or anak['nama_lengkap']
                    daftar_jadwal.extend(
                        _ambil_daftar_jadwal(cursor, anak['id_anak'], nama_anak=nama_anak)
                    )
            else:
                if selected_anak_id:
                    anak_aktif = next(
                        (a for a in daftar_anak if str(a['id_anak']) == str(selected_anak_id)),
                        None
                    )
                if not anak_aktif:
                    # Default: anak pertama (baru pertama kali buka halaman / anak_id tidak valid)
                    anak_aktif = daftar_anak[0]

                # 4. Ambil semua kelas + sesi milik anak yang aktif dipilih
                nama_anak = anak_aktif['nama_panggilan'] or anak_aktif['nama_lengkap']
                daftar_jadwal = _ambil_daftar_jadwal(cursor, anak_aktif['id_anak'], nama_anak=nama_anak)

        # daftar_jadwal (1 baris per sesi) dipakai untuk KALENDER.
        # daftar_mapel (1 kartu per mata pelajaran) dipakai untuk tampilan DAFTAR.
        daftar_mapel = _kelompokkan_per_mapel(daftar_jadwal)

        return render_template('orangtua/jadwal_belajar.html',
                               username=session.get('username'),
                               daftar_anak=daftar_anak,
                               anak_aktif=anak_aktif,
                               mode_semua=mode_semua,
                               foto_profil=foto_profil_user,
                               daftar_jadwal=daftar_jadwal,
                               daftar_mapel=daftar_mapel,
                               google_calendar_connected=is_connected(id_orangtua))

    except Exception as e:
        print(f"Error memuat jadwal belajar: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()


@orangtua_bp.route('/jadwal_belajar/detail_kelas/<id_kelas>')
def detail_kelas(id_kelas):
    # Halaman ini menampilkan detail sebuah kelas (daftar siswa & rencana
    # pembelajaran) versi orang tua -- read-only, tanpa fitur absensi/materi
    # yang jadi kewenangan pengajar.
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    id_orangtua = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    kelas_data = None
    daftar_siswa = []
    daftar_sesi = []
    foto_profil_user = 'default_parent.png'

    try:
        # Pastikan salah satu anak dari orang tua ini memang terdaftar aktif
        # di kelas ini, supaya orang tua tidak bisa mengintip kelas anak lain
        # yang tidak ada hubungannya dengan mereka. Anak yang statusnya
        # dinonaktifkan juga tidak boleh dipakai untuk mengakses jadwal ini.
        cursor.execute("""
            SELECT 1 FROM pendaftaran p
            JOIN anak a ON p.id_anak = a.id_anak
            WHERE p.id_kelas = %s AND a.id_orangtua = %s AND a.status_anak = 'Active' AND p.status_pendaftaran = 'Aktif'
            LIMIT 1
        """, (id_kelas, id_orangtua))
        akses_valid = cursor.fetchone()

        if not akses_valid:
            flash('Anda tidak memiliki akses ke kelas ini.', 'error')
            return redirect(url_for('orangtua.jadwal_belajar'))

        # 1. Info kelas
        cursor.execute("""
            SELECT k.id_kelas, k.nama_kelas, k.hari_jadwal, k.jam_mulai, k.jam_selesai, k.status_kelas,
                   u.username AS nama_pengajar
            FROM kelas k
            LEFT JOIN users u ON k.id_pengajar = u.id_users
            WHERE k.id_kelas = %s
        """, (id_kelas,))
        kelas_data = cursor.fetchone()

        if not kelas_data:
            flash('Kelas tidak ditemukan.', 'error')
            return redirect(url_for('orangtua.jadwal_belajar'))

        # Konversi jam (timedelta) jadi string HH:MM
        if kelas_data['jam_mulai'] and hasattr(kelas_data['jam_mulai'], 'total_seconds'):
            total_sec = int(kelas_data['jam_mulai'].total_seconds())
            kelas_data['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
        if kelas_data['jam_selesai'] and hasattr(kelas_data['jam_selesai'], 'total_seconds'):
            total_sec = int(kelas_data['jam_selesai'].total_seconds())
            kelas_data['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

        # 2. Daftar siswa yang terdaftar aktif di kelas ini
        cursor.execute("""
            SELECT a.nama_lengkap, a.nama_panggilan, a.sekolah_asal, a.kelas
            FROM pendaftaran p
            JOIN anak a ON p.id_anak = a.id_anak
            WHERE p.id_kelas = %s AND p.status_pendaftaran = 'Aktif'
            ORDER BY a.nama_lengkap ASC
        """, (id_kelas,))
        daftar_siswa = cursor.fetchall()

        # 3. Rencana pembelajaran (daftar sesi)
        cursor.execute("""
            SELECT id_sesi, sesi_ke, tanggal, topik_pembahasan
            FROM sesi_kelas
            WHERE id_kelas = %s
            ORDER BY sesi_ke ASC
        """, (id_kelas,))
        daftar_sesi = cursor.fetchall()

        # Foto profil untuk topbar, konsisten dengan halaman lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (id_orangtua,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else 'default_parent.png'

    except Exception as e:
        print(f"Error pada detail kelas (orangtua): {e}")
        flash('Terjadi kesalahan saat memuat detail kelas.', 'error')
        return redirect(url_for('orangtua.jadwal_belajar'))
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'orangtua/detail_kelas.html',
        kelas=kelas_data,
        daftar_siswa=daftar_siswa,
        daftar_sesi=daftar_sesi,
        today=date.today(),
        username=session.get('username'),
        foto_profil=foto_profil_user
    )


@orangtua_bp.route('/jadwal_belajar/detail_sesi/<int:id_sesi>')
def detail_sesi(id_sesi):
    # Versi read-only untuk orang tua: melihat topik & materi yang sudah
    # diinput pengajar untuk sesi ini. Tidak ada tombol edit/upload di sini.
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    id_orangtua = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Ambil data sesi beserta info kelas & pengajarnya
        cursor.execute("""
            SELECT
                sk.id_sesi, sk.id_kelas, sk.sesi_ke, sk.tanggal, sk.topik_pembahasan,
                k.nama_kelas, u.username AS nama_pengajar
            FROM sesi_kelas sk
            JOIN kelas k ON sk.id_kelas = k.id_kelas
            LEFT JOIN users u ON k.id_pengajar = u.id_users
            WHERE sk.id_sesi = %s
        """, (id_sesi,))
        sesi = cursor.fetchone()

        if not sesi:
            flash('Sesi tidak ditemukan.', 'error')
            return redirect(url_for('orangtua.jadwal_belajar'))

        # Pastikan salah satu anak dari orang tua ini memang terdaftar aktif
        # di kelas dari sesi ini, sebelum mengizinkan akses. Anak yang
        # dinonaktifkan juga tidak boleh dipakai untuk mengakses sesi ini.
        cursor.execute("""
            SELECT 1 FROM pendaftaran p
            JOIN anak a ON p.id_anak = a.id_anak
            WHERE p.id_kelas = %s AND a.id_orangtua = %s AND a.status_anak = 'Active' AND p.status_pendaftaran = 'Aktif'
            LIMIT 1
        """, (sesi['id_kelas'], id_orangtua))
        akses_valid = cursor.fetchone()

        if not akses_valid:
            flash('Anda tidak memiliki akses ke sesi ini.', 'error')
            return redirect(url_for('orangtua.jadwal_belajar'))

        # 2. Ambil daftar materi pembelajaran untuk sesi ini
        cursor.execute("""
            SELECT id_materi, judul_materi, deskripsi, file_materi, created_at
            FROM materi_belajar
            WHERE id_sesi = %s
            ORDER BY created_at DESC
        """, (id_sesi,))
        daftar_materi = cursor.fetchall()

        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (id_orangtua,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else 'default_parent.png'

        kelas = {'id_kelas': sesi['id_kelas'], 'nama_kelas': sesi['nama_kelas'], 'nama_pengajar': sesi['nama_pengajar']}

        return render_template(
            'orangtua/detail_sesi.html',
            sesi=sesi,
            kelas=kelas,
            daftar_materi=daftar_materi,
            username=session.get('username'),
            foto_profil=foto_profil_user
        )

    except Exception as e:
        print(f"Error pada detail sesi (orangtua): {e}")
        flash('Gagal memuat data sesi.', 'error')
        return redirect(url_for('orangtua.jadwal_belajar'))
    finally:
        cursor.close()
        conn.close()


@orangtua_bp.route('/google_calendar/connect')
def google_calendar_connect():
    """Mulai alur OAuth: redirect orang tua ke consent screen Google."""
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    try:
        auth_url, state = get_authorization_url()
    except GoogleCalendarNotConfigured as e:
        flash(str(e), 'error')
        return redirect(url_for('orangtua.jadwal_belajar'))

    session['gcal_oauth_state'] = state
    session['gcal_return_to'] = request.args.get('next') or url_for('orangtua.jadwal_belajar')
    return redirect(auth_url)


@orangtua_bp.route('/google_calendar/oauth2callback')
def google_calendar_callback():
    """Google redirect ke sini setelah orang tua menyetujui/menolak akses."""
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    return_to = session.pop('gcal_return_to', None) or url_for('orangtua.jadwal_belajar')
    state = session.pop('gcal_oauth_state', None)

    if request.args.get('error'):
        flash('Menghubungkan Google Calendar dibatalkan.', 'error')
        return redirect(return_to)

    try:
        creds = exchange_code_for_credentials(state, request.url)
        save_credentials(session['id_users'], creds)
        flash('Google Calendar berhasil terhubung.', 'success')
    except Exception as e:
        print(f"Gagal menghubungkan Google Calendar: {e}")
        flash('Gagal menghubungkan Google Calendar. Silakan coba lagi.', 'error')

    return redirect(return_to)


@orangtua_bp.route('/google_calendar/disconnect', methods=['POST'])
def google_calendar_disconnect():
    if 'id_users' not in session or session.get('role') != 'murid':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    disconnect(session['id_users'])
    return jsonify({'success': True})


@orangtua_bp.route('/google_calendar/sync', methods=['POST'])
def google_calendar_sync():
    """Dipanggil oleh tombol 'Sinkronisasi Kalender' di halaman Jadwal Belajar."""
    if 'id_users' not in session or session.get('role') != 'murid':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    id_orangtua = session['id_users']
    selected_anak_id = request.args.get('anak_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id_anak, nama_lengkap, nama_panggilan FROM anak WHERE id_orangtua = %s AND status_anak = 'Active' ORDER BY created_at DESC",
            (id_orangtua,)
        )
        daftar_anak = cursor.fetchall()
        if not daftar_anak:
            return jsonify({'success': False, 'message': 'Belum ada data anak terdaftar.'}), 400

        anak_aktif = next(
            (a for a in daftar_anak if str(a['id_anak']) == str(selected_anak_id)),
            daftar_anak[0]
        )

        daftar_jadwal = _ambil_daftar_jadwal(cursor, anak_aktif['id_anak'])

        hasil = sync_jadwal_to_calendar(
            id_orangtua, daftar_jadwal,
            nama_anak=anak_aktif['nama_panggilan'] or anak_aktif['nama_lengkap']
        )
        return jsonify({'success': True, **hasil})

    except GoogleCalendarNotConnected:
        return jsonify({'success': False, 'code': 'NOT_CONNECTED', 'message': 'Belum terhubung ke Google Calendar.'}), 409
    except GoogleCalendarNotConfigured as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        print(f"Error sinkronisasi Google Calendar: {e}")
        return jsonify({'success': False, 'message': 'Terjadi kesalahan pada server.'}), 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/presensi')
def presensi():
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    id_orangtua = session['id_users']
    selected_anak_id = request.args.get('anak_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (id_orangtua,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        # 1. Ambil semua anak milik orang tua ini (untuk dropdown pilih anak)
        # Hanya yang aktif -- anak nonaktif tidak bisa dilihat presensinya
        cursor.execute(
            "SELECT id_anak, nama_lengkap, nama_panggilan FROM anak WHERE id_orangtua = %s AND status_anak = 'Active' ORDER BY created_at DESC",
            (id_orangtua,)
        )
        daftar_anak = cursor.fetchall()

        anak_aktif = None
        daftar_presensi = []
        total_hadir = total_izin = total_sakit = total_alpa = 0
        persentase_kehadiran = 0

        if daftar_anak:
            if selected_anak_id:
                anak_aktif = next((a for a in daftar_anak if str(a['id_anak']) == str(selected_anak_id)), None)
            if not anak_aktif:
                anak_aktif = daftar_anak[0]

            # 2. Ambil seluruh riwayat presensi anak ini, dari semua kelas yang pernah/sedang diikuti
            cursor.execute("""
                SELECT 
                    pr.id_presensi, pr.status_kehadiran, pr.catatan,
                    sk.tanggal, sk.sesi_ke, sk.topik_pembahasan,
                    k.id_kelas, k.nama_kelas, k.jam_mulai, k.jam_selesai
                FROM presensi pr
                JOIN sesi_kelas sk ON pr.id_sesi = sk.id_sesi
                JOIN kelas k ON sk.id_kelas = k.id_kelas
                JOIN pendaftaran pd ON pr.id_pendaftaran = pd.id_pendaftaran
                WHERE pd.id_anak = %s
                ORDER BY sk.tanggal DESC, k.jam_mulai DESC
            """, (anak_aktif['id_anak'],))
            daftar_presensi = cursor.fetchall()

            # Konversi jam_mulai & jam_selesai dari timedelta (tipe TIME di MySQL) ke string "HH:MM"
            for p in daftar_presensi:
                for kolom_jam in ('jam_mulai', 'jam_selesai'):
                    if p.get(kolom_jam) and hasattr(p[kolom_jam], 'total_seconds'):
                        total_sec = int(p[kolom_jam].total_seconds())
                        p[kolom_jam] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

            # 3. Hitung ringkasan statistik dari data riil di atas
            for p in daftar_presensi:
                if p['status_kehadiran'] == 'Hadir':
                    total_hadir += 1
                elif p['status_kehadiran'] == 'Izin':
                    total_izin += 1
                elif p['status_kehadiran'] == 'Sakit':
                    total_sakit += 1
                elif p['status_kehadiran'] == 'Alpa':
                    total_alpa += 1

            total_sesi_tercatat = len(daftar_presensi)
            if total_sesi_tercatat > 0:
                persentase_kehadiran = round((total_hadir / total_sesi_tercatat) * 100)

        nama_anak_aktif = None
        if anak_aktif:
            nama_anak_aktif = anak_aktif['nama_panggilan'] or anak_aktif['nama_lengkap']

        return render_template('orangtua/presensi.html',
                               username=session.get('username'),
                               foto_profil=foto_profil_user,
                               daftar_anak=daftar_anak,
                               anak_aktif=anak_aktif,
                               nama_anak_aktif=nama_anak_aktif,
                               daftar_presensi=daftar_presensi,
                               total_hadir=total_hadir,
                               total_izin=total_izin,
                               total_sakit=total_sakit,
                               total_alpa=total_alpa,
                               total_sesi_tercatat=len(daftar_presensi),
                               persentase_kehadiran=persentase_kehadiran)

    except Exception as e:
        print(f"Error memuat presensi: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/reports')
def reports():
    if 'id_users' not in session:
        return redirect(url_for('orangtua.halaman_portal_orangtua')) # Sesuaikan dengan nama route login Anda
    
    id_orangtua = session['id_users']
    child_id_req = request.args.get('child_id') # Menangkap ID anak dari dropdown frontend
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 2. Ambil semua daftar anak yang dimiliki oleh orang tua yang sedang login
        # (hanya yang aktif -- anak nonaktif tidak bisa dilihat laporan/jadwalnya)
        cursor.execute("SELECT id_anak, nama_lengkap, nama_panggilan FROM anak WHERE id_orangtua = %s AND status_anak = 'Active'", (id_orangtua,))
        daftar_anak = cursor.fetchall()

        # Ambil foto profil user (untuk topbar), sama seperti route lain
        cursor.execute("SELECT foto_profil FROM users WHERE id_users = %s", (id_orangtua,))
        user_row = cursor.fetchone()
        foto_profil_user = user_row['foto_profil'] if user_row and user_row['foto_profil'] else None

        if not daftar_anak:
            # Jika orang tua belum memiliki data anak terdaftar
            return render_template('orangtua/reports.html', daftar_anak=[], anak_terpilih=None, jadwal=[],
                                   username=session.get('username'), foto_profil=foto_profil_user)
        
        # 3. Tentukan anak mana yang sedang dipilih/aktif dilihat
        anak_terpilih = None
        if child_id_req:
            # Cari data anak yang ID-nya sesuai dengan kiriman dropdown
            anak_terpilih = next((a for a in daftar_anak if str(a['id_anak']) == str(child_id_req)), daftar_anak[0])
        else:
            # Default ke anak pertama jika baru pertama kali buka halaman
            anak_terpilih = daftar_anak[0]
            
        # 4. QUERY JADWAL BELAJAR BERDASARKAN ANAK YANG TERPILIH
        # (Contoh query ini bisa disesuaikan dengan struktur tabel kelas/jadwal Anda nanti)
        # Untuk saat ini kita ambil data jadwal kelas berdasarkan id_anak tersebut
        query_jadwal = """
            SELECT * FROM jadwal_belajar 
            WHERE id_anak = %s 
            ORDER BY tanggal ASC
        """
        # cursor.execute(query_jadwal, (anak_terpilih['id_anak'],))
        # jadwal = cursor.fetchall()
        
        # Fallback data dummy jika tabel jadwal belajar sesungguhnya belum Anda buat di MySQL:
        jadwal = [] 

        return render_template('orangtua/reports.html', 
                               daftar_anak=daftar_anak, 
                               anak_terpilih=anak_terpilih,
                               jadwal=jadwal,
                               username=session.get('username'),
                               foto_profil=foto_profil_user)
                               
    except Exception as e:
        print(f"Error pada halaman reports: {e}")
        return "Terjadi kesalahan pada server.", 500
    finally:
        cursor.close()
        conn.close()

@orangtua_bp.route('/pengaturan')
def pengaturan():
    # Pastikan user sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    user_id = session['id_users']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Ambil data user yang sedang login
        cursor.execute("SELECT * FROM users WHERE id_users = %s", (user_id,))
        user_data = cursor.fetchone()
        
        # 2. Ambil data anak untuk mengisi dropdown di Topbar (agar konsisten dengan index)
        cursor.execute("SELECT id_anak, nama_lengkap, nama_panggilan, kelas FROM anak WHERE id_orangtua = %s", (user_id,))
        daftar_anak = cursor.fetchall()
        
        # Tampilkan ke halaman HTML
        return render_template('orangtua/pengaturan.html', 
                               username=session.get('username'),
                               user=user_data,
                               daftar_anak=daftar_anak)
                               
    except Exception as e:
        print(f"Error memuat halaman pengaturan: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()


@orangtua_bp.route('/update_pengaturan', methods=['POST'])
def update_pengaturan():
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    user_id = session['id_users']
    
    # Ambil data dari form input
    nama_lengkap = request.form.get('nama_lengkap')
    no_telp = request.form.get('no_telp')
    alamat = request.form.get('alamat')
    
    # Checkbox Toggle
    notif_tagihan = 1 if request.form.get('notif_tagihan') == '1' else 0
    
    # Tangani Upload Foto Profil ke Cloudinary
    foto = request.files.get('foto_profil')
    url_foto_cloudinary = None
    
    if foto and foto.filename != '':
        if foto_valid(foto.filename):
            try:
                upload_result = cloudinary.uploader.upload(
                    foto,
                    folder="tec_portal/foto_user"
                )
                url_foto_cloudinary = upload_result.get('secure_url')
            except Exception as e:
                flash(f'Gagal mengunggah foto profil: {str(e)}', 'error')
                return redirect(url_for('orangtua.pengaturan'))
        else:
            flash('Format foto tidak valid. Gunakan JPG atau PNG.', 'error')
            return redirect(url_for('orangtua.pengaturan'))
            
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if url_foto_cloudinary:
            # Update data user beserta foto baru (sekarang berupa URL)
            cursor.execute("""
                UPDATE users 
                SET nama_lengkap = %s, no_telp = %s, alamat = %s, notif_tagihan = %s, foto_profil = %s
                WHERE id_users = %s
            """, (nama_lengkap, no_telp, alamat, notif_tagihan, url_foto_cloudinary, user_id))
        else:
            # Update data user tanpa mengubah foto profil lama
            cursor.execute("""
                UPDATE users 
                SET nama_lengkap = %s, no_telp = %s, alamat = %s, notif_tagihan = %s
                WHERE id_users = %s
            """, (nama_lengkap, no_telp, alamat, notif_tagihan, user_id))
            
        conn.commit()
        flash('Pengaturan akun berhasil disimpan!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error update pengaturan: {e}")
        flash('Terjadi kesalahan saat menyimpan pengaturan.', 'error')
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('orangtua.pengaturan'))
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
import uuid, random
from db import get_db_connection
from extensions import mail
from flask_mail import Message

orangtua_bp = Blueprint('orangtua', __name__,)

@orangtua_bp.route('/')
@orangtua_bp.route('/index')
def index():
    # Pastikan user sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    user_id = session['id_users']
    
    # Menangkap ID anak dari pilihan dropdown (URL: /index?anak_id=123)
    selected_anak_id = request.args.get('anak_id') 
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Ambil daftar anak milik orang tua ini untuk mengisi dropdown
        cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s ORDER BY created_at DESC", (user_id,))
        daftar_anak = cursor.fetchall()
        
        # Tentukan anak mana yang datanya akan ditampilkan (anak_aktif)
        anak_aktif = None
        
        if daftar_anak:
            if selected_anak_id:
                # Cari anak yang ID-nya cocok dengan pilihan dropdown
                for anak in daftar_anak:
                    if str(anak['id_anak']) == str(selected_anak_id):
                        anak_aktif = anak
                        break
            
            # Jika baru pertama kali login (belum memilih dropdown), otomatis pilih anak pertama
            if not anak_aktif:
                anak_aktif = daftar_anak[0]
                
        # (Opsional: Di masa depan, Anda bisa tambahkan query untuk mengambil presensi/jadwal kelas anak_aktif di sini)

        return render_template('orangtua/index.html', 
                               username=session.get('username'), 
                               daftar_anak=daftar_anak, 
                               anak_aktif=anak_aktif)
                               
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

@orangtua_bp.route('/verify_otp_page')
def verify_otp_page():
    return render_template('orangtua/register_orangtua_otp.html')

@orangtua_bp.route('/proses_regtister/snk', methods=['GET'])
def halaman_syarat_ketentuan():
    return render_template('orangtua/snk.html')

@orangtua_bp.route('/proses_regtister/kebijakan_privasi', methods=['GET'])
def halaman_kebijakan_privasi():
    return render_template('orangtua/kebijakan_privasi.html')

@orangtua_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('orangtua.halaman_portal_orangtua'))

@orangtua_bp.route('/manajemen_anak')
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
        
        return render_template('orangtua/child_management.html', daftar_anak=daftar_anak)
        
    except Exception as e:
        print(f"Error mengambil data anak: {e}")
        return "Terjadi kesalahan pada server", 500
    finally:
        cursor.close()
        conn.close()

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

@orangtua_bp.route('/kelas')
def kelas():
    return render_template('orangtua/kelas.html')

@orangtua_bp.route('/riwayat_pembayaran')
def riwayat_pembayaran():
    return render_template('orangtua/riwayat_transaksi.html')

@orangtua_bp.route('/jadwal_belajar')
def jadwal_belajar():
    return render_template('orangtua/jadwal_belajar.html')

@orangtua_bp.route('/presensi')
def presensi():
    return render_template('orangtua/presensi.html')

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
        cursor.execute("SELECT id_anak, nama_lengkap, nama_panggilan FROM anak WHERE id_orangtua = %s", (id_orangtua,))
        daftar_anak = cursor.fetchall()
        
        if not daftar_anak:
            # Jika orang tua belum memiliki data anak terdaftar
            return render_template('orangtua/reports.html', daftar_anak=[], anak_terpilih=None, jadwal=[])
        
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
                               jadwal=jadwal)
                               
    except Exception as e:
        print(f"Error pada halaman reports: {e}")
        return "Terjadi kesalahan pada server.", 500
    finally:
        cursor.close()
        conn.close()

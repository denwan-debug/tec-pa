from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import uuid, random, re
from db import get_db_connection
from extensions import mail
from flask_mail import Message

orangtua_bp = Blueprint('orangtua', __name__,)


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
            
            # 3. Kirim email
            try:
                msg = Message('Kode OTP Reset Password', recipients=[email])
                msg.body = f"Kode OTP untuk mereset kata sandi Anda adalah: {otp}\nBerlaku selama 5 menit."
                mail.send(msg)
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
def halaman_pendaftaran_kelas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT k.*, u.username AS nama_tutor,
        (SELECT COUNT(*) FROM pendaftaran p WHERE p.id_kelas = k.id_kelas) AS jumlah_siswa
        FROM kelas k
        LEFT JOIN users u ON k.id_pengajar = u.id_users
        WHERE k.status_kelas = 'Aktif'
    """
    cursor.execute(query)
    daftar_kelas = cursor.fetchall()
    
    # Format waktu jam_mulai dan jam_selesai jadi string HH:MM
    for k in daftar_kelas:
        if k['jam_mulai']:
            k['jam_mulai'] = str(k['jam_mulai'])[:5]
        if k['jam_selesai']:
            k['jam_selesai'] = str(k['jam_selesai'])[:5]

    cursor.close()
    conn.close()
    
    return render_template('orangtua/kelas.html', daftar_kelas=daftar_kelas, username=session.get('username'))

@orangtua_bp.route('/konfirmasi_kelas/<id_kelas>')
def konfirmasi_kelas(id_kelas):
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Ambil detail kelas yang diklik
        cursor.execute("SELECT * FROM kelas WHERE id_kelas = %s", (id_kelas,))
        detail_kelas = cursor.fetchone()
        
        # 2. Ambil daftar anak milik orang tua yang sedang login ini
        cursor.execute("SELECT * FROM anak WHERE id_orangtua = %s", (session['id_users'],))
        daftar_anak = cursor.fetchall()
        
        if not detail_kelas:
            flash('Kelas tidak ditemukan.', 'error')
            return redirect(url_for('orangtua.kelas'))
            
        # Tampilkan halaman konfirmasi dengan membawa data kelas dan daftar anak
        return render_template('orangtua/konfirmasi_kelas.html', 
                               username=session.get('username'),
                               kelas=detail_kelas,
                               daftar_anak=daftar_anak)
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
            SELECT k.*, u.username AS nama_tutor 
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

        return render_template('orangtua/konfirmasi_kelas.html',
                               kelas=kelas_detail,
                               daftar_anak=daftar_anak,
                               username=session.get('username'),
                               deskripsi=deskripsi_text,
                               kriteria_kelas=kriteria_kelas)

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
            cursor.execute("SELECT id_pendaftaran FROM pendaftaran WHERE id_kelas = %s AND id_anak = %s", (id_kelas, id_anak))
            pendaftaran = cursor.fetchone()
            
            if not pendaftaran:
                # Jika belum ada, buat pendaftaran baru
                cursor.execute("INSERT INTO pendaftaran (id_kelas, id_anak, status_pendaftaran) VALUES (%s, %s, 'Aktif')", (id_kelas, id_anak))
                id_pendaftaran = cursor.lastrowid  # Ambil ID Auto Increment
            else:
                id_pendaftaran = pendaftaran['id_pendaftaran']
                
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

            # Tampilkan ke halaman pembayaran
            return render_template('orangtua/pembayaran.html', 
                                   username=session.get('username'),
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
    return render_template('orangtua/pembayaran.html', username=session.get('username'))

@orangtua_bp.route('/riwayat_pembayaran')
def riwayat_pembayaran():
    # 1. Pastikan user (orang tua) sudah login
    if 'id_users' not in session or session.get('role') != 'murid':
        return redirect(url_for('orangtua.halaman_portal_orangtua'))

    user_id = session['id_users']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
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
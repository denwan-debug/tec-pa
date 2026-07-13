from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from db import get_db_connection
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
import random
from extensions import send_email

# Membuat blueprint untuk pengajar
pengajar_bp = Blueprint('pengajar', __name__)

@pengajar_bp.route('/login_pengajar_action', methods=['POST'])
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
            # Dukung dua kondisi:
            # 1. Password sudah di-hash (scrypt/pbkdf2) -- akun yang sudah pernah ganti/reset password
            # 2. Password masih plaintext -- akun lama yang belum pernah diubah sejak awal dibuat
            stored_password = pembimbing_data['password'] or ''
            password_valid = False

            if stored_password.startswith(('scrypt:', 'pbkdf2:')):
                try:
                    password_valid = check_password_hash(stored_password, password)
                except Exception as e:
                    print(f"Error saat memverifikasi hash password: {e}")
                    password_valid = False
            else:
                password_valid = (stored_password == password)

            if password_valid:
                
                # 4. Simpan data pengguna ke dalam session Flask
                session['user_id'] = pembimbing_data['id_users'] 
                session['role'] = pembimbing_data['nama_role']     # Berisi 'Pengajar'
                session['username'] = pembimbing_data['username'] # Menyimpan nama asli pembimbing
                session['foto_profil'] = pembimbing_data['foto_profil']
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

@pengajar_bp.route('/login_pengajar')
def login_pengajar():
    return render_template('pengajar/login_pengajar.html')

@pengajar_bp.route('/dashboard_pengajar')
def dashboard_pengajar():
    # 1. Proteksi Sesi Login Pengajar
    if 'user_id' not in session:
        return redirect(url_for('pengajar.login_pengajar'))
        
    pengajar_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 2. Hitung Statistik Ringkas Khusus Pengajar Ini
        # Total Kelas Aktif
        cursor.execute("SELECT COUNT(*) as total FROM kelas WHERE id_pengajar = %s AND status_kelas = 'Aktif'", (pengajar_id,))
        kelas_aktif = cursor.fetchone()['total'] or 0
        
        # Total Siswa Unik yang Diajar oleh Pengajar ini
        query_total_siswa = """
            SELECT COUNT(DISTINCT p.id_anak) as total 
            FROM pendaftaran p 
            JOIN kelas k ON p.id_kelas = k.id_kelas 
            WHERE k.id_pengajar = %s
        """
        cursor.execute(query_total_siswa, (pengajar_id,))
        total_siswa = cursor.fetchone()['total'] or 0
        
        # Total Semua Kelas (Aktif/Penuh/Selesai) milik pengajar ini
        cursor.execute("SELECT COUNT(*) as total FROM kelas WHERE id_pengajar = %s", (pengajar_id,))
        total_kelas = cursor.fetchone()['total'] or 0

        # 3. Query Ambil Daftar Kelas Milik Pengajar Ini
        query_kelas = """
            SELECT 
                k.id_kelas,
                k.nama_kelas,
                k.hari_jadwal,
                k.jam_mulai,
                k.jam_selesai,
                k.kapasitas_maksimal,
                k.status_kelas,
                (SELECT COUNT(*) FROM pendaftaran p WHERE p.id_kelas = k.id_kelas) AS jumlah_siswa
            FROM kelas k
            WHERE k.id_pengajar = %s
            ORDER BY k.created_at DESC
        """
        cursor.execute(query_kelas, (pengajar_id,))
        daftar_kelas = cursor.fetchall()
        
        # 4. Konversi format tipe data TIME (timedelta) dari MySQL menjadi string (HH:MM) agar tidak error
        for kelas in daftar_kelas:
            if kelas['jam_mulai'] and hasattr(kelas['jam_mulai'], 'total_seconds'):
                total_sec = int(kelas['jam_mulai'].total_seconds())
                kelas['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
            if kelas['jam_selesai'] and hasattr(kelas['jam_selesai'], 'total_seconds'):
                total_sec = int(kelas['jam_selesai'].total_seconds())
                kelas['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
                
        # 5. Kirim semua data ke Frontend HTML
        return render_template(
            'pengajar/dashboard_pengajar.html', 
            daftar_kelas=daftar_kelas,
            kelas_aktif=kelas_aktif,
            total_siswa=total_siswa,
            total_kelas=total_kelas
        )
        
    except Exception as e:
        print(f"Error pada dashboard pengajar: {e}")
        return render_template('pengajar/dashboard_pengajar.html', daftar_kelas=[], kelas_aktif=0, total_siswa=0, total_kelas=0)
    finally:
        cursor.close()
        conn.close()

@pengajar_bp.route('/kelas_pengajar')
def kelas_pengajar():
    if 'user_id' not in session:
        return redirect(url_for('pengajar.login_pengajar'))
        
    pengajar_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    daftar_kelas = [] # Inisialisasi list kosong di luar try
    
    try:
        query_kelas = """
            SELECT 
                k.id_kelas,
                k.nama_kelas,
                k.hari_jadwal,
                k.jam_mulai,
                k.jam_selesai,
                k.kapasitas_maksimal,
                k.status_kelas,
                (SELECT COUNT(*) FROM pendaftaran p WHERE p.id_kelas = k.id_kelas) AS jumlah_siswa
            FROM kelas k
            WHERE k.id_pengajar = %s
            ORDER BY k.created_at DESC
        """
        cursor.execute(query_kelas, (pengajar_id,))
        daftar_kelas = cursor.fetchall()
        
        for kelas in daftar_kelas:
            if kelas['jam_mulai'] and hasattr(kelas['jam_mulai'], 'total_seconds'):
                total_sec = int(kelas['jam_mulai'].total_seconds())
                kelas['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
            if kelas['jam_selesai'] and hasattr(kelas['jam_selesai'], 'total_seconds'):
                total_sec = int(kelas['jam_selesai'].total_seconds())
                kelas['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
                
    except Exception as e:
        print(f"Error pada database kelas pengajar: {e}")
    finally:
        cursor.close()
        conn.close()

    # SEKARANG DI LUAR TRY-EXCEPT: Memudahkan debugging template HTML
    return render_template('pengajar/kelas_pengajar.html', daftar_kelas=daftar_kelas)


# TAMBAHKAN ROUTE INI agar url_for di HTML tidak error
@pengajar_bp.route('/detail_kelas/<id_kelas>')
def detail_kelas(id_kelas):
    if 'user_id' not in session:
        return redirect(url_for('pengajar.login_pengajar'))
        
    # DEBUG 1: Pastikan ID yang diterima dari HTML sudah benar
    print(f"==> Menerima request detail_kelas untuk ID: {id_kelas} (Tipe: {type(id_kelas)})")
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    detail_kelas_data = None
    daftar_siswa = []
    
    try:
        # 1. UBAH JOIN MENJADI LEFT JOIN DI SINI
        query_kelas = """
            SELECT 
                k.id_kelas,
                k.nama_kelas,
                k.hari_jadwal,
                k.jam_mulai,
                k.jam_selesai,
                k.kapasitas_maksimal,
                k.status_kelas,
                u.username AS nama_pengajar
            FROM kelas k
            LEFT JOIN users u ON k.id_pengajar = u.id_users 
            WHERE k.id_kelas = %s
        """
        cursor.execute(query_kelas, (id_kelas,))
        detail_kelas_data = cursor.fetchone()
        
        # 2. TAMBAHKAN PRINT INI UNTUK DEBUGGING (Cek di terminal VSCode/CMD Anda)
        print(f"Mencari Kelas ID: {id_kelas}")
        print(f"Hasil dari Database: {detail_kelas_data}")
        
        # Jika kelas tidak ditemukan, batalkan dan kembali ke daftar
        if not detail_kelas_data:
            print("Peringatan: Data kelas kosong! Melempar kembali ke menu awal.")
            return redirect(url_for('pengajar.kelas_pengajar'))
            
        # Konversi waktu
        if detail_kelas_data['jam_mulai'] and hasattr(detail_kelas_data['jam_mulai'], 'total_seconds'):
            total_sec = int(detail_kelas_data['jam_mulai'].total_seconds())
            detail_kelas_data['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
            
        if detail_kelas_data['jam_selesai'] and hasattr(detail_kelas_data['jam_selesai'], 'total_seconds'):
            total_sec = int(detail_kelas_data['jam_selesai'].total_seconds())
            detail_kelas_data['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"

        # Query daftar siswa
        # Query daftar siswa
        query_siswa = """
            SELECT 
                a.id_anak,
                a.nama_lengkap,
                a.nama_panggilan,
                a.jenis_kelamin,
                a.sekolah_asal, 
                a.kelas,
                p.status_pendaftaran,
                p.tanggal_daftar
            FROM pendaftaran p
            JOIN anak a ON p.id_anak = a.id_anak
            WHERE p.id_kelas = %s AND p.status_pendaftaran = 'Aktif'
        """
        cursor.execute(query_siswa, (id_kelas,))
        daftar_siswa = cursor.fetchall()
        
    except Exception as e:
        # DEBUG 3: Menangkap jika ada error sintaks SQL atau error koneksi
        print(f"!!! Error pada database detail kelas: {e}")
        return redirect(url_for('pengajar.kelas_pengajar'))
        
    finally:
        cursor.close()
        conn.close()
        
    return render_template('pengajar/detail_kelas.html', kelas=detail_kelas_data, daftar_siswa=daftar_siswa)



@pengajar_bp.route('/jadwal_pengajar')
def manajemen_jadwal():
    return render_template('pengajar/manajemen_jadwal.html')

@pengajar_bp.route('/laporan_pengajar')
def laporan_pengajar():
    return render_template('pengajar/manajemen_laporan.html')

@pengajar_bp.route('/profil_pengajar')
def profil_pengajar():
    # Proteksi Sesi
    if 'user_id' not in session:
        return redirect(url_for('pengajar.login_pengajar'))
        
    pengajar_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user_data = None
    try:
        # Mengambil data diri, abaikan notif_tagihan sesuai permintaan
        query = """
            SELECT username, nama_lengkap, email, no_telp, alamat, tempat_lahir, foto_profil 
            FROM users 
            WHERE id_users = %s
        """
        cursor.execute(query, (pengajar_id,))
        user_data = cursor.fetchone()
        
    except Exception as e:
        print(f"Error pada halaman profil pengajar: {e}")
    finally:
        cursor.close()
        conn.close()

    return render_template('pengajar/profil_pengajar.html', user=user_data)

from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

@pengajar_bp.route('/update_profil_pengajar', methods=['POST'])
def update_profil_pengajar():
    if 'user_id' not in session:
        return redirect(url_for('pengajar.login_pengajar'))
        
    pengajar_id = session['user_id']
    form_type = request.form.get('form_type')

    # ==================================================
    # FORM 1: Ganti Kata Sandi (kolom "Keamanan Akun")
    # ==================================================
    if form_type == 'ganti_password':
        password_lama = request.form.get('password_lama')
        password_baru = request.form.get('password_baru')
        konfirmasi_password = request.form.get('konfirmasi_password')

        if not password_lama or not password_baru or not konfirmasi_password:
            flash('Semua kolom kata sandi wajib diisi!', 'error')
            return redirect(url_for('pengajar.profil_pengajar'))

        if len(password_baru) < 8:
            flash('Kata sandi baru minimal 8 karakter!', 'error')
            return redirect(url_for('pengajar.profil_pengajar'))

        if password_baru != konfirmasi_password:
            flash('Konfirmasi kata sandi baru tidak cocok!', 'error')
            return redirect(url_for('pengajar.profil_pengajar'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT password FROM users WHERE id_users = %s", (pengajar_id,))
            user_row = cursor.fetchone()

            if not user_row or not check_password_hash(user_row['password'], password_lama):
                flash('Kata sandi saat ini salah!', 'error')
                return redirect(url_for('pengajar.profil_pengajar'))

            password_hash_baru = generate_password_hash(password_baru)
            cursor.execute("UPDATE users SET password = %s WHERE id_users = %s", (password_hash_baru, pengajar_id))
            conn.commit()
            flash('Kata sandi berhasil diperbarui!', 'success')

        except Exception as e:
            conn.rollback()
            print(f"Error saat ganti password: {e}")
            flash('Terjadi kesalahan saat memperbarui kata sandi.', 'error')
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('pengajar.profil_pengajar'))

    # ==================================================
    # FORM 2: Update Data Diri (kolom "Informasi Data Diri")
    # ==================================================
    nama_lengkap = request.form.get('nama_lengkap')
    tempat_lahir = request.form.get('tempat_lahir')
    no_telp = request.form.get('no_telp')
    alamat = request.form.get('alamat')
    
    # Tangkap file foto
    foto_file = request.files.get('foto_profil')
    nama_foto_baru = None
    
    # Jika ada file yang diunggah dan namanya tidak kosong
    if foto_file and foto_file.filename != '':
        allowed_extensions = ['png', 'jpg', 'jpeg']
        
        # Mengambil ekstensi file dengan memisahkan string berdasarkan titik
        ext = foto_file.filename.split('.')[-1].lower()
        
        if ext in allowed_extensions:
            nama_asli = secure_filename(foto_file.filename)
            nama_foto_baru = f"{pengajar_id}_{nama_asli}"
            
            # Menentukan path penyimpanan langsung ke static/img
            simpan_path = f"static/img/{nama_foto_baru}"
            
            # Simpan file ke direktori (pastikan folder static/img sudah dibuat manual!)
            foto_file.save(simpan_path)
        else:
            flash('Format foto tidak didukung. Gunakan JPG atau PNG.', 'error')
            return redirect(url_for('pengajar.profil_pengajar'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if nama_foto_baru:
            query = """
                UPDATE users 
                SET nama_lengkap = %s, tempat_lahir = %s, no_telp = %s, alamat = %s, foto_profil = %s 
                WHERE id_users = %s
            """
            cursor.execute(query, (nama_lengkap, tempat_lahir, no_telp, alamat, nama_foto_baru, pengajar_id))
        else:
            query = """
                UPDATE users 
                SET nama_lengkap = %s, tempat_lahir = %s, no_telp = %s, alamat = %s 
                WHERE id_users = %s
            """
            cursor.execute(query, (nama_lengkap, tempat_lahir, no_telp, alamat, pengajar_id))
            
        conn.commit()
        flash('Perubahan data berhasil disimpan!', 'success')

        if nama_foto_baru:
            session['foto_profil'] = nama_foto_baru
            session.modified = True
        
    except Exception as e:
        print(f"Error saat update profil: {e}")
        conn.rollback()
        flash('Gagal menyimpan perubahan. Silakan coba lagi.', 'error')
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('pengajar.profil_pengajar'))

@pengajar_bp.route('/forgot-password-pengajar', methods=['GET', 'POST'])
def forgot_password_pengajar():
    # Jika GET, tampilkan halaman form Lupa Password
    if request.method == 'GET':
        return render_template('pengajar/lupa_password_pengajar.html')

    # Jika POST, proses pencarian email
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({'message': 'Email wajib diisi.'}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Cari user berdasarkan email dan rolenya (R02 = Pengajar)
        cursor.execute("SELECT id_users FROM users WHERE email = %s AND role_id_role = 'R02'", (email,))
        user = cursor.fetchone()

        # Kalau email ini bukan akun Pengajar (atau tidak terdaftar sama sekali),
        # langsung tolak dengan pesan jelas -- jangan lanjut ke halaman OTP.
        if not user:
            cursor.close()
            conn.close()
            return jsonify({'message': 'Akun Pengajar dengan email ini tidak ditemukan!'}), 404

        otp = str(random.randint(100000, 999999))
        user_id = user['id_users']

        cursor.execute("""
            INSERT INTO user_otps (user_id_users, email, otp_code, expired_at, is_used)
            VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), 0)
        """, (user_id, email, otp))
        conn.commit()

        try:
            send_email(
                to=email,
                subject='Kode OTP Reset Password - TEC Pengajar',
                body=f"Kode OTP untuk mereset kata sandi akun Pengajar Anda adalah: {otp}\nBerlaku selama 5 menit."
            )
            print(f"[DEBUG] OTP Lupa Password Pengajar {otp} dikirim ke {email}")
        except Exception as e:
            print(f"Gagal mengirim email: {e}")

        cursor.close()
        conn.close()

        return jsonify({
            'message': 'Kode OTP telah dikirim ke email Anda.',
            'redirect': url_for('pengajar.verify_reset_otp_pengajar', email=email)
        }), 200


@pengajar_bp.route('/verify-reset-otp-pengajar', methods=['GET', 'POST'])
def verify_reset_otp_pengajar():
    # Menampilkan halaman input OTP
    if request.method == 'GET':
        email = request.args.get('email')
        if not email:
            return redirect(url_for('pengajar.forgot_password_pengajar'))
        return render_template('pengajar/otp_pengajar.html', email=email)

    # Memproses validasi kode OTP
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        otp = data.get('otp')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # PENTING: JOIN ke tabel users dan pastikan role-nya R02 (Pengajar).
        # Ini mencegah OTP milik akun lain (Orang Tua, dll) yang kebetulan
        # memakai email sama ikut dianggap valid di alur reset password Pengajar.
        cursor.execute("""
            SELECT o.* FROM user_otps o
            JOIN users u ON o.user_id_users = u.id_users
            WHERE o.email = %s AND o.otp_code = %s AND o.is_used = 0 AND o.expired_at > NOW()
              AND u.role_id_role = 'R02'
            ORDER BY o.id DESC LIMIT 1
        """, (email, otp))
        otp_data = cursor.fetchone()

        if otp_data:
            cursor.execute("UPDATE user_otps SET is_used = 1 WHERE id = %s", (otp_data['id'],))
            conn.commit()

            # Tandai di sesi bahwa email ini sudah tervalidasi OTP-nya untuk reset password
            session['reset_email_pengajar'] = email

            cursor.close()
            conn.close()

            return jsonify({
                'message': 'OTP Valid. Silakan buat password baru.',
                'redirect': url_for('pengajar.reset_password_pengajar')
            }), 200
        else:
            cursor.close()
            conn.close()
            return jsonify({'message': 'Kode OTP salah atau telah kadaluarsa!'}), 400


@pengajar_bp.route('/reset-password-pengajar', methods=['GET', 'POST'])
def reset_password_pengajar():
    # Mencegah user mengakses halaman ini jika belum verifikasi OTP
    if request.method == 'GET':
        if 'reset_email_pengajar' not in session:
            return redirect(url_for('pengajar.forgot_password_pengajar'))
        return render_template('pengajar/reset_password_pengajar.html')

    # Proses update password baru ke database
    if request.method == 'POST':
        if 'reset_email_pengajar' not in session:
            return jsonify({'message': 'Sesi telah berakhir, silakan ulang dari awal.'}), 400

        data = request.get_json()
        new_password = data.get('password')
        konfirmasi_password = data.get('konfirmasi_password')
        email = session['reset_email_pengajar']

        if not new_password or len(new_password) < 8:
            return jsonify({'message': 'Kata sandi baru minimal 8 karakter!'}), 400

        if konfirmasi_password is not None and new_password != konfirmasi_password:
            return jsonify({'message': 'Konfirmasi kata sandi tidak cocok!'}), 400

        hashed_password = generate_password_hash(new_password)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users SET password = %s WHERE email = %s AND role_id_role = 'R02'
        """, (hashed_password, email))
        conn.commit()

        baris_terupdate = cursor.rowcount

        cursor.close()
        conn.close()

        session.pop('reset_email_pengajar', None)

        if baris_terupdate == 0:
            return jsonify({'message': 'Akun Pengajar tidak ditemukan, kata sandi gagal diubah.'}), 404

        return jsonify({
            'message': 'Kata sandi berhasil diubah! Silakan login.',
            'redirect': url_for('pengajar.login_pengajar')
        }), 200


@pengajar_bp.route('/logout_pengajar')
def logout_pengajar():
    session.clear()
    return redirect(url_for('pengajar.login_pengajar'))
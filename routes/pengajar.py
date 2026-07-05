from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from db import get_db_connection

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
        query_siswa = """
            SELECT 
                a.id_anak,
                a.nama_lengkap,
                a.nama_panggilan,
                a.jenis_kelamin,
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

@pengajar_bp.route('/logout_pengajar')
def logout_pengajar():
    session.clear()
    return redirect(url_for('pengajar.login_pengajar'))

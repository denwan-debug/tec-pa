from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from db import get_db_connection
import uuid, math

# Membuat blueprint untuk admin
admin_bp = Blueprint('admin', __name__)


# --- FILTER JINJA2: Format angka menjadi Rupiah (Rp450.000) ---
@admin_bp.app_template_filter('rupiah')
def format_rupiah(value):
    try:
        value = int(value)
        return "Rp{:,.0f}".format(value).replace(",", ".")
    except (ValueError, TypeError):
        return "Rp0"


# --- HELPER: Format tanggal ke Bahasa Indonesia (dilakukan di Python, bukan SQL,
# supaya tidak tergantung cara driver database menangani karakter '%') ---
_NAMA_BULAN_ID = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
    7: 'Jul', 8: 'Agu', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Des'
}

def format_tanggal_indo(dt):
    if not dt:
        return '-'
    try:
        return f"{dt.day:02d} {_NAMA_BULAN_ID[dt.month]} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"
    except (AttributeError, KeyError):
        return str(dt)

@admin_bp.route('/dashboard_admin')
def dashboard_admin():
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Hitung Total Murid Sebenarnya (Dari tabel anak)
        cursor.execute("SELECT COUNT(*) as total FROM anak")
        murid = cursor.fetchone()['total'] or 0
        
        # 2. Hitung Total Pengajar Sebenarnya (Berdasarkan ID Role 'R02')
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role_id_role = 'R02'")
        pengajar = cursor.fetchone()['total'] or 0 

        # 3. Nilai Riil Kelas Aktif (Tabel kelas sudah ada di database)
        cursor.execute("SELECT COUNT(*) as total FROM kelas WHERE status_kelas = 'Aktif'")
        kelas_aktif = cursor.fetchone()['total'] or 0 
        
        # 4. Hitung Total Orang Tua/Keluarga yang masih 'unverified' (Pending)
        cursor.execute("""
            SELECT COUNT(*) as total 
            FROM users u
            JOIN role r ON u.role_id_role = r.id_role
            WHERE r.nama_role = 'Murid' AND u.status_akun = 'unverified'
        """)
        pending = cursor.fetchone()['total'] or 0 

        return render_template('admin/dashboard_admin.html', 
                               murid=murid, 
                               pengajar=pengajar,
                               kelas_aktif=kelas_aktif,
                               pending=pending,
                               username=session.get('username', 'Admin Dennis'))
                               
    except Exception as e:
        print(f"\n[ERROR DASHBOARD]: {e}\n")
        return render_template('admin/dashboard_admin.html', murid=0, pengajar=0, kelas_aktif=0, pending=0, username="Admin")
    finally:
        cursor.close()
        conn.close()
# Tugas: Menampilkan wujud halaman web (UI)
@admin_bp.route('/login_admin')
def login_admin():
    return render_template('admin/login_admin.html')

@admin_bp.route('/login_admin_action', methods=['POST'])
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

@admin_bp.route('/logout_admin')
def logout_admin():
    session.clear()
    return redirect(url_for('admin.login_admin'))

@admin_bp.route('/manajemen_kelas_admin')
def manajemen_kelas_admin():
    # 1. Proteksi Akses Admin Kepala
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 2. Hitung statistik ringkas untuk kartu bagian atas halaman
        cursor.execute("SELECT COUNT(*) as total FROM kelas")
        total_kelas = cursor.fetchone()['total'] or 0
        
        cursor.execute("SELECT COUNT(*) as total FROM kelas WHERE status_kelas = 'Aktif'")
        kelas_aktif = cursor.fetchone()['total'] or 0
        
        cursor.execute("SELECT SUM(kapasitas_maksimal) as total_slot FROM kelas")
        fetch_slot = cursor.fetchone()
        total_slot = fetch_slot['total_slot'] if fetch_slot and fetch_slot['total_slot'] is not None else 0
        
        # 3. Query Utama: Mengambil data persis sesuai kolom di tec_english.sql terbaru
        query_kelas = """
            SELECT 
                k.id_kelas,
                k.nama_kelas,
                k.hari_jadwal,
                k.jam_mulai,
                k.jam_selesai,
                k.kapasitas_maksimal,
                k.harga,
                k.status_kelas,
                u.username AS nama_tutor,
                (SELECT COUNT(*) FROM pendaftaran p WHERE p.id_kelas = k.id_kelas) AS jumlah_siswa
            FROM kelas k
            LEFT JOIN users u ON k.id_pengajar = u.id_users
            ORDER BY k.created_at DESC
        """
        cursor.execute(query_kelas)
        daftar_kelas = cursor.fetchall()
        
        # 4. Konversi Data TIME & DECIMAL agar aman dikirim ke Jinja2 HTML
        for kelas in daftar_kelas:
            # Format Jam Mulai
            if kelas['jam_mulai']:
                if hasattr(kelas['jam_mulai'], 'total_seconds'):  # jika bertipe timedelta
                    total_sec = int(kelas['jam_mulai'].total_seconds())
                    kelas['jam_mulai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
                elif hasattr(kelas['jam_mulai'], 'strftime'):  # jika bertipe time object
                    kelas['jam_mulai'] = kelas['jam_mulai'].strftime('%H:%M')
                else:
                    kelas['jam_mulai'] = str(kelas['jam_mulai'])[:5]

            # Format Jam Selesai
            if kelas['jam_selesai']:
                if hasattr(kelas['jam_selesai'], 'total_seconds'):
                    total_sec = int(kelas['jam_selesai'].total_seconds())
                    kelas['jam_selesai'] = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
                elif hasattr(kelas['jam_selesai'], 'strftime'):
                    kelas['jam_selesai'] = kelas['jam_selesai'].strftime('%H:%M')
                else:
                    kelas['jam_selesai'] = str(kelas['jam_selesai'])[:5]
            
            # Pastikan harga diubah ke integer/float murni (bukan objek Decimal)
            kelas['harga'] = int(kelas['harga']) if kelas['harga'] else 0
        
        return render_template(
            'admin/manajemen_kelas.html', 
            daftar_kelas=daftar_kelas,
            total_kelas=total_kelas,
            kelas_aktif=kelas_aktif,
            total_slot=total_slot
        )
        
    except Exception as e:
        print(f"\n[ERROR MANAJEMEN KELAS]: {e}\n")
        flash("Gagal memuat data kelas dari database.", "error")
        return render_template('admin/manajemen_kelas.html', daftar_kelas=[], total_kelas=0, kelas_aktif=0, total_slot=0)
        
    finally:
        cursor.close()
        conn.close()

@admin_bp.route('/buat_kelas_baru')
def buat_kelas_baru():
    # 1. Proteksi Sesi Admin (Hanya Kepala/Admin yang bisa akses)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 2. Ambil daftar user yang memiliki role Pengajar (R02) untuk dikirim ke dropdown HTML
        cursor.execute("SELECT id_users, username, email FROM users WHERE role_id_role = 'R02'")
        daftar_tutor = cursor.fetchall()
        
        return render_template('admin/tambah_kelas.html', daftar_tutor=daftar_tutor)
    except Exception as e:
        print(f"Error memuat form tambah kelas: {e}")
        return render_template('admin/tambah_kelas.html', daftar_tutor=[])
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/simpan_kelas_baru', methods=['POST'])
def simpan_kelas_baru():
    # Proteksi Sesi
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
        
    # 1. Ambil data dari input form HTML
    nama_kelas = request.form.get('nama_kelas')
    tingkat = request.form.get('tingkat')
    id_pengajar = request.form.get('id_pengajar')
    hari_jadwal = request.form.get('hari_jadwal')
    jam_mulai = request.form.get('jam_mulai')
    jam_selesai = request.form.get('jam_selesai')
    kapasitas_maksimal = request.form.get('kapasitas_maksimal')
    harga = request.form.get('harga') # <--- Menerima data harga baru

    # 2. Validasi kelengkapan data (tambahkan 'harga' ke dalam pengecekan)
    if not all([nama_kelas, tingkat, id_pengajar, hari_jadwal, jam_mulai, jam_selesai, kapasitas_maksimal, harga]):
        flash('Semua kolom formulir wajib diisi!', 'error')
        return redirect(url_for('admin.buat_kelas_baru'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 3. Generate ID kelas secara unik
        id_kelas_baru = f"KLS-{str(uuid.uuid4().hex[:6]).upper()}"

        # 4. Eksekusi query INSERT ke tabel kelas (Tambahkan kolom harga)
        query = """
            INSERT INTO kelas (
                id_kelas, nama_kelas, tingkat, id_pengajar, 
                hari_jadwal, jam_mulai, jam_selesai, 
                kapasitas_maksimal, harga, status_kelas
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Aktif')
        """
        # Sesuaikan urutan values dengan urutan kolom pada query di atas
        values = (
            id_kelas_baru, nama_kelas, tingkat, id_pengajar, 
            hari_jadwal, jam_mulai, jam_selesai, 
            kapasitas_maksimal, harga
        )
        
        cursor.execute(query, values)
        conn.commit() 

        flash(f'Kelas "{nama_kelas}" berhasil dibuat dengan harga Rp {harga}!', 'success')
        return redirect(url_for('admin.manajemen_kelas_admin'))

    except Exception as e:
        conn.rollback() 
        print(f"\n[ERROR SIMPAN KELAS]: {e}\n")
        flash('Terjadi kegagalan sistem saat menyimpan data kelas baru.', 'error')
        return redirect(url_for('admin.buat_kelas_baru'))
        
    finally:
        cursor.close()
        conn.close()

@admin_bp.route('/manajemen_pengajar_admin')
def manajemen_pengajar_admin():
    # 1. Verifikasi hak akses admin login
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
    
    # 2. Tangkap parameter filter, pencarian, dan halaman (Pagination)
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Menampilkan 5 data per halaman
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 3. Statistik: Hitung total pengajar aktif riil (Role R02)
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role_id_role = 'R02'")
        total_semua = cursor.fetchone()['total'] or 0

        # Sesi Kelas Aktif: Menghitung kelas riil yang statusnya 'Aktif'
        cursor.execute("SELECT COUNT(*) as total FROM kelas WHERE status_kelas = 'Aktif'")
        sesi_aktif = cursor.fetchone()['total'] or 0

        # Nilai representatif statis untuk penilaian & validasi pendaftaran
        rata_rating = "4.8"
        pending_validasi = 0

        # 4. Hitung total records pencarian untuk dasar pembuatan pagination halaman
        query_count = """
            SELECT COUNT(*) as total 
            FROM users 
            WHERE role_id_role = 'R02' AND (username LIKE %s OR email LIKE %s)
        """
        search_param = f"%{search}%"
        cursor.execute(query_count, (search_param, search_param))
        total_data = cursor.fetchone()['total'] or 0
        
        import math
        total_pages = max(1, math.ceil(total_data / per_page))

        # 5. AMBIL DATA RIIL: Diurutkan berdasarkan alfabet username (A-Z) karena tidak ada 'created_at'
        query_pengajar = """
            SELECT 
                u.id_users, 
                u.username, 
                u.email, 
                u.status_akun,
                (SELECT COUNT(*) FROM kelas k WHERE k.id_pengajar = u.id_users) AS total_kelas,
                (SELECT COUNT(DISTINCT p.id_anak) FROM pendaftaran p JOIN kelas k ON p.id_kelas = k.id_kelas WHERE k.id_pengajar = u.id_users) AS total_siswa
            FROM users u
            WHERE u.role_id_role = 'R02' AND (u.username LIKE %s OR u.email LIKE %s)
            ORDER BY u.username ASC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query_pengajar, (search_param, search_param, per_page, offset))
        daftar_pengajar = cursor.fetchall()

        # 6. Kirim semua variabel ke file HTML
        return render_template(
            'admin/manajemen_pengajar.html',
            daftar_pengajar=daftar_pengajar,
            total_semua=total_semua,
            sesi_aktif=sesi_aktif,
            rata_rating=rata_rating,
            pending_validasi=pending_validasi,
            search=search,
            page=page,
            total_data=total_data,
            total_pages=total_pages
        )

    except Exception as e:
        # Mencetak pesan error asli ke console log terminal terminal/CMD
        print(f"\n[SISTEM EROR DATABASE PENGAJAR]: {e}\n")
        flash('Gagal memuat data pengajar secara riil.', 'error')
        
        return render_template(
            'admin/manajemen_pengajar.html',
            daftar_pengajar=[], total_semua=0, sesi_aktif=0, rata_rating="0.0", pending_validasi=0,
            search=search, page=1, total_data=0, total_pages=1
        )
    finally:
        cursor.close()
        conn.close()

@admin_bp.route('/manajemen_orangtua_admin')
def manajemen_orangtua_admin():
    # Proteksi Sesi Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
    
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
        return render_template('admin/manajemen_orangtua_anak.html', 
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
        return render_template('admin/manajemen_orangtua_anak.html', 
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

@admin_bp.route('/tambah_pengajar', methods=['POST'])
def tambah_pengajar():
    # Pastikan yang mengakses adalah Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))
    
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    
    # Validasi input kosong
    if not username or not email or not password:
        flash('Semua data wajib diisi!', 'error')
        return redirect(url_for('admin.manajemen_pengajar_admin'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Cek apakah email sudah terdaftar sebelumnya
        cursor.execute("SELECT id_users FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('Email sudah terdaftar!', 'error')
            return redirect(url_for('admin.manajemen_pengajar_admin'))
        
        # 2. Ambil id_role untuk 'Pengajar' dari tabel role secara dinamis
        cursor.execute("SELECT id_role FROM role WHERE nama_role = 'Pengajar'")
        role_data = cursor.fetchone()
        if not role_data:
            flash('Role Pengajar tidak ditemukan di database!', 'error')
            return redirect(url_for('admin.manajemen_pengajar_admin'))
            
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
        
    return redirect(url_for('admin.manajemen_pengajar_admin'))


# ==========================================================
#                VALIDASI PEMBAYARAN (ADMIN)
# ==========================================================

@admin_bp.route('/validasi_pembayaran_admin')
def validasi_pembayaran_admin():
    # 1. Proteksi Sesi Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))

    # 2. Tangkap parameter pencarian, filter status, dan halaman untuk tabel riwayat
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 8
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # --- KELOMPOK STATISTIK KARTU ATAS ---
        # A. Tugas yang tertunda (menunggu persetujuan)
        cursor.execute("SELECT COUNT(*) as total FROM pembayaran WHERE status_pembayaran = 'Pending'")
        tugas_tertunda = cursor.fetchone()['total'] or 0

        # B. Divalidasi hari ini (disetujui/ditolak hari ini)
        cursor.execute("""
            SELECT COUNT(*) as total FROM pembayaran 
            WHERE status_pembayaran IN ('Lunas', 'Ditolak') AND DATE(tanggal_bayar) = CURDATE()
        """)
        divalidasi_hari_ini = cursor.fetchone()['total'] or 0

        # C. Total nominal yang sedang menunggu validasi
        cursor.execute("SELECT COALESCE(SUM(jumlah_bayar), 0) as total FROM pembayaran WHERE status_pembayaran = 'Pending'")
        total_nominal_pending = cursor.fetchone()['total'] or 0

        # D. Perlu perhatian: pengajuan pending TANPA bukti bayar, atau sudah menunggu > 2 hari
        cursor.execute("""
            SELECT COUNT(*) as total FROM pembayaran
            WHERE status_pembayaran = 'Pending'
              AND (bukti_bayar IS NULL OR bukti_bayar = '' OR tanggal_bayar < (NOW() - INTERVAL 2 DAY))
        """)
        perlu_perhatian = cursor.fetchone()['total'] or 0

        # --- ANTREAN: MENUNGGU PERSETUJUAN (ditampilkan di bagian atas halaman) ---
        cursor.execute("""
            SELECT 
                p.id_pembayaran,
                CONCAT('TXN-', LPAD(p.id_pembayaran, 5, '0')) AS kode_transaksi,
                p.jumlah_bayar,
                p.tanggal_bayar,
                p.status_pembayaran,
                p.bukti_bayar,
                p.keterangan,
                a.nama_lengkap AS nama_anak,
                k.nama_kelas,
                u.username AS nama_orangtua
            FROM pembayaran p
            JOIN pendaftaran pd ON p.id_pendaftaran = pd.id_pendaftaran
            JOIN anak a ON pd.id_anak = a.id_anak
            JOIN kelas k ON pd.id_kelas = k.id_kelas
            JOIN users u ON a.id_orangtua = u.id_users
            WHERE p.status_pembayaran = 'Pending'
            ORDER BY p.tanggal_bayar ASC
        """)
        antrean_pembayaran = cursor.fetchall()
        for item in antrean_pembayaran:
            item['tanggal_bayar_fmt'] = format_tanggal_indo(item['tanggal_bayar'])

        # --- TABEL RIWAYAT SEMUA TRANSAKSI (dengan pencarian, filter status & pagination) ---
        base_query = """
            FROM pembayaran p
            JOIN pendaftaran pd ON p.id_pendaftaran = pd.id_pendaftaran
            JOIN anak a ON pd.id_anak = a.id_anak
            JOIN kelas k ON pd.id_kelas = k.id_kelas
            JOIN users u ON a.id_orangtua = u.id_users
            WHERE (a.nama_lengkap LIKE %s OR u.username LIKE %s OR k.nama_kelas LIKE %s)
        """
        search_param = f"%{search}%"
        params = [search_param, search_param, search_param]

        if status_filter in ('Pending', 'Lunas', 'Ditolak'):
            base_query += " AND p.status_pembayaran = %s"
            params.append(status_filter)

        cursor.execute(f"SELECT COUNT(*) as total {base_query}", params)
        total_data = cursor.fetchone()['total'] or 0
        total_pages = max(1, math.ceil(total_data / per_page))

        cursor.execute(f"""
            SELECT 
                p.id_pembayaran,
                CONCAT('TXN-', LPAD(p.id_pembayaran, 5, '0')) AS kode_transaksi,
                p.jumlah_bayar,
                p.tanggal_bayar,
                p.status_pembayaran,
                p.bukti_bayar,
                p.keterangan,
                a.nama_lengkap AS nama_anak,
                k.nama_kelas,
                u.username AS nama_orangtua
            {base_query}
            ORDER BY p.tanggal_bayar DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        semua_transaksi = cursor.fetchall()
        for t in semua_transaksi:
            t['tanggal_bayar_fmt'] = format_tanggal_indo(t['tanggal_bayar'])

        return render_template(
            'admin/validasi_pembayaran.html',
            tugas_tertunda=tugas_tertunda,
            divalidasi_hari_ini=divalidasi_hari_ini,
            total_nominal_pending=total_nominal_pending,
            perlu_perhatian=perlu_perhatian,
            antrean_pembayaran=antrean_pembayaran,
            semua_transaksi=semua_transaksi,
            search=search,
            status_filter=status_filter,
            page=page,
            total_pages=total_pages,
            total_data=total_data
        )

    except Exception as e:
        print(f"\n[ERROR VALIDASI PEMBAYARAN]: {e}\n")
        flash('Gagal memuat data pembayaran dari database.', 'error')
        return render_template(
            'admin/validasi_pembayaran.html',
            tugas_tertunda=0, divalidasi_hari_ini=0, total_nominal_pending=0, perlu_perhatian=0,
            antrean_pembayaran=[], semua_transaksi=[], search=search, status_filter=status_filter,
            page=1, total_pages=1, total_data=0
        )
    finally:
        cursor.close()
        conn.close()


@admin_bp.route('/validasi_pembayaran_admin/setujui/<int:id_pembayaran>', methods=['POST'])
def setujui_pembayaran(id_pembayaran):
    # Proteksi Sesi Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Hanya memproses transaksi yang statusnya masih 'Pending' (mencegah proses ganda)
        cursor.execute("""
            UPDATE pembayaran 
            SET status_pembayaran = 'Lunas' 
            WHERE id_pembayaran = %s AND status_pembayaran = 'Pending'
        """, (id_pembayaran,))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Pembayaran berhasil disetujui dan ditandai Lunas.', 'success')
        else:
            flash('Pembayaran tidak ditemukan atau sudah diproses sebelumnya.', 'error')

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR SETUJUI PEMBAYARAN]: {e}\n")
        flash('Terjadi kesalahan pada server saat menyetujui pembayaran.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin.validasi_pembayaran_admin'))


@admin_bp.route('/validasi_pembayaran_admin/tolak/<int:id_pembayaran>', methods=['POST'])
def tolak_pembayaran(id_pembayaran):
    # Proteksi Sesi Admin (Kepala)
    if 'user_id' not in session or session.get('role') != 'Kepala':
        return redirect(url_for('admin.login_admin'))

    alasan = request.form.get('alasan_tolak', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            UPDATE pembayaran 
            SET status_pembayaran = 'Ditolak', keterangan = %s 
            WHERE id_pembayaran = %s AND status_pembayaran = 'Pending'
        """, (alasan if alasan else 'Ditolak oleh admin', id_pembayaran))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Pembayaran berhasil ditolak.', 'success')
        else:
            flash('Pembayaran tidak ditemukan atau sudah diproses sebelumnya.', 'error')

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR TOLAK PEMBAYARAN]: {e}\n")
        flash('Terjadi kesalahan pada server saat menolak pembayaran.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin.validasi_pembayaran_admin'))
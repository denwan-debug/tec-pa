-- Menonaktifkan pengecekan Foreign Key sementara untuk mempermudah pembuatan tabel
SET FOREIGN_KEY_CHECKS = 0;
-- 1. Bersihkan dulu kalau sebelumnya sempat setengah jalan
CREATE DATABASE IF NOT EXISTS `tec_english`;
USE `tec_english`;

-- --------------------------------------------------------
-- Table structure for table `role`
-- --------------------------------------------------------
-- 1. Table structure for table `role`
drop database tec_english;
CREATE TABLE `role` (
  `id_role` varchar(10) NOT NULL,
  `nama_role` varchar(50) NOT NULL,
  PRIMARY KEY (`id_role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO role (id_role, nama_role) VALUES
('R01', 'murid'),
('R02', 'pengajar'),
('R03', 'kepala');
-- 2. Table structure for table `users`
CREATE TABLE `users` (
  `id_users` varchar(10) NOT NULL,
  `username` varchar(50) NOT NULL,
  `nama_lengkap` varchar(100) DEFAULT NULL,
  `email` varchar(100) NOT NULL,
  `no_telp` varchar(20) DEFAULT NULL,
  `alamat` text,
  `foto_profil` varchar(255) DEFAULT 'default_avatar.png',
  `notif_tagihan` tinyint(1) DEFAULT '1',
  `password` varchar(255) NOT NULL,
  `role_id_role` varchar(10) NOT NULL,
  `status_akun` varchar(20) DEFAULT 'unverified',
  `tempat_lahir` varchar(50) DEFAULT NULL,
  `reset_token` varchar(255) DEFAULT NULL,
  `reset_token_expired` datetime DEFAULT NULL,
  PRIMARY KEY (`id_users`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO users (id_users, username, email, password, role_id_role, status_akun)
VALUES (
    '80B4304668',
    'Admin',
    'admin@admin',
    'scrypt:32768:8:1$2mA7UH2qnMWVyLGM$9f5fbb9acbf1f60e4b99bdc6539a0c3d4ddc32241623480b617217760f1868e8b7d9c2cb32fbeb1e531a22cbdece8193515623bd3d2b2e2ddf4ee9d1c3a71ded',
    'R03',
    'verified'
);
-- 3. Table structure for table `user_otps`
CREATE TABLE `user_otps` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id_users` varchar(10) NOT NULL,
  `otp_code` varchar(6) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `expired_at` datetime NOT NULL,
  `is_used` tinyint(1) DEFAULT '0',
  `username` varchar(50) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `password` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4. Table structure for table `anak`
CREATE TABLE `anak` (
  `id_anak` int NOT NULL AUTO_INCREMENT,
  `id_orangtua` varchar(10) NOT NULL,
  `nama_lengkap` varchar(100) NOT NULL,
  `nama_panggilan` varchar(50) DEFAULT NULL,
  `tanggal_lahir` date DEFAULT NULL,
  `jenis_kelamin` enum('L','P') DEFAULT NULL,
  `status_anak` enum('Active','Inactive') DEFAULT 'Active',
  `foto_profil` varchar(255) DEFAULT 'default_anak.png',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `sekolah_asal` varchar(255) DEFAULT NULL,
  `kelas` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`id_anak`),
  KEY `fk_anak_orangtua` (`id_orangtua`),
  CONSTRAINT `fk_anak_orangtua` FOREIGN KEY (`id_orangtua`) REFERENCES `users` (`id_users`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 5. Table structure for table `kelas`
CREATE TABLE `kelas` (
  `id_kelas` varchar(20) NOT NULL,
  `nama_kelas` varchar(100) NOT NULL,
  `tingkat` enum('SD','SMP','SMA') DEFAULT NULL,
  `id_pengajar` varchar(10) NOT NULL,
  `hari_jadwal` varchar(50) NOT NULL,
  `jam_mulai` time NOT NULL,
  `jam_selesai` time NOT NULL,
  `kapasitas_maksimal` int NOT NULL DEFAULT '15',
  `harga` decimal(10,2) NOT NULL DEFAULT '0.00',
  `status_kelas` enum('Aktif','Penuh','Selesai') DEFAULT 'Aktif',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `deskripsi` text,
  PRIMARY KEY (`id_kelas`),
  KEY `fk_kelas_pengajar` (`id_pengajar`),
  CONSTRAINT `fk_kelas_pengajar` FOREIGN KEY (`id_pengajar`) REFERENCES `users` (`id_users`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 6. Table structure for table `sesi_kelas`
CREATE TABLE `sesi_kelas` (
  `id_sesi` int NOT NULL AUTO_INCREMENT,
  `id_kelas` varchar(20) NOT NULL,
  `sesi_ke` int NOT NULL,
  `tanggal` date NOT NULL,
  `topik_pembahasan` varchar(255) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id_sesi`),
  KEY `fk_sesi_kelas` (`id_kelas`),
  CONSTRAINT `fk_sesi_kelas` FOREIGN KEY (`id_kelas`) REFERENCES `kelas` (`id_kelas`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 7. Table structure for table `materi_belajar`
CREATE TABLE `materi_belajar` (
  `id_materi` int NOT NULL AUTO_INCREMENT,
  `id_sesi` int NOT NULL,
  `judul_materi` varchar(150) NOT NULL,
  `deskripsi` text,
  `file_materi` varchar(255) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id_materi`),
  KEY `fk_materi_sesi` (`id_sesi`),
  CONSTRAINT `fk_materi_sesi` FOREIGN KEY (`id_sesi`) REFERENCES `sesi_kelas` (`id_sesi`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 8. Table structure for table `pendaftaran`
CREATE TABLE `pendaftaran` (
  `id_pendaftaran` int NOT NULL AUTO_INCREMENT,
  `id_kelas` varchar(20) NOT NULL,
  `id_anak` int NOT NULL,
  `tanggal_daftar` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status_pendaftaran` enum('Aktif','Lulus','Berhenti') NOT NULL DEFAULT 'Aktif',
  PRIMARY KEY (`id_pendaftaran`),
  KEY `fk_pendaftaran_kelas` (`id_kelas`),
  KEY `fk_pendaftaran_anak` (`id_anak`),
  CONSTRAINT `fk_pendaftaran_anak` FOREIGN KEY (`id_anak`) REFERENCES `anak` (`id_anak`) ON DELETE CASCADE,
  CONSTRAINT `fk_pendaftaran_kelas` FOREIGN KEY (`id_kelas`) REFERENCES `kelas` (`id_kelas`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 9. Table structure for table `pembayaran`
CREATE TABLE `pembayaran` (
  `id_pembayaran` bigint NOT NULL AUTO_INCREMENT,
  `kode_pembayaran` varchar(30) DEFAULT NULL,
  `id_pendaftaran` int NOT NULL,
  `jumlah_bayar` int NOT NULL,
  `tanggal_bayar` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status_pembayaran` enum('Pending','Lunas','Ditolak') NOT NULL DEFAULT 'Pending',
  `bukti_bayar` varchar(255) DEFAULT NULL,
  `keterangan` text,
  PRIMARY KEY (`id_pembayaran`),
  UNIQUE KEY `kode_pembayaran` (`kode_pembayaran`),
  KEY `fk_pembayaran_pendaftaran` (`id_pendaftaran`),
  CONSTRAINT `fk_pembayaran_pendaftaran` FOREIGN KEY (`id_pendaftaran`) REFERENCES `pendaftaran` (`id_pendaftaran`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 10. Table structure for table `presensi`
CREATE TABLE `presensi` (
  `id_presensi` int NOT NULL AUTO_INCREMENT,
  `id_sesi` int NOT NULL,
  `id_pendaftaran` int NOT NULL,
  `status_kehadiran` enum('Hadir','Izin','Sakit','Alpa') NOT NULL DEFAULT 'Hadir',
  `catatan` text,
  PRIMARY KEY (`id_presensi`),
  KEY `fk_presensi_sesi` (`id_sesi`),
  KEY `fk_presensi_pendaftaran` (`id_pendaftaran`),
  CONSTRAINT `fk_presensi_pendaftaran` FOREIGN KEY (`id_pendaftaran`) REFERENCES `pendaftaran` (`id_pendaftaran`) ON DELETE CASCADE,
  CONSTRAINT `fk_presensi_sesi` FOREIGN KEY (`id_sesi`) REFERENCES `sesi_kelas` (`id_sesi`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- Mengaktifkan kembali pengecekan Foreign Key
SET FOREIGN_KEY_CHECKS = 1;
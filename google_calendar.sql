-- =========================================================
-- Migrasi: integrasi Google Calendar
-- Jalankan file ini di database `tec_english` (phpMyAdmin /
-- mysql client) sebelum memakai fitur Sinkronisasi Kalender.
-- =========================================================

-- Menyimpan token OAuth Google per user (1 baris per user yang sudah connect)
CREATE TABLE `google_calendar_tokens` (
  `id_users` varchar(10) NOT NULL,
  `access_token` text NOT NULL,
  `refresh_token` text DEFAULT NULL,
  `token_uri` varchar(255) NOT NULL,
  `client_id` varchar(255) NOT NULL,
  `client_secret` varchar(255) NOT NULL,
  `scopes` text NOT NULL,
  `expiry` datetime DEFAULT NULL,
  `calendar_id` varchar(255) DEFAULT 'primary',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id_users`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE `google_calendar_tokens`
  ADD CONSTRAINT `fk_gcal_token_user` FOREIGN KEY (`id_users`) REFERENCES `users` (`id_users`) ON DELETE CASCADE;

-- Memetakan 1 sesi_kelas -> 1 event Google Calendar, supaya sinkronisasi
-- berikutnya meng-UPDATE event yang sudah ada, bukan membuat dobel.
CREATE TABLE `google_calendar_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `id_users` varchar(10) NOT NULL,
  `id_sesi` int NOT NULL,
  `google_event_id` varchar(255) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_sesi` (`id_users`, `id_sesi`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE `google_calendar_events`
  ADD CONSTRAINT `fk_gcal_event_user` FOREIGN KEY (`id_users`) REFERENCES `users` (`id_users`) ON DELETE CASCADE,
  ADD CONSTRAINT `fk_gcal_event_sesi` FOREIGN KEY (`id_sesi`) REFERENCES `sesi_kelas` (`id_sesi`) ON DELETE CASCADE;
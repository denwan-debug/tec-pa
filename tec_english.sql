-- phpMyAdmin SQL Dump
-- version 5.2.3
-- https://www.phpmyadmin.net/
--
-- Host: localhost:3306
-- Generation Time: Jun 24, 2026 at 02:37 PM
-- Server version: 8.4.3
-- PHP Version: 8.3.30

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `tec_english`
--

-- --------------------------------------------------------

--
-- Table structure for table `role`
--

CREATE TABLE `role` (
  `id_role` varchar(10) NOT NULL,
  `nama_role` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

--
-- Dumping data for table `role`
--

INSERT INTO `role` (`id_role`, `nama_role`) VALUES
('R01', 'Murid'),
('R02', 'Pengajar'),
('R03', 'Kepala');

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id_users` varchar(10) NOT NULL,
  `username` varchar(50) NOT NULL,
  `email` varchar(100) NOT NULL,
  `password` varchar(255) NOT NULL,
  `role_id_role` varchar(10) NOT NULL,
  `status_akun` varchar(20) DEFAULT 'unverified'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

--
-- Dumping data for table `users`
--

INSERT INTO `users` (`id_users`, `username`, `email`, `password`, `role_id_role`, `status_akun`) VALUES
('08DA9A988F', 'Farrel Arya Putra', 'itsfarrelarya69@gmail.com', 'scrypt:32768:8:1$jlEZouNFqmqO6Cam$589f63d4f708ed4d3898f2e7b622a4b12f0dcfea090e6294e33138130e4cd859154b2b9d4ad1c4268ba2e229770117a4d2daa7605d79cecfcba6b7c461d3fc72', 'R01', 'unverified'),
('B7F9829DF2', 'denis', 'dennisdg273@gmail.com', 'scrypt:32768:8:1$5yJuDB09lrgCy7mc$635ac9c9b9b408837ea148b940176b7d7ee13991d48bf05fd47b066f825e0809ca427571e1ed620e03200dbf5006db9a8df8009497fd4f1531c26d85c58a3628', 'R01', 'verified');

-- --------------------------------------------------------

--
-- Table structure for table `user_otps`
--

CREATE TABLE `user_otps` (
  `id` int NOT NULL,
  `user_id_users` varchar(10) NOT NULL,
  `otp_code` varchar(6) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `expired_at` datetime NOT NULL,
  `is_used` tinyint(1) DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

--
-- Dumping data for table `user_otps`
--

INSERT INTO `user_otps` (`id`, `user_id_users`, `otp_code`, `created_at`, `expired_at`, `is_used`) VALUES
(44, '08DA9A988F', '663145', '2026-06-23 01:16:24', '2026-06-23 08:21:24', 0),
(45, '08DA9A988F', '663145', '2026-06-23 01:16:24', '2026-06-23 08:21:24', 0),
(56, 'B7F9829DF2', '218930', '2026-06-23 15:15:57', '2026-06-23 22:20:57', 1),
(57, 'B7F9829DF2', '218930', '2026-06-23 15:15:57', '2026-06-23 22:20:57', 0);

--
-- Indexes for dumped tables
--

--
-- Indexes for table `role`
--
ALTER TABLE `role`
  ADD PRIMARY KEY (`id_role`);

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`id_users`),
  ADD KEY `user_role_fk` (`role_id_role`);

--
-- Indexes for table `user_otps`
--
ALTER TABLE `user_otps`
  ADD PRIMARY KEY (`id`),
  ADD KEY `fk_otp_user` (`user_id_users`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `user_otps`
--
ALTER TABLE `user_otps`
  MODIFY `id` int NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=58;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `users`
--
ALTER TABLE `users`
  ADD CONSTRAINT `user_role_fk` FOREIGN KEY (`role_id_role`) REFERENCES `role` (`id_role`);

--
-- Constraints for table `user_otps`
--
ALTER TABLE `user_otps`
  ADD CONSTRAINT `fk_otp_user` FOREIGN KEY (`user_id_users`) REFERENCES `users` (`id_users`) ON DELETE CASCADE;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;

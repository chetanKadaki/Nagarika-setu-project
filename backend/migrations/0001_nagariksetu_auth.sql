CREATE DATABASE IF NOT EXISTS nagariksetu
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE nagariksetu;

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(180) NOT NULL,
    role VARCHAR(30) NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    UNIQUE KEY uq_users_email (email),
    KEY ix_users_role (role)
) ENGINE=InnoDB;

ALTER TABLE users
    ADD COLUMN created_at DATETIME(6) NULL,
    ADD COLUMN updated_at DATETIME(6) NULL;
UPDATE users
SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP(6)),
    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP(6));
ALTER TABLE users
    MODIFY created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    MODIFY updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6);
ALTER TABLE users
    ADD CONSTRAINT ck_users_role CHECK (
        role IN ('citizen', 'engineer_pending', 'engineer', 'verifier', 'officer', 'admin')
    );

CREATE TABLE IF NOT EXISTS user_authentication (
    user_id VARCHAR(40) NOT NULL PRIMARY KEY,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    account_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    KEY ix_user_authentication_status (account_status),
    CONSTRAINT ck_user_authentication_status CHECK (account_status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT fk_user_authentication_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

INSERT IGNORE INTO user_authentication (user_id, email_verified, account_status)
SELECT id, TRUE, 'ACTIVE' FROM users;

CREATE TABLE IF NOT EXISTS citizen_profiles (
    user_id VARCHAR(40) NOT NULL PRIMARY KEY,
    phone_number VARCHAR(24) NOT NULL,
    address VARCHAR(240) NOT NULL DEFAULT '',
    ward VARCHAR(100) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_citizen_profiles_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS officer_profiles (
    user_id VARCHAR(40) NOT NULL PRIMARY KEY,
    employee_id VARCHAR(100) NOT NULL UNIQUE,
    designation VARCHAR(120) NOT NULL,
    department VARCHAR(100) NOT NULL,
    jurisdiction VARCHAR(180) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_officer_profiles_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_contact_profiles (
    user_id VARCHAR(40) NOT NULL PRIMARY KEY,
    phone_number VARCHAR(24) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_user_contact_profiles_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token_hash CHAR(64) NOT NULL PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    used_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_email_verification_tokens_user (user_id),
    KEY ix_email_verification_tokens_expiry (expires_at),
    CONSTRAINT fk_email_verification_tokens_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash CHAR(64) NOT NULL PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    used_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_password_reset_tokens_user (user_id),
    KEY ix_password_reset_tokens_expiry (expires_at),
    CONSTRAINT fk_password_reset_tokens_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_sessions (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    user_id VARCHAR(40) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_auth_sessions_user (user_id),
    KEY ix_auth_sessions_expiry (expires_at),
    CONSTRAINT fk_auth_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_audit_logs (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    user_id VARCHAR(40) NULL,
    email VARCHAR(180) NOT NULL,
    ip_address VARCHAR(45) NOT NULL DEFAULT '',
    user_agent VARCHAR(512) NOT NULL DEFAULT '',
    succeeded BOOLEAN NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_login_audit_logs_user (user_id),
    KEY ix_login_audit_logs_email (email),
    KEY ix_login_audit_logs_created (created_at),
    CONSTRAINT fk_login_audit_logs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_attempts (
    id VARCHAR(40) NOT NULL PRIMARY KEY,
    email VARCHAR(180) NOT NULL,
    ip_address VARCHAR(45) NOT NULL DEFAULT '',
    succeeded BOOLEAN NOT NULL,
    attempted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_login_attempts_email (email),
    KEY ix_login_attempts_ip (ip_address),
    KEY ix_login_attempts_time (attempted_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_invitations (
    token_hash CHAR(64) NOT NULL PRIMARY KEY,
    email VARCHAR(180) NOT NULL,
    name VARCHAR(120) NOT NULL,
    role VARCHAR(30) NOT NULL,
    department VARCHAR(100) NOT NULL DEFAULT '',
    employee_id VARCHAR(100) NOT NULL DEFAULT '',
    designation VARCHAR(120) NOT NULL DEFAULT '',
    jurisdiction VARCHAR(180) NOT NULL DEFAULT '',
    created_by VARCHAR(40) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    used_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_user_invitations_email (email),
    KEY ix_user_invitations_expiry (expires_at),
    CONSTRAINT ck_user_invitations_role CHECK (role IN ('officer', 'verifier')),
    CONSTRAINT fk_user_invitations_creator FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB;

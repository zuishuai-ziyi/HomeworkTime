-- ============================================================================
-- HomeworkTime 服务端 数据库 Schema
-- ----------------------------------------------------------------------------
-- 目标库: homework_time (utf8mb4)
-- 运行方式: 在宝塔面板 MySQL 中,使用 root 或具备建库权限的账号执行
--   mysql -u root -p < schema.sql
-- 或者在 phpMyAdmin 中整段粘贴执行
--
-- 说明:
--   * 所有时间字段使用 DATETIME,默认 CURRENT_TIMESTAMP,便于后台审计展示
--   * JSON 字段使用 MySQL 原生 JSON 类型 (5.7+)
--   * 字符集统一 utf8mb4_unicode_ci,完整支持 emoji 与中文
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `homework_time`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `homework_time`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------------------------------------------------------
-- 1) users: 后台管理员
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `username`      VARCHAR(64)  NOT NULL                COMMENT '登录用户名 (唯一)',
  `password_hash` VARCHAR(255) NOT NULL                COMMENT 'bcrypt 哈希 (bcryptjs, $2a$/$2b$ 开头)',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='后台管理员账号';

-- ----------------------------------------------------------------------------
-- 2) config: 当前全局业务配置 (单行; id 固定 = 1)
--    content_json 字段与 client/app/config_schema.json / server/src/config.schema.json
--    严格对齐 (draft-07),服务端校验逻辑会加载这两份 JSON Schema。
--    注意: 单行约束由应用层保证 (插入固定 id=1、更新只改 id=1),
--    不写 CHECK (id=1),因为 MySQL 8.0.16+ 不允许 CHECK 引用自增列。
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `config`;
CREATE TABLE `config` (
  `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `content_json`  JSON         NOT NULL                COMMENT '业务配置主体 JSON',
  `version`       INT UNSIGNED NOT NULL DEFAULT 1     COMMENT '单调递增版本号,客户端据此判断是否需要更新',
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `updated_by`    INT UNSIGNED NULL                  COMMENT '最近一次修改者 user.id (允许 NULL 表示初始化)',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='当前全局业务配置 (单行)';

-- ----------------------------------------------------------------------------
-- 3) client_token: 客户端共用 Token (单行; id 固定 = 1)
--    同样不能写 CHECK (id=1) (见上);单行由应用层保证
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `client_token`;
CREATE TABLE `client_token` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `token`      VARCHAR(128) NOT NULL                COMMENT '客户端鉴权 token (明文,因客户端需要直接存放)',
  `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_client_token_token` (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='客户端鉴权 Token (单行)';

-- ----------------------------------------------------------------------------
-- 4) devices: 设备在线监控
--    last_heartbeat 距今 <= 30s 视为在线
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `devices`;
CREATE TABLE `devices` (
  `id`                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `device_uuid`         VARCHAR(64)  NOT NULL                COMMENT '客户端首次启动随机生成的 UUID',
  `device_name`         VARCHAR(128) NULL                    COMMENT '客户端主机名',
  `room_name`           VARCHAR(128) NULL                    COMMENT '教室名 (后台可改)',
  `ip`                  VARCHAR(64)  NULL                    COMMENT '最近心跳时的客户端 IP',
  `client_version`      VARCHAR(32)  NULL                    COMMENT '客户端版本字符串',
  `update_pending_version` VARCHAR(32) NULL                  COMMENT '已下载待生效的更新版本 (心跳上报, NULL=无)',
  `last_heartbeat`      DATETIME     NULL                    COMMENT '最后一次心跳时间',
  `last_config_version` INT UNSIGNED NULL                    COMMENT '该设备上次成功拉取的 config.version',
  `created_at`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_devices_device_uuid` (`device_uuid`),
  KEY `idx_devices_last_heartbeat` (`last_heartbeat`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='设备心跳与在线监控';

-- ----------------------------------------------------------------------------
-- 5) audio_files: 音频文件元数据
--    is_builtin=1 表示内置 (near.wav / end.wav),后台不可删
--    内置音频的实际文件随客户端打包 (client/resources/sounds/),
--    不入库,stored_path 留空;上传音频 stored_path 指向 server/uploads/audio/
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `audio_files`;
CREATE TABLE `audio_files` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `filename`    VARCHAR(128) NOT NULL                COMMENT '对外文件名 (含 .wav 后缀)',
  `stored_path` VARCHAR(255) NULL                    COMMENT '服务端相对路径;内置音频为 NULL',
  `size`        BIGINT UNSIGNED NULL                COMMENT '字节数,内置音频允许 NULL',
  `sha256`      CHAR(64)     NULL                    COMMENT '十六进制 sha256,内置音频允许 NULL',
  `is_builtin`  TINYINT(1)   NOT NULL DEFAULT 0     COMMENT '1 = 内置 (不可删), 0 = 后台上传',
  `uploaded_by` INT UNSIGNED NULL                    COMMENT '上传者 user.id (内置为 NULL)',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_audio_files_filename` (`filename`),
  KEY `idx_audio_files_is_builtin` (`is_builtin`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='音频文件元数据 (含内置)';

-- ----------------------------------------------------------------------------
-- 6) client_update: 客户端全量更新包 (单行; id 固定 = 1, 仅保留最新一个包)
--    管理端上传 zip (PyInstaller onedir 整目录压缩, 根级为 HomeworkTime.exe
--    与 _internal/ 等) 即视为发布; 回滚 = 重新上传旧包。
--    effective_time 为管理端指定的客户端生效时间 (客户端到点后替换重启,
--    若正处于晚自习时段则顺延至晚自习结束), NULL 表示立即生效。
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `client_update`;
CREATE TABLE `client_update` (
  `id`             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `version`        VARCHAR(32)  NOT NULL                COMMENT '版本号 (应与包内 update_manifest.json 一致)',
  `notes`          VARCHAR(500) NULL                    COMMENT '更新说明',
  `stored_path`    VARCHAR(255) NOT NULL                COMMENT 'zip 包相对服务端根路径',
  `size`           BIGINT UNSIGNED NOT NULL             COMMENT 'zip 字节数',
  `sha256`         CHAR(64)     NOT NULL                COMMENT 'zip 十六进制 sha256',
  `effective_time` DATETIME     NOT NULL                COMMENT '客户端生效时间 (上传时为空则取当前时间=立即生效)',
  `published_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发布(上传完成)时间',
  `uploaded_by`    INT UNSIGNED NULL                    COMMENT '上传者 user.id',
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='客户端全量更新包 (单行, 仅保留最新)';

-- ----------------------------------------------------------------------------
-- 7) audit_logs: 操作日志
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `audit_logs`;
CREATE TABLE `audit_logs` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     INT UNSIGNED NULL                    COMMENT '操作者 user.id (系统动作可 NULL)',
  `action`      VARCHAR(64)  NOT NULL                COMMENT '操作类型,如 config.update / audio.upload / user.create / token.reset',
  `detail_json` JSON         NULL                    COMMENT '操作详情,结构随 action 变化',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_audit_logs_user_id`     (`user_id`),
  KEY `idx_audit_logs_action`      (`action`),
  KEY `idx_audit_logs_created_at`  (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='操作日志 (后台操作可查询)';

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- 初始数据
-- ============================================================================

-- 默认管理员 admin / admin123 (bcryptjs $2b$10$ 哈希)
-- 该哈希对明文 "admin123" 验证通过;首次部署后请立即在后台修改密码。
INSERT INTO `users` (`username`, `password_hash`) VALUES
  ('admin', '$2b$10$MCo1.ebuo0XQPi7d8iCZ9e3VHO32Yos759BqQ.eu7nk9b9XyzO2Ou');

-- 业务配置初始单行 (id 固定 = 1)
-- content_json 与 server/src/default_config.json 保持一致;
-- 后续如调整默认配置,以 default_config.json 为准,并手动 UPDATE 此处。
INSERT INTO `config` (`id`, `content_json`, `version`, `updated_by`) VALUES
  (
    1,
    JSON_OBJECT(
      'evening_start', '18:30',
      'evening_end',   '22:00',
      'subjects', JSON_ARRAY(
        JSON_OBJECT('name', '语文', 'start', '18:30', 'end', '19:20'),
        JSON_OBJECT('name', '数学', 'start', '19:20', 'end', '20:10'),
        JSON_OBJECT('name', '英语', 'start', '20:10', 'end', '21:00'),
        JSON_OBJECT('name', '物理', 'start', '21:00', 'end', '22:00')
      ),
      'opacity', JSON_OBJECT(
        'main',   0.85,
        'ball',   0.70,
        'config', 1.00
      ),
      'theme', JSON_OBJECT(
        'card',     '#023E8A',
        'accent',   '#0077B6',
        'timeline', '#03045E'
      ),
      'allow_local_edit', true,
      'idle_text',        '课间休息',
      'sound', JSON_OBJECT(
        'enabled',       true,
        'near_seconds',  60,
        'near_audio',    'near.wav',
        'near_enabled',  true,
        'end_audio',     'end.wav',
        'end_enabled',   true
      )
    ),
    1,
    NULL
  );

-- 客户端 Token 初始行 (单行, id 固定 = 1)
-- 占位 token,首次部署后请在后台执行 token.reset 重新生成。
INSERT INTO `client_token` (`id`, `token`) VALUES
  (1, 'CHANGE_ME_DEFAULT_TOKEN');

-- 内置音频元数据 (近结束 / 结束)
-- is_builtin=1 表示内置,后台禁止删除;size/sha256 允许 NULL (内置音频随客户端打包,不入库)。
INSERT INTO `audio_files` (`filename`, `stored_path`, `size`, `sha256`, `is_builtin`) VALUES
  ('near.wav', NULL, NULL, NULL, 1),
  ('end.wav',  NULL, NULL, NULL, 1);
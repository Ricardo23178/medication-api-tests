-- ============================================================================
-- medication-api-tests . 测试库结构
--
-- 来源：medication-reminder-backend 的 medication_system 库，导出结构 + 必要配置种子。
-- 用途：每次跑测试前重建一个一次性数据库，用例在其中自注册账号、自建数据，
--       跑完即弃，不触碰开发库里的任何真实数据。
--
-- 重建方式：python scripts/prepare_db.py
-- ============================================================================

DROP TABLE IF EXISTS `abnormal_event`;
CREATE TABLE `abnormal_event` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '事件ID',
  `user_id` bigint unsigned NOT NULL COMMENT '归属用户',
  `task_id` bigint unsigned NOT NULL COMMENT '关联提醒任务',
  `type` varchar(32) NOT NULL COMMENT 'UNCONFIRMED_TIMEOUT未确认超时/CONSECUTIVE_UNCONFIRMED连续未确认/PLAN_ENDED_UNFINISHED计划结束未完成',
  `status` varchar(16) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN/NOTIFIED/ACKNOWLEDGED/CLOSED',
  `occurred_at` datetime NOT NULL COMMENT '事件发生时间（判定时刻）',
  `notified_at` datetime DEFAULT NULL COMMENT '通知发出时间',
  `acknowledged_by` bigint unsigned DEFAULT NULL COMMENT '确认知晓的家属用户',
  `acknowledged_at` datetime DEFAULT NULL COMMENT '知晓时间',
  `closed_at` datetime DEFAULT NULL COMMENT '事件关闭时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_type` (`task_id`,`type`) COMMENT '★防重复告警：同一任务的同一类异常只建一条，定时任务重复扫描不会重复通知',
  KEY `idx_user_status` (`user_id`,`status`),
  KEY `idx_status_occurred` (`status`,`occurred_at`) COMMENT '待通知事件扫描',
  CONSTRAINT `fk_event_task` FOREIGN KEY (`task_id`) REFERENCES `remind_task` (`id`),
  CONSTRAINT `fk_event_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=125 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='超时/未确认等异常事件';
DROP TABLE IF EXISTS `admin_audit_log`;
CREATE TABLE `admin_audit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `operator_id` bigint NOT NULL,
  `action` varchar(40) NOT NULL,
  `target_type` varchar(40) NOT NULL,
  `target_id` varchar(80) NOT NULL,
  `reason` varchar(200) NOT NULL,
  `before_value` text NOT NULL,
  `after_value` text NOT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_admin_audit_created` (`create_time`),
  KEY `idx_admin_audit_action` (`action`,`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
DROP TABLE IF EXISTS `admin_setting`;
CREATE TABLE `admin_setting` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `category` varchar(16) NOT NULL,
  `code` varchar(80) NOT NULL,
  `name` varchar(80) NOT NULL,
  `setting_value` text NOT NULL,
  `description` varchar(300) NOT NULL,
  `version` int NOT NULL DEFAULT '0',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB AUTO_INCREMENT=32 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
DROP TABLE IF EXISTS `audit_log`;
CREATE TABLE `audit_log` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '日志ID',
  `operator_id` bigint unsigned NOT NULL COMMENT '操作人',
  `operator_role` varchar(16) DEFAULT NULL COMMENT '操作时的角色',
  `action` varchar(64) NOT NULL COMMENT 'VIEW_RECORD查看明细/EXPORT导出/DISABLE_USER停用账号/UNBIND解除关系...',
  `target_type` varchar(32) DEFAULT NULL COMMENT '目标类型：USER/MEDICINE/PLAN/RELATION',
  `target_id` bigint unsigned DEFAULT NULL COMMENT '目标ID',
  `ip` varchar(45) DEFAULT NULL COMMENT '来源IP（IPv6 需 45 位）',
  `detail` varchar(512) DEFAULT NULL COMMENT '补充说明（不含敏感明文）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
  PRIMARY KEY (`id`),
  KEY `idx_operator_time` (`operator_id`,`created_at`),
  KEY `idx_action_time` (`action`,`created_at`),
  KEY `idx_target` (`target_type`,`target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='敏感操作审计';
DROP TABLE IF EXISTS `family_relation`;
CREATE TABLE `family_relation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '关系ID',
  `owner_user_id` bigint unsigned NOT NULL COMMENT '被照护方（数据主体）',
  `family_user_id` bigint unsigned DEFAULT NULL COMMENT '家属用户（邀请阶段未定，接受后回填）',
  `relation_type` varchar(32) DEFAULT NULL COMMENT '关系称谓（父/母/子女/配偶，用户自选）',
  `relation_status` varchar(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING待确认/ACTIVE生效/REJECTED拒绝/REVOKED已解除',
  `scope` varchar(255) NOT NULL DEFAULT 'PLAN_STATUS,ABNORMAL_EVENT' COMMENT '授权范围，逗号分隔：PLAN_STATUS计划状态/ABNORMAL_EVENT异常事件/RECORD_DETAIL明细/STATISTICS统计',
  `invite_code` varchar(32) DEFAULT NULL COMMENT '邀请码（仅 PENDING 期间有效）',
  `invite_expire_at` datetime DEFAULT NULL COMMENT '邀请过期时间',
  `bind_time` datetime DEFAULT NULL COMMENT '关系生效时间',
  `unbind_time` datetime DEFAULT NULL COMMENT '解除时间（保留记录，不物理删除）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_owner_family` (`owner_user_id`,`family_user_id`) COMMENT '同一对关系只保留一条',
  KEY `idx_family_status` (`family_user_id`,`relation_status`) COMMENT '家属查自己的协同对象',
  KEY `idx_owner_status` (`owner_user_id`,`relation_status`) COMMENT '患者查自己的授权列表',
  KEY `idx_invite_code` (`invite_code`) COMMENT '邀请码查询',
  CONSTRAINT `fk_relation_family` FOREIGN KEY (`family_user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `fk_relation_owner` FOREIGN KEY (`owner_user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=120 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='家属绑定与授权范围';
DROP TABLE IF EXISTS `medication_plan`;
CREATE TABLE `medication_plan` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '计划ID',
  `user_id` bigint unsigned NOT NULL COMMENT '归属用户',
  `medicine_id` bigint unsigned NOT NULL COMMENT '关联药品档案',
  `dosage_per_time` decimal(8,2) DEFAULT NULL COMMENT '单次服用量',
  `dosage_unit` varchar(16) DEFAULT NULL COMMENT '服用量单位',
  `start_date` date NOT NULL COMMENT '开始日期',
  `end_date` date DEFAULT NULL COMMENT '结束日期，NULL=长期用药',
  `meal_relation` tinyint NOT NULL DEFAULT '0' COMMENT '0=无关 1=餐前 2=餐后 3=晨起空腹 4=睡前',
  `status` varchar(16) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT/ACTIVE/PAUSED/FINISHED/CANCELLED',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注（用户自定义，如处方来源）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除',
  `plan_version` int NOT NULL DEFAULT '1' COMMENT 'Plan rule version',
  PRIMARY KEY (`id`),
  KEY `idx_user_status` (`user_id`,`status`),
  KEY `idx_medicine` (`medicine_id`),
  KEY `idx_active_scan` (`status`,`end_date`) COMMENT '扫描到期需自然结束的计划',
  CONSTRAINT `fk_plan_medicine` FOREIGN KEY (`medicine_id`) REFERENCES `medicine` (`id`),
  CONSTRAINT `fk_plan_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=94 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用药计划主表';
DROP TABLE IF EXISTS `medication_record`;
CREATE TABLE `medication_record` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '记录ID',
  `task_id` bigint unsigned NOT NULL COMMENT '关联提醒任务',
  `user_id` bigint unsigned NOT NULL COMMENT '确认人（数据主体）',
  `action` varchar(16) NOT NULL COMMENT 'TAKEN已服/DELAYED稍后/SKIPPED跳过/UNCONFIRMED超时未确认',
  `action_time` datetime NOT NULL COMMENT '实际操作时间（以服务端时间为准）',
  `delay_minutes` int DEFAULT NULL COMMENT '「稍后」顺延的分钟数',
  `skip_reason` varchar(64) DEFAULT NULL COMMENT '「跳过」原因（用户自报，系统不作医学解释）',
  `source` varchar(16) NOT NULL DEFAULT 'APP' COMMENT 'APP/CARD卡片/SYSTEM系统判定/TASK',
  `client_request_id` varchar(64) DEFAULT NULL COMMENT '客户端幂等键（弱网重传去重）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task` (`task_id`) COMMENT '★幂等核心：一个提醒任务只允许一条执行记录，重复提交由唯一索引兜底',
  KEY `idx_user_time` (`user_id`,`action_time`) COMMENT '个人记录与日历查询',
  KEY `idx_action_time` (`action`,`action_time`) COMMENT '统计各类动作占比',
  CONSTRAINT `fk_record_task` FOREIGN KEY (`task_id`) REFERENCES `remind_task` (`id`),
  CONSTRAINT `fk_record_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=33 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='确认与执行记录';
DROP TABLE IF EXISTS `medicine`;
CREATE TABLE `medicine` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '药品档案ID',
  `user_id` bigint unsigned NOT NULL COMMENT '归属用户',
  `name` varchar(128) NOT NULL COMMENT '药品名称（用户按药盒/处方录入）',
  `specification` varchar(64) DEFAULT NULL COMMENT '规格，如 5mg×30片',
  `dosage` varchar(64) DEFAULT NULL COMMENT '单次剂量，如 1片',
  `unit` varchar(16) DEFAULT NULL COMMENT '剂量单位',
  `remark` varchar(255) DEFAULT NULL COMMENT '用户备注（自由文本）',
  `image_url` varchar(255) DEFAULT NULL COMMENT '药盒照片',
  `enabled` tinyint NOT NULL DEFAULT '1' COMMENT '1=启用, 0=停用（停用不影响历史记录）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除',
  PRIMARY KEY (`id`),
  KEY `idx_user_enabled` (`user_id`,`enabled`),
  CONSTRAINT `fk_medicine_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=95 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户药品档案';
DROP TABLE IF EXISTS `notification`;
CREATE TABLE `notification` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '通知ID',
  `receiver_id` bigint unsigned NOT NULL COMMENT '接收人',
  `type` varchar(32) NOT NULL COMMENT 'REMIND用药提醒/FAMILY_ALERT家属告警/SYSTEM系统消息',
  `title` varchar(128) NOT NULL COMMENT '标题',
  `content` varchar(512) DEFAULT NULL COMMENT '正文（不得写入敏感明文）',
  `biz_type` varchar(32) DEFAULT NULL COMMENT '关联业务类型：REMIND_TASK/ABNORMAL_EVENT',
  `biz_id` bigint unsigned DEFAULT NULL COMMENT '关联业务ID（点击跳转用）',
  `read_flag` tinyint NOT NULL DEFAULT '0' COMMENT '0=未读 1=已读',
  `send_status` varchar(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING待发送/SENT已发送/FAILED发送失败',
  `retry_count` int unsigned NOT NULL DEFAULT '0' COMMENT '重试次数（上限由配置控制）',
  `sent_at` datetime DEFAULT NULL COMMENT '发送成功时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_receiver_read` (`receiver_id`,`read_flag`) COMMENT '消息中心未读数',
  KEY `idx_send_status` (`send_status`,`retry_count`) COMMENT '失败通知补偿扫描',
  CONSTRAINT `fk_notification_receiver` FOREIGN KEY (`receiver_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=271 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='消息中心与通知记录';
DROP TABLE IF EXISTS `plan_time`;
CREATE TABLE `plan_time` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '时间点ID',
  `plan_id` bigint unsigned NOT NULL COMMENT '所属计划',
  `remind_time` time NOT NULL COMMENT '每日提醒时刻 HH:mm:ss',
  `sequence_no` int unsigned NOT NULL DEFAULT '1' COMMENT '当日第几剂（用于排序与展示）',
  `enabled` tinyint NOT NULL DEFAULT '1' COMMENT '1=启用 0=停用（不改计划整体状态）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_plan_time` (`plan_id`,`remind_time`) COMMENT '同一计划同一时刻不重复',
  KEY `idx_plan` (`plan_id`,`enabled`),
  CONSTRAINT `fk_plan_time_plan` FOREIGN KEY (`plan_id`) REFERENCES `medication_plan` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=100 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='计划的每日提醒时间点';
DROP TABLE IF EXISTS `remind_task`;
CREATE TABLE `remind_task` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '任务ID',
  `plan_id` bigint unsigned NOT NULL COMMENT '所属计划',
  `plan_time_id` bigint unsigned NOT NULL COMMENT '来源时间点规则',
  `user_id` bigint unsigned NOT NULL COMMENT '冗余归属用户，按人查当天任务免联表',
  `scheduled_at` datetime NOT NULL COMMENT '计划触发时间',
  `expire_at` datetime NOT NULL COMMENT '容忍窗口截止时间（超此即判超时）',
  `status` varchar(16) NOT NULL DEFAULT 'WAITING' COMMENT 'WAITING/TRIGGERED/CONFIRMED/EXPIRED/CANCELLED',
  `trigger_count` int unsigned NOT NULL DEFAULT '0' COMMENT '已触发次数（防止一次提醒反复通知）',
  `last_trigger_at` datetime DEFAULT NULL COMMENT '最近触发时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `plan_version` int DEFAULT NULL COMMENT 'Version at generation; NULL for unknown legacy history',
  `snapshot_medicine_id` bigint unsigned DEFAULT NULL COMMENT 'Medicine at task generation',
  `snapshot_medicine_name` varchar(128) DEFAULT NULL,
  `snapshot_dosage_per_time` decimal(8,2) DEFAULT NULL,
  `snapshot_dosage_unit` varchar(16) DEFAULT NULL,
  `snapshot_meal_relation` tinyint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_plan_version_scheduled` (`plan_id`,`plan_version`,`scheduled_at`),
  KEY `idx_scan_due` (`status`,`scheduled_at`) COMMENT '扫描：待触发',
  KEY `idx_scan_expire` (`status`,`expire_at`) COMMENT '扫描：待判超时',
  KEY `idx_user_day` (`user_id`,`scheduled_at`) COMMENT '查询当天提醒清单',
  KEY `idx_plan_status` (`plan_id`,`status`) COMMENT '暂停计划时批量取消未执行任务',
  CONSTRAINT `fk_task_plan` FOREIGN KEY (`plan_id`) REFERENCES `medication_plan` (`id`),
  CONSTRAINT `fk_task_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2262 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='具体提醒任务';
DROP TABLE IF EXISTS `sys_user`;
CREATE TABLE `sys_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `account` varchar(64) NOT NULL COMMENT '登录账号（手机号或用户名）',
  `password_hash` varchar(100) NOT NULL COMMENT '密码哈希（BCrypt，禁止明文）',
  `nickname` varchar(64) DEFAULT NULL COMMENT '昵称',
  `phone` varchar(20) DEFAULT NULL COMMENT '手机号（脱敏展示）',
  `role` varchar(16) NOT NULL DEFAULT 'USER' COMMENT 'USER=普通用户, ADMIN=平台管理员',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1=启用, 0=禁用（管理员可停用）',
  `last_login_at` datetime DEFAULT NULL COMMENT '最近登录时间',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除 0=正常 1=已删',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_account` (`account`,`deleted`),
  KEY `idx_role_status` (`role`,`status`)
) ENGINE=InnoDB AUTO_INCREMENT=367 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账户与角色';

-- 配置表种子：异常类型名、通知模板、投递参数。应用启动时读取 PARAM 行，
-- 缺行会导致异常事件与通知模板取不到默认值，因此随结构一起初始化。
INSERT INTO `admin_setting` (`id`, `category`, `code`, `name`, `setting_value`, `description`, `version`, `update_time`) VALUES (1,'DICT','event.labels','异常类型名称','{"UNCONFIRMED_TIMEOUT":"超时未确认服药","CONSECUTIVE_UNCONFIRMED":"连续多次未确认","PLAN_ENDED_UNFINISHED":"计划结束未完成"}','管理端异常列表的类型名称；仅修改展示，不修改业务状态',0,'2026-10-15 20:14:43');
INSERT INTO `admin_setting` (`id`, `category`, `code`, `name`, `setting_value`, `description`, `version`, `update_time`) VALUES (2,'TEMPLATE','notification.owner','本人异常通知','{"title":"用药未确认提醒","content":"您有用药提醒超时未确认，系统已记录异常。这不代表医学意义上的漏服。"}','仅影响之后新入队的本人通知，已有消息保持原文',0,'2026-10-15 20:14:43');
INSERT INTO `admin_setting` (`id`, `category`, `code`, `name`, `setting_value`, `description`, `version`, `update_time`) VALUES (3,'TEMPLATE','notification.family','家属异常通知','{"title":"家属用药未确认提醒","content":"您关注的家人有用药提醒超时未确认，请查看授权范围内的异常事件。"}','仅影响之后新入队的授权家属通知，已有消息保持原文',0,'2026-10-15 20:14:43');
INSERT INTO `admin_setting` (`id`, `category`, `code`, `name`, `setting_value`, `description`, `version`, `update_time`) VALUES (4,'PARAM','delivery.paused','暂停站内消息发布','false','true暂停后续投递批次，已执行中的批次继续完成；不会停止异常入队',0,'2026-10-15 20:14:43');
INSERT INTO `admin_setting` (`id`, `category`, `code`, `name`, `setting_value`, `description`, `version`, `update_time`) VALUES (5,'PARAM','delivery.batch-size','每批消息投递数量','100','1至100之间的整数，下一个投递批次生效',0,'2026-10-15 20:14:43');

-- Neo4j graph sync retry table
-- Apply: mysql -u root -p edu_financial < migrations/20260724_graph_sync_retry.sql

CREATE TABLE IF NOT EXISTS fin_graph_sync_retry (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sync_type VARCHAR(32) NOT NULL COMMENT '同步类型: holding / risk_level / remove_holding',
    payload JSON NOT NULL COMMENT '同步参数 JSON',
    error_message VARCHAR(1024) DEFAULT NULL COMMENT '最后一次失败的错误信息',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
    max_retries INT NOT NULL DEFAULT 10 COMMENT '最大重试次数',
    next_retry_at DATETIME DEFAULT NULL COMMENT '下次重试时间',
    status ENUM('pending','success','manual_review') NOT NULL DEFAULT 'pending' COMMENT '状态: pending=待重试, success=已成功, manual_review=需人工处理',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status_next_retry (status, next_retry_at),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='图谱同步重试表：Neo4j同步失败后记录，后台任务定时重试';

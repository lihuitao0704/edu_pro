-- Six-Agent linkage: recommendation feedback and durable event delivery.

ALTER TABLE product_recommendation
  ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/accepted/rejected/ignored',
  ADD COLUMN IF NOT EXISTS feedback_reason VARCHAR(255) NULL COMMENT 'feedback reason',
  ADD COLUMN IF NOT EXISTS feedback_at DATETIME NULL COMMENT 'feedback time';

CREATE INDEX IF NOT EXISTS idx_rec_customer_status
  ON product_recommendation (customer_id, status);

CREATE TABLE IF NOT EXISTS agent_event_outbox (
  event_id CHAR(36) PRIMARY KEY,
  event_type VARCHAR(64) NOT NULL,
  source_agent VARCHAR(32) NOT NULL,
  customer_id BIGINT NOT NULL,
  correlation_id VARCHAR(64) NOT NULL,
  payload JSON NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  retry_count INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_at DATETIME NULL,
  INDEX idx_agent_event_outbox_status_created (status, created_at),
  INDEX idx_agent_event_outbox_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_event_consumption (
  event_id CHAR(36) NOT NULL,
  consumer VARCHAR(64) NOT NULL,
  consumed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (event_id, consumer)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

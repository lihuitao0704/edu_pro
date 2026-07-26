-- One expiry reminder per assessment without restricting normal alert types.
ALTER TABLE fin_risk_alert
  ADD COLUMN reminder_key VARCHAR(64) NULL COMMENT 'scheduler idempotency key',
  ADD UNIQUE KEY uq_fin_risk_alert_reminder_key (reminder_key);

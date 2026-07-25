-- Relay state for durable six-Agent event publication.

ALTER TABLE agent_event_outbox
  ADD COLUMN IF NOT EXISTS claimed_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS last_error TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_event_outbox_relay
  ON agent_event_outbox (status, claimed_at, created_at);

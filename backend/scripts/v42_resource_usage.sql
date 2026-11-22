-- V4.2 resource usage lifecycle ledger (PostgreSQL)
CREATE TABLE IF NOT EXISTS resource_usage (
  id VARCHAR(32) PRIMARY KEY,
  user_id VARCHAR(32) NOT NULL,
  conversation_id VARCHAR(32) NULL,
  run_id VARCHAR(32) NOT NULL,
  message_id VARCHAR(32) NULL,
  resource_type VARCHAR(24) NOT NULL,
  resource_id VARCHAR(128) NOT NULL,
  resource_name VARCHAR(400) NOT NULL DEFAULT '',
  stage VARCHAR(16) NOT NULL,
  selection_source VARCHAR(24) NOT NULL DEFAULT 'auto',
  retrieval_reason TEXT NULL,
  tool_name VARCHAR(64) NULL,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT uq_resource_usage_stage UNIQUE (run_id, resource_type, resource_id, stage)
);
CREATE INDEX IF NOT EXISTS ix_resource_usage_user_id ON resource_usage (user_id);
CREATE INDEX IF NOT EXISTS ix_resource_usage_run_id ON resource_usage (run_id);
CREATE INDEX IF NOT EXISTS ix_resource_usage_type ON resource_usage (resource_type);
CREATE INDEX IF NOT EXISTS ix_resource_usage_stage ON resource_usage (stage);

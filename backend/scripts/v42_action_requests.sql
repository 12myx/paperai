-- V4.2 persistent agent action ledger (PostgreSQL)
CREATE TABLE IF NOT EXISTS action_requests (
  id VARCHAR(256) PRIMARY KEY,
  user_id VARCHAR(32) NOT NULL,
  tool_name VARCHAR(64) NOT NULL,
  args_json TEXT NOT NULL DEFAULT '{}',
  args_digest VARCHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  confirmed_at TIMESTAMP NULL,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  result_summary TEXT NULL,
  error TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_action_requests_user_id ON action_requests (user_id);
CREATE INDEX IF NOT EXISTS ix_action_requests_tool_name ON action_requests (tool_name);
CREATE INDEX IF NOT EXISTS ix_action_requests_status ON action_requests (status);
CREATE INDEX IF NOT EXISTS ix_action_requests_expires_at ON action_requests (expires_at);

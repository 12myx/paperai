-- V4.2 academic artifact knowledge persistence (PostgreSQL)
ALTER TABLE academic_artifacts ADD COLUMN IF NOT EXISTS knowledge_item_ids JSON NOT NULL DEFAULT '[]';
ALTER TABLE academic_artifacts ADD COLUMN IF NOT EXISTS knowledge_saved_at TIMESTAMP NULL;

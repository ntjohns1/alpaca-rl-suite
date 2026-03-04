-- Migration 002: Add approval workflow fields
-- Adds manual approval gates to kaggle_training_job and policy_bundle tables

-- ─────────────────────────────────────────
-- kaggle_training_job approval fields
-- ─────────────────────────────────────────
ALTER TABLE kaggle_training_job
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (approval_status IN ('pending','approved','rejected')),
    ADD COLUMN IF NOT EXISTS approved_by     TEXT,
    ADD COLUMN IF NOT EXISTS approved_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- ─────────────────────────────────────────
-- policy_bundle approval fields
-- ─────────────────────────────────────────
ALTER TABLE policy_bundle
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (approval_status IN ('pending','approved','rejected')),
    ADD COLUMN IF NOT EXISTS approved_by     TEXT,
    ADD COLUMN IF NOT EXISTS approved_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Index for fast pending-approval queries
CREATE INDEX IF NOT EXISTS idx_kaggle_job_approval ON kaggle_training_job (approval_status, status);
CREATE INDEX IF NOT EXISTS idx_policy_bundle_approval ON policy_bundle (approval_status, promoted);

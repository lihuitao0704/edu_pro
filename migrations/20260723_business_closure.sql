-- Financial Agent business-closure schema migration
-- Apply once before running scripts/seed_demo_data.py.

ALTER TABLE sys_user
    ADD COLUMN IF NOT EXISTS balance DECIMAL(18, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE fin_product
    ADD COLUMN IF NOT EXISTS industry VARCHAR(64) NULL;

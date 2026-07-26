from pathlib import Path

from app.config.risk_level_mapping import RISK_LEVEL_MAPPING


MIGRATION = Path("migrations/20260727_risk_level_consistency.sql")


def test_migration_replaces_legacy_profile_column_with_explicit_pair():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN risk_level_code" in sql
    assert "ADD COLUMN risk_level_name" in sql
    assert "DROP COLUMN risk_level" in sql


def test_migration_accepts_legacy_alias_but_persists_only_standard_c4_name():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "WHEN '进取型' THEN 'C4'" in sql
    assert "WHEN 'C4' THEN '积极型'" in sql
    assert "THEN '进取型'" not in sql


def test_migration_restricts_every_customer_code_name_pair_and_assessment_code():
    sql = MIGRATION.read_text(encoding="utf-8")

    for code, name in RISK_LEVEL_MAPPING.items():
        assert f"risk_level_code = '{code}' AND risk_level_name = '{name}'" in sql
        assert f"'{code}'" in sql
    assert "chk_fin_customer_profile_risk_level_pair" in sql
    assert "chk_fin_risk_assessment_risk_level_code" in sql

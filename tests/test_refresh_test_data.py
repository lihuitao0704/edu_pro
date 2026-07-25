from app.model.entities import Base


def test_dataset_covers_every_mapped_table_with_at_least_target_rows():
    from scripts.refresh_test_data import TARGET_ROWS, build_dataset

    dataset = build_dataset(TARGET_ROWS)
    mapped_tables = set(Base.metadata.tables)

    assert TARGET_ROWS == 100
    assert {
        "sys_user",
        "fin_customer_profile",
        "fin_product",
        "fin_holdings",
        "fin_transaction",
    } <= set(dataset)
    assert mapped_tables == set(dataset)
    assert all(len(rows) >= TARGET_ROWS for rows in dataset.values())


def test_dataset_is_deterministic_and_uses_synthetic_customer_names():
    from scripts.refresh_test_data import TARGET_ROWS, build_dataset

    first = build_dataset(TARGET_ROWS)
    second = build_dataset(TARGET_ROWS)

    assert first == second
    assert first["sys_user"][0]["username"] == "refresh_customer_001"
    assert first["sys_user"][-1]["username"] == "refresh_customer_100"


def test_mysql_inventory_returns_sorted_base_table_names_only():
    from scripts.refresh_test_data import mysql_table_inventory

    class Cursor:
        def execute(self, statement):
            self.statement = statement

        def fetchall(self):
            return [("z_table",), ("a_table",)]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

    assert mysql_table_inventory(Connection()) == ["a_table", "z_table"]

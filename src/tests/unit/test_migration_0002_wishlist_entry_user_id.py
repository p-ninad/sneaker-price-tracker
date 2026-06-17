from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = Path(__file__).resolve().parents[3] / "migrations" / "versions" / (
    "0002_wishlist_entry_user_id.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_0002_wishlist_entry_user_id",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDialect:
    name = "postgresql"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeInspector:
    def __init__(
        self,
        *,
        columns: list[str],
        foreign_keys: list[dict[str, object]] | None = None,
        indexes: list[str] | None = None,
    ) -> None:
        self._columns = columns
        self._foreign_keys = foreign_keys or []
        self._indexes = indexes or []

    def get_columns(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "wishlist_entries"
        return [{"name": column_name} for column_name in self._columns]

    def get_foreign_keys(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "wishlist_entries"
        return list(self._foreign_keys)

    def get_indexes(self, table_name: str) -> list[dict[str, object]]:
        assert table_name == "wishlist_entries"
        return [{"name": index_name} for index_name in self._indexes]


def test_upgrade_rehomes_existing_foreign_key_without_adding_column(monkeypatch):
    migration = _load_migration_module()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record(name: str):
        def _record(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _record

    monkeypatch.setattr(migration.op, "get_bind", lambda: _FakeBind())
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda bind: _FakeInspector(
            columns=["id", "user_id", "source_url", "is_active"],
            foreign_keys=[
                {
                    "name": "wishlist_entries_user_id_fkey",
                    "constrained_columns": ["user_id"],
                    "referred_table": "users",
                    "referred_columns": ["id"],
                }
            ],
            indexes=["idx_wishlist_user_active"],
        ),
    )
    monkeypatch.setattr(migration.op, "add_column", record("add_column"))
    monkeypatch.setattr(migration.op, "drop_constraint", record("drop_constraint"))
    monkeypatch.setattr(migration.op, "create_foreign_key", record("create_foreign_key"))
    monkeypatch.setattr(migration.op, "create_index", record("create_index"))

    migration.upgrade()

    assert calls[0] == (
        "drop_constraint",
        ("wishlist_entries_user_id_fkey", "wishlist_entries"),
        {"type_": "foreignkey"},
    )
    assert calls[1] == (
        "create_foreign_key",
        (
            "fk_wishlist_entries_user_id_users",
            "wishlist_entries",
            "users",
            ["user_id"],
            ["id"],
        ),
        {},
    )
    assert len(calls) == 2


def test_upgrade_adds_missing_user_id_column(monkeypatch):
    migration = _load_migration_module()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record(name: str):
        def _record(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _record

    monkeypatch.setattr(migration.op, "get_bind", lambda: _FakeBind())
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda bind: _FakeInspector(columns=[], foreign_keys=[], indexes=[]),
    )
    monkeypatch.setattr(migration.op, "add_column", record("add_column"))
    monkeypatch.setattr(migration.op, "drop_constraint", record("drop_constraint"))
    monkeypatch.setattr(migration.op, "create_foreign_key", record("create_foreign_key"))
    monkeypatch.setattr(migration.op, "create_index", record("create_index"))

    migration.upgrade()

    assert calls[0][0] == "add_column"
    add_column_args = calls[0][1]
    assert add_column_args[0] == "wishlist_entries"
    column = add_column_args[1]
    assert column.name == "user_id"
    assert isinstance(column.type, sa.Integer)
    assert column.nullable is True

    assert calls[1] == (
        "create_foreign_key",
        (
            "fk_wishlist_entries_user_id_users",
            "wishlist_entries",
            "users",
            ["user_id"],
            ["id"],
        ),
        {},
    )
    assert calls[2] == (
        "create_index",
        (
            "idx_wishlist_user_active",
            "wishlist_entries",
            ["user_id", "is_active"],
        ),
        {"unique": False},
    )
    assert len(calls) == 3

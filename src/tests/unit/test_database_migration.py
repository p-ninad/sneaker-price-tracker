from __future__ import annotations


class _FakeConnection:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def execute(self, statement, params=None) -> None:
        self.calls.append(("execute", str(statement), params))


class _FakeContext:
    def __init__(self, calls: list[tuple], enter_label: str) -> None:
        self.calls = calls
        self.enter_label = enter_label
        self.connection = _FakeConnection(calls)

    def __enter__(self):
        self.calls.append((self.enter_label,))
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        self.calls.append(("end", exc_type))
        return False


class _FakeEngine:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.begin_context = _FakeContext(calls, "begin")
        self.connect_context = _FakeContext(calls, "connect")

    def begin(self):
        return self.begin_context

    def connect(self):
        return self.connect_context


def test_init_db_verifies_postgres_connection_without_creating_schema(monkeypatch):
    import app.database.db as db

    calls: list[tuple] = []
    engine = _FakeEngine(calls)

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "_database_backend", lambda: "postgresql")
    monkeypatch.setattr(
        db.Base.metadata,
        "create_all",
        lambda bind: calls.append(("create_all", bind)),
    )

    db.init_db()

    assert calls == [
        ("connect",),
        ("execute", "SELECT 1", None),
        ("end", None),
    ]


def test_init_db_creates_schema_directly_for_sqlite(monkeypatch):
    import app.database.db as db

    calls: list[tuple] = []
    engine = object()

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "_database_backend", lambda: "sqlite")
    monkeypatch.setattr(
        db.Base.metadata,
        "create_all",
        lambda bind: calls.append(("create_all", bind)),
    )

    db.init_db()

    assert calls == [("create_all", engine)]


def test_reset_db_drops_and_recreates_schema(monkeypatch):
    import app.database.db as db

    calls: list[tuple] = []
    engine = object()

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "_database_backend", lambda: "sqlite")
    monkeypatch.setattr(
        db.Base.metadata,
        "drop_all",
        lambda bind: calls.append(("drop_all", bind)),
    )
    monkeypatch.setattr(
        db.Base.metadata,
        "create_all",
        lambda bind: calls.append(("create_all", bind)),
    )

    db.reset_db()

    assert calls == [
        ("drop_all", engine),
        ("create_all", engine),
    ]


def test_reset_db_rejects_postgres(monkeypatch):
    import pytest

    import app.database.db as db

    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(db, "_database_backend", lambda: "postgresql")

    with pytest.raises(RuntimeError, match="disabled for PostgreSQL"):
        db.reset_db()

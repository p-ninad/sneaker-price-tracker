from __future__ import annotations


class _FakeConnection:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def execute(self, statement, params=None) -> None:
        self.calls.append(("execute", str(statement), params))


class _FakeBegin:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.connection = _FakeConnection(calls)

    def __enter__(self):
        self.calls.append(("begin",))
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        self.calls.append(("end", exc_type))
        return False


class _FakeEngine:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.context = _FakeBegin(calls)

    def begin(self):
        return self.context


def test_init_db_uses_postgres_schema_lock(monkeypatch):
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

    assert calls[0] == ("begin",)
    assert calls[1][0] == "execute"
    assert "pg_advisory_xact_lock" in calls[1][1]
    assert calls[1][2] == {"lock_key": db._POSTGRES_SCHEMA_LOCK_KEY}
    assert calls[2] == ("create_all", engine.context.connection)
    assert calls[3] == ("end", None)


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

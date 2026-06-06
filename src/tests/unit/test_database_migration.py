from __future__ import annotations


def test_init_db_runs_migrations_for_sqlite(monkeypatch):
    import app.database.db as db

    calls = []
    monkeypatch.setattr(db, "run_migrations", lambda: calls.append("migrated"))

    db.init_db()

    assert calls == ["migrated"]


def test_init_db_runs_migrations_for_postgres(monkeypatch):
    import app.database.db as db

    calls = []
    monkeypatch.setattr(db, "_database_backend", lambda: "postgresql")
    monkeypatch.setattr(db, "run_migrations", lambda: calls.append("migrated"))

    db.init_db()

    assert calls == ["migrated"]

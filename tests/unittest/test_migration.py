from __future__ import annotations

from pathlib import Path

import pytest

from app.bootstrap.migration import SchemaMigrationRunner


class FakeScalarResult:
    def __init__(self, value: int = 1) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value

    def fetchone(self):
        return self if self.value is not None else None

    def fetchall(self) -> list:
        return [self] if self.value is not None else []


class FakeConnection:
    def __init__(self, lock_result: int = 1) -> None:
        self.lock_result = lock_result
        self.executed_statements: list[str] = []
        self.committed = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        return None

    def execute(self, statement, params=None) -> FakeScalarResult:
        self.executed_statements.append(str(statement))
        if "GET_LOCK" in str(statement):
            return FakeScalarResult(self.lock_result)
        if "SELECT 1 FROM alembic_schema" in str(statement):
            return FakeScalarResult(None)  # no existing row
        if "SELECT version_num FROM alembic_schema" in str(statement):
            return FakeScalarResult(None)  # empty
        if "SELECT version_num FROM alembic_version" in str(statement):
            return FakeScalarResult("20260616_000007")
        return FakeScalarResult(1)

    def commit(self) -> None:
        self.committed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _mock_runner_internals(runner, monkeypatch, connection):
    """Mock internal methods so tests focus on lock / lifecycle behaviour."""
    monkeypatch.setattr(runner, "_ensure_alembic_schema_table", lambda conn: None)
    monkeypatch.setattr(runner, "_store_migration_sources", lambda conn, sc, db, tgt: None)
    monkeypatch.setattr(runner, "_get_local_head", lambda: "20260616_000007")
    monkeypatch.setattr(runner, "_get_db_revision", lambda conn: None)
    calls: list[tuple] = []
    monkeypatch.setattr(
        runner,
        "_run_alembic_command",
        lambda conn, cmd, target: calls.append((conn, cmd, target)),
    )
    return calls


def test_migration_runner_uses_mysql_named_lock(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="mysql+pymysql://user:pass@db/amsz")
    connection = FakeConnection(lock_result=1)
    engine = FakeEngine(connection)
    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    calls = _mock_runner_internals(runner, monkeypatch, connection)

    runner.run()

    assert calls == [(connection, "upgrade", "head")]
    assert any("GET_LOCK" in stmt for stmt in connection.executed_statements)
    assert any("RELEASE_LOCK" in stmt for stmt in connection.executed_statements)
    assert connection.committed is True
    assert engine.disposed is True


def test_migration_runner_exits_when_mysql_lock_not_acquired(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="mysql+pymysql://user:pass@db/amsz")
    connection = FakeConnection(lock_result=0)
    engine = FakeEngine(connection)
    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    calls = _mock_runner_internals(runner, monkeypatch, connection)

    with pytest.raises(SystemExit) as exc_info:
        runner.run()

    assert exc_info.value.code == 1
    assert calls == []


def test_migration_runner_skips_named_lock_for_sqlite(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="sqlite+pysqlite:///./amsz.db")
    connection = FakeConnection(lock_result=1)
    engine = FakeEngine(connection)
    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    calls = _mock_runner_internals(runner, monkeypatch, connection)

    runner.run()

    assert calls == [(connection, "upgrade", "head")]
    assert all("GET_LOCK" not in stmt for stmt in connection.executed_statements)


def test_alembic_ini_exists() -> None:
    assert Path("alembic.ini").exists()

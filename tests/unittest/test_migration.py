from __future__ import annotations

from pathlib import Path

import pytest

from app.bootstrap.migration import SchemaMigrationRunner


class FakeScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


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


def test_migration_runner_uses_mysql_named_lock(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="mysql+pymysql://user:pass@db/amsz")
    connection = FakeConnection(lock_result=1)
    engine = FakeEngine(connection)
    upgrade_calls: list[FakeConnection] = []

    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    monkeypatch.setattr(runner, "_run_upgrade", lambda conn: upgrade_calls.append(conn))

    runner.run()

    assert upgrade_calls == [connection]
    assert any("GET_LOCK" in stmt for stmt in connection.executed_statements)
    assert any("RELEASE_LOCK" in stmt for stmt in connection.executed_statements)
    assert connection.committed is True
    assert engine.disposed is True


def test_migration_runner_exits_when_mysql_lock_not_acquired(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="mysql+pymysql://user:pass@db/amsz")
    connection = FakeConnection(lock_result=0)
    engine = FakeEngine(connection)
    upgrade_calls: list[FakeConnection] = []

    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    monkeypatch.setattr(runner, "_run_upgrade", lambda conn: upgrade_calls.append(conn))

    with pytest.raises(SystemExit) as exc_info:
        runner.run()

    assert exc_info.value.code == 1
    assert upgrade_calls == []


def test_migration_runner_skips_named_lock_for_sqlite(monkeypatch) -> None:
    runner = SchemaMigrationRunner(database_url="sqlite+pysqlite:///./amsz.db")
    connection = FakeConnection(lock_result=1)
    engine = FakeEngine(connection)
    upgrade_calls: list[FakeConnection] = []

    monkeypatch.setattr(runner, "_create_engine", lambda: engine)
    monkeypatch.setattr(runner, "_run_upgrade", lambda conn: upgrade_calls.append(conn))

    runner.run()

    assert upgrade_calls == [connection]
    assert all("GET_LOCK" not in stmt for stmt in connection.executed_statements)


def test_alembic_ini_exists() -> None:
    assert Path("alembic.ini").exists()

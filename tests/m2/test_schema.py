from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from yourvpn_core.db import Base


EXPECTED_TABLES = {
    "access_group_routes",
    "access_groups",
    "alembic_version",
    "applications",
    "approval_records",
    "audit_logs",
    "device_access_groups",
    "devices",
    "install_packages",
    "jobs",
    "login_attempts",
    "password_tokens",
    "server_secrets",
    "sessions",
    "system_settings",
    "traffic_snapshots",
    "user_access_groups",
    "user_identities",
    "users",
    "worker_heartbeats",
}


def test_metadata_contains_v1_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES - {"alembic_version"}


def test_sqlite_alembic_upgrade_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "m2.sqlite3"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    tables = set(inspect(engine).get_table_names())
    assert tables == EXPECTED_TABLES

    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"id", "email", "role", "status", "approved_device_limit"}.issubset(user_columns)

    indexes = {index["name"] for index in inspect(engine).get_indexes("jobs")}
    assert {"ix_jobs_status_run_after", "ix_jobs_locked_at"}.issubset(indexes)


def test_alembic_config_resolves_migrations_from_config_path(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m2-other-cwd.sqlite3"
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_mysql_ddl_compiles_for_schema() -> None:
    dialect = mysql.dialect()

    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))

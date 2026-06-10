"""Extra unit tests for the database package (dialect helpers, DDL, env)."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

from pyvelm.database import create_database_from_dsn, dialect_capabilities
from pyvelm.database.adapter import (
    ConnectionAdapter,
    ExecuteResult,
    conn_capabilities,
    sqlalchemy_connection,
)
from pyvelm.database.capabilities import SchemaResetStrategy
from pyvelm.database.ddl import (
    add_column_if_missing,
    append_search_pagination,
    create_table_sql,
    fetch_lastrowid,
    ilike_sql,
    ir_module_create_sql,
    ir_module_table,
    migration_supported,
    normalize_column_ddl,
    normalize_sql_type,
    reset_schema,
    returning_id_clause,
    serial_primary_key,
    supports_create_table_if_not_exists,
    timestamp_sql_type,
    now_sql,
    string_sql_type,
)
from pyvelm.database.dialects import (
    configure_engine,
    dialect_capabilities as dialect_caps,
    get_backend,
    normalize_dsn_with_dialects,
)
from pyvelm.database.dialects import mssql, mysql, oracle, postgresql, sqlite
from pyvelm.database.env import (
    app_dsn_from_env,
    dsn_display,
    load_testing_env,
    require_test_dsn_from_env,
    uses_serverless_schema_wipe,
    warn_if_poor_nuke_dsn,
)
from pyvelm.database.introspection import column_exists, table_exists
from pyvelm.database.sqlite_runtime import (
    delete_sqlite_file,
    resolve_sqlite_dsn_for_runtime,
    sqlite_file_path,
)


class ExecuteResultTests(unittest.TestCase):
    def test_empty_rows(self):
        r = ExecuteResult()
        self.assertEqual(r.fetchall(), [])
        self.assertIsNone(r.fetchone())
        self.assertEqual(r.rowcount, -1)

    def test_with_rows(self):
        r = ExecuteResult(rows=[(1, "a"), (2, "b")], rowcount=2)
        self.assertEqual(r.fetchall(), [(1, "a"), (2, "b")])
        self.assertEqual(r.fetchone(), (1, "a"))


class DialectRegistryTests(unittest.TestCase):
    def test_unknown_backend_falls_back_to_postgresql(self):
        self.assertIs(get_backend("unknown"), postgresql)

    def test_dialect_base_name_aliases(self):
        from pyvelm.database.capabilities import dialect_base_name

        self.assertEqual(dialect_base_name("mariadb+pymysql"), "mysql")
        self.assertEqual(dialect_base_name("sqlserver+pyodbc"), "mssql")

    def test_normalize_dsn_with_dialects(self):
        self.assertIn(
            "+psycopg",
            normalize_dsn_with_dialects("postgresql://localhost/x"),
        )
        self.assertIn(
            "+pymysql",
            normalize_dsn_with_dialects("mysql://localhost/x"),
        )

    def test_configure_engine_dispatches(self):
        engine = MagicMock()
        configure_engine(engine, dialect_caps("postgresql"))
        configure_engine(engine, dialect_caps("oracle"))
        with patch.object(mysql, "configure_engine") as mysql_cfg, patch.object(
            mssql, "configure_engine"
        ) as mssql_cfg:
            configure_engine(engine, dialect_caps("mysql"))
            configure_engine(engine, dialect_caps("mssql"))
        mysql_cfg.assert_called_once_with(engine)
        mssql_cfg.assert_called_once_with(engine)


class DialectHelperTests(unittest.TestCase):
    def _conn(self, row):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = row
        return conn

    def test_postgresql_fetch_lastrowid(self):
        self.assertEqual(
            postgresql.fetch_lastrowid(self._conn((7,)), "t"),
            7,
        )
        self.assertEqual(
            postgresql.fetch_lastrowid(self._conn((None,)), "t"),
            0,
        )

    def test_postgresql_helpers(self):
        self.assertIn("SERIAL", postgresql.serial_primary_key())
        self.assertEqual(postgresql.timestamp_sql_type(), "timestamptz")
        self.assertEqual(postgresql.now_sql(), "now()")
        self.assertEqual(postgresql.string_sql_type(), "text")
        self.assertTrue(postgresql.supports_create_table_if_not_exists())
        sql = postgresql.append_search_pagination(
            "SELECT 1",
            base_table_sql="t",
            limit=5,
            offset=2,
            order=None,
        )
        self.assertIn("LIMIT 5", sql)
        self.assertIn("OFFSET 2", sql)
        self.assertEqual(postgresql.bind_params((1, 2)), (1, 2))
        conn = MagicMock()
        postgresql.before_reset_all_tables(conn)
        postgresql.after_reset_all_tables(conn)
        self.assertIn(
            "+psycopg",
            postgresql.normalize_dsn("postgres://localhost/db") or "",
        )

    def test_mysql_fetch_lastrowid(self):
        self.assertEqual(mysql.fetch_lastrowid(self._conn((3,)), "t"), 3)

    def test_mssql_fetch_lastrowid(self):
        self.assertEqual(mssql.fetch_lastrowid(self._conn((9,)), "t"), 9)

    def test_oracle_fetch_lastrowid(self):
        self.assertEqual(oracle.fetch_lastrowid(self._conn((2,)), "t"), 2)

    def test_sqlite_fetch_lastrowid(self):
        self.assertEqual(sqlite.fetch_lastrowid(self._conn((4,)), "t"), 4)

    def test_oracle_pagination_with_order(self):
        sql = oracle.append_search_pagination(
            'SELECT "t"."id" FROM "t"',
            base_table_sql='"t"',
            limit=5,
            offset=0,
            order='"t"."name"',
        )
        self.assertIn('ORDER BY "t"."name"', sql)
        self.assertIn("FETCH NEXT 5 ROWS ONLY", sql)

    def test_oracle_pagination_default_order(self):
        sql = oracle.append_search_pagination(
            'SELECT "t"."id" FROM "t"',
            base_table_sql='"t"',
            limit=None,
            offset=2,
            order=None,
        )
        self.assertIn('ORDER BY "t"."id"', sql)
        self.assertIn("OFFSET 2 ROWS", sql)
        self.assertNotIn("FETCH", sql)

    def test_mssql_pagination(self):
        sql = mssql.append_search_pagination(
            'SELECT "t"."id" FROM "t"',
            base_table_sql='"t"',
            limit=10,
            offset=0,
            order=None,
        )
        self.assertIn('ORDER BY "t"."id"', sql)
        self.assertIn("FETCH NEXT 10 ROWS ONLY", sql)

    def test_mysql_pagination_limit_offset(self):
        sql = mysql.append_search_pagination(
            "SELECT 1",
            base_table_sql='"t"',
            limit=20,
            offset=5,
            order=None,
        )
        self.assertIn("LIMIT 20", sql)
        self.assertIn("OFFSET 5", sql)

    def test_sqlite_bind_params_datetime_types(self):
        bound = sqlite.bind_params(
            (datetime(2024, 1, 2, 3, 4, 5), date(2024, 1, 2), time(12, 30), "x")
        )
        self.assertEqual(bound[0], "2024-01-02 03:04:05")
        self.assertEqual(bound[1], "2024-01-02")
        self.assertEqual(bound[2], "12:30:00")
        self.assertEqual(bound[3], "x")

    def test_duplicate_column_errors(self):
        self.assertTrue(mysql.is_duplicate_column_error("duplicate column name"))
        self.assertTrue(mssql.is_duplicate_column_error("already an object named x"))
        self.assertTrue(oracle.is_duplicate_column_error("name is already used"))
        self.assertTrue(sqlite.is_duplicate_column_error("duplicate column"))
        self.assertFalse(postgresql.is_duplicate_column_error("anything"))

    def test_mysql_mssql_configure_engine_registers_listener(self):
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")
        mysql.configure_engine(engine)
        mssql.configure_engine(engine)
        # Listeners registered — no error means connect hook is wired.
        self.assertTrue(hasattr(engine, "dispatch"))
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        executed: list[str] = []

        wire_sa_conn(
            conn,
            executed,
            base_execute=lambda sql, params=None: MagicMock(),
        )
        mysql.before_reset_all_tables(conn)
        mysql.after_reset_all_tables(conn)
        self.assertIn("FOREIGN_KEY_CHECKS = 0", executed[0])
        self.assertIn("FOREIGN_KEY_CHECKS = 1", executed[1])

    def test_mssql_before_reset_drops_fks(self):
        conn = MagicMock()
        mssql.before_reset_all_tables(conn)
        self.assertIn("sys.foreign_keys", conn.execute.call_args[0][0])

    def test_normalize_dsn_per_dialect(self):
        self.assertEqual(
            mysql.normalize_dsn("mysql://localhost/db"),
            "mysql+pymysql://localhost/db",
        )
        self.assertEqual(
            mysql.normalize_dsn("mariadb://localhost/db"),
            "mariadb+pymysql://localhost/db",
        )
        self.assertEqual(
            mssql.normalize_dsn("sqlserver://localhost/db"),
            "mssql+pyodbc://localhost/db",
        )
        self.assertEqual(
            oracle.normalize_dsn("oracle://localhost/db"),
            "oracle+oracledb://localhost/db",
        )
        self.assertEqual(
            postgresql.normalize_dsn("postgres://localhost/db"),
            "postgresql+psycopg://localhost/db",
        )

    def test_portable_type_maps(self):
        cap = dialect_caps("oracle")
        self.assertIn("FLOAT", normalize_sql_type("double precision", cap))
        self.assertIn("CLOB", normalize_column_ddl('"x" text', cap))


class DdlHelperTests(unittest.TestCase):
    def test_serial_primary_key_dispatch(self):
        self.assertIn("SERIAL", serial_primary_key(dialect_caps("postgresql")))
        self.assertIn("IDENTITY", serial_primary_key(dialect_caps("mssql")))

    def test_ilike_sql(self):
        self.assertIn("ILIKE", ilike_sql('"x"', dialect_caps("postgresql")))
        self.assertIn("LOWER", ilike_sql('"x"', dialect_caps("mysql")))

    def test_append_search_pagination_oracle_branch(self):
        cap = dialect_caps("oracle")
        sql = append_search_pagination(
            "SELECT 1",
            base_table_sql='"t"',
            limit=5,
            offset=0,
            order='"t"."name"',
            cap=cap,
        )
        self.assertIn("FETCH", sql)

    def test_returning_id_clause(self):
        pg = dialect_caps("postgresql")
        sq = dialect_caps("sqlite")
        my = dialect_caps("mysql")
        ora = dialect_caps("oracle")
        self.assertIn("RETURNING", returning_id_clause(pg))
        self.assertIn("RETURNING", returning_id_clause(sq))
        self.assertEqual(returning_id_clause(my), "")
        self.assertEqual(returning_id_clause(ora), "")

    def test_append_search_pagination_noop(self):
        cap = dialect_caps("postgresql")
        sql = "SELECT 1"
        self.assertEqual(
            append_search_pagination(
                sql, base_table_sql='"t"', limit=None, offset=0, order=None, cap=cap
            ),
            sql,
        )

    def test_create_table_sql(self):
        from pyvelm.database.sa_ddl import primary_key_column

        cap = dialect_caps("sqlite")
        self.assertIn(
            "IF NOT EXISTS",
            create_table_sql("t", [primary_key_column(cap)], cap),
        )
        cap_oracle = dialect_caps("oracle")
        self.assertNotIn(
            "IF NOT EXISTS",
            create_table_sql("t", [primary_key_column(cap_oracle)], cap_oracle),
        )
        cap_mssql = dialect_caps("mssql")
        self.assertNotIn(
            "IF NOT EXISTS",
            create_table_sql("t", [primary_key_column(cap_mssql)], cap_mssql),
        )

    def test_reset_schema_unsupported(self):
        conn = MagicMock()
        cap = dialect_caps("postgresql").__class__(
            name="unknown",
            supports_returning=False,
            supports_ilike=False,
            supports_add_column_if_not_exists=False,
            supports_drop_schema=False,
            schema_reset=SchemaResetStrategy.DELETE_FILE,
            placeholder="%s",
        )
        with self.assertRaises(RuntimeError):
            reset_schema(conn, cap)

    def test_reset_schema_drop_all_without_sa_connection(self):
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        executed: list[str] = []

        def base_execute(sql, params=None):
            executed.append(sql)
            return MagicMock()

        wire_sa_conn(
            conn, executed, dialect_name="sqlite", base_execute=base_execute
        )
        conn._sa.engine = MagicMock()
        with patch("pyvelm.database.ddl.sqlalchemy_connection", return_value=None):
            with patch("pyvelm.database.ddl.inspect") as sa_inspect:
                sa_inspect.return_value.get_table_names.return_value = ["demo"]
                reset_schema(conn, dialect_caps("sqlite"))
        self.assertTrue(any("DROP TABLE" in s for s in executed))

    def test_reset_schema_oracle_plain_drop(self):
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        executed: list[str] = []

        def base_execute(sql, params=None):
            executed.append(sql)
            return MagicMock()

        wire_sa_conn(conn, executed, dialect_name="oracle", base_execute=base_execute)
        conn._sa.engine = MagicMock()
        with patch.object(oracle, "reset_all_tables", None), patch(
            "pyvelm.database.ddl.sqlalchemy_connection", return_value=None
        ), patch("pyvelm.database.ddl.inspect") as sa_inspect:
            sa_inspect.return_value.get_table_names.return_value = ["demo"]
            reset_schema(conn, dialect_caps("oracle"))
        self.assertIn('DROP TABLE "demo"', executed)

    def test_reset_schema_drop_all_tables_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ddl_reset.db"
            db = create_database_from_dsn(f"sqlite:///{path}", pool_size=1)
            with db.connect() as conn:
                conn.execute(
                    'CREATE TABLE "demo" ("id" INTEGER PRIMARY KEY, "name" text)'
                )
                self.assertTrue(table_exists(conn, "demo"))
                reset_schema(conn, db.capabilities)
                self.assertFalse(table_exists(conn, "demo"))
            db.dispose()

    def test_add_column_if_missing_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "add_col.db"
            db = create_database_from_dsn(f"sqlite:///{path}", pool_size=1)
            with db.connect() as conn:
                conn.execute('CREATE TABLE "demo" ("id" INTEGER PRIMARY KEY)')
                self.assertTrue(
                    add_column_if_missing(conn, "demo", "name", "text", db.capabilities)
                )
                self.assertTrue(column_exists(conn, "demo", "name"))
                self.assertFalse(
                    add_column_if_missing(conn, "demo", "name", "text", db.capabilities)
                )
            db.dispose()

    def test_add_column_duplicate_error_swallowed(self):
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        cap = dialect_caps("mysql")

        def base_execute(sql, params=None):
            raise RuntimeError("duplicate column name")

        wire_sa_conn(conn, [], dialect_name="mysql", base_execute=base_execute)
        with patch(
            "pyvelm.database.introspection.column_exists", return_value=False
        ), patch("pyvelm.database.introspection.table_exists", return_value=True):
            self.assertFalse(
                add_column_if_missing(conn, "t", "c", "text", cap)
            )

    def test_add_column_if_missing_table_absent(self):
        conn = MagicMock()
        cap = dialect_caps("postgresql")
        with patch("pyvelm.database.introspection.table_exists", return_value=False):
            self.assertFalse(add_column_if_missing(conn, "t", "c", "text", cap))

    def test_add_column_if_missing_with_field_and_registry(self):
        from pyvelm.fields import Char
        from pyvelm.model import BaseModel
        from pyvelm.registry import Registry
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        reg = Registry()
        with reg.activate():

            class Demo(BaseModel):
                _name = "demo.tag"
                _table = "demo_tag"
                name = Char()

        conn = MagicMock()
        cap = dialect_caps("sqlite")
        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="sqlite")
        with patch(
            "pyvelm.database.introspection.table_exists", return_value=True
        ), patch("pyvelm.database.introspection.column_exists", return_value=False):
            self.assertTrue(
                add_column_if_missing(
                    conn,
                    "demo_tag",
                    "name",
                    "text",
                    cap,
                    registry=reg,
                    field=Demo._fields["name"],
                )
            )

    def test_add_column_missing_table_error_swallowed(self):
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        cap = dialect_caps("mssql")

        def base_execute(sql, params=None):
            raise RuntimeError("42s02 object does not exist")

        wire_sa_conn(conn, [], dialect_name="mssql", base_execute=base_execute)
        with patch(
            "pyvelm.database.introspection.column_exists", return_value=False
        ), patch("pyvelm.database.introspection.table_exists", return_value=True):
            self.assertFalse(add_column_if_missing(conn, "t", "c", "text", cap))

    def test_migration_supported_and_ddl_helpers(self):
        conn = MagicMock()
        conn.dialect_name = "postgresql"
        self.assertTrue(migration_supported(conn, ("postgresql",)))
        self.assertFalse(migration_supported(conn, ("mysql",)))
        self.assertTrue(migration_supported(conn, None))
        cap = dialect_caps("mysql")
        self.assertTrue(supports_create_table_if_not_exists(cap))
        self.assertIn("TIMESTAMP", timestamp_sql_type(cap))
        self.assertIn("CURRENT", now_sql(cap))
        self.assertIn("VARCHAR", string_sql_type(cap, primary_key=True))
        tbl = ir_module_table(cap)
        self.assertEqual(tbl.name, "ir_module")
        self.assertIn("ir_module", ir_module_create_sql(cap))

    def test_fetch_lastrowid_dispatch(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        conn.execute.return_value.fetchone.return_value = (11,)
        self.assertEqual(fetch_lastrowid(conn, "t"), 11)


class EnvHelperTests(unittest.TestCase):
    def test_load_testing_env_import_error(self):
        with patch.dict("sys.modules", {"dotenv": None}):
            self.assertFalse(load_testing_env())

    def test_load_testing_env_finds_file(self):
        fake_dotenv = MagicMock()
        fake_dotenv.find_dotenv.return_value = "/tmp/.env.testing"
        with patch.dict("sys.modules", {"dotenv": fake_dotenv}):
            self.assertTrue(load_testing_env())
        fake_dotenv.load_dotenv.assert_called_once()

    def test_require_test_dsn_exits(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                require_test_dsn_from_env()

    def test_require_test_dsn_returns_normalized(self):
        with patch.dict(
            os.environ,
            {"PYVELM_DSN_TEST": "postgresql://localhost/pyvelm_test"},
            clear=True,
        ):
            self.assertIn(
                "+psycopg",
                require_test_dsn_from_env(),
            )

    def test_nuke_dsn_exits_when_unset(self):
        from pyvelm.database.env import nuke_dsn_from_env

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                nuke_dsn_from_env()

    def test_is_supabase_direct_host_invalid_dsn(self):
        from pyvelm.database.env import is_supabase_direct_host

        with patch("pyvelm.database.env.normalize_dsn", side_effect=ValueError("bad")):
            self.assertFalse(is_supabase_direct_host("not-a-dsn"))

    def test_app_dsn_from_env(self):
        with patch.dict(
            os.environ,
            {"PYVELM_DSN": "postgresql://localhost/app"},
            clear=True,
        ):
            self.assertIn("+psycopg", app_dsn_from_env() or "")

    def test_dsn_display_sqlite_netloc(self):
        shown = dsn_display("sqlite://host/path/to.db")
        self.assertIn("sqlite://", shown)
        self.assertIn("host", shown)

    def test_dsn_display_postgres_redacts_password(self):
        shown = dsn_display("postgresql://user:secret@localhost:5432/db")
        self.assertIn("user:***", shown)
        self.assertNotIn("secret", shown)

    def test_dsn_display_invalid_fallback(self):
        with patch("pyvelm.database.env.normalize_dsn", side_effect=ValueError("bad")):
            self.assertEqual(dsn_display("not-a-dsn"), "<dsn>")

    def test_uses_serverless_schema_wipe_flag(self):
        with patch.dict(os.environ, {"PYVELM_NUKE_SERVERLESS": "yes"}, clear=True):
            self.assertTrue(uses_serverless_schema_wipe())

    def test_warn_if_poor_nuke_dsn_pooler(self):
        with patch.dict(
            os.environ,
            {"PYVELM_NUKE_SERVERLESS": "1"},
            clear=True,
        ):
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                warn_if_poor_nuke_dsn(
                    "postgresql://u:p@pooler.example.com:6543/postgres"
                )
            self.assertIn("transaction pooler", buf.getvalue())

    def test_warn_if_poor_nuke_dsn_supabase_direct(self):
        with patch.dict(
            os.environ,
            {"PYVELM_NUKE_SERVERLESS": "1"},
            clear=True,
        ):
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                warn_if_poor_nuke_dsn(
                    "postgresql://u:p@db.abc123.supabase.co:5432/postgres"
                )
            self.assertIn("IPv6-only", buf.getvalue())


class SqliteRuntimeMoreTests(unittest.TestCase):
    def test_sqlite_file_path_variants(self):
        self.assertEqual(
            sqlite_file_path("sqlite:////absolute/path.db"),
            "/absolute/path.db",
        )
        self.assertEqual(
            sqlite_file_path("sqlite://host.net/share.db"),
            "/host.net/share.db",
        )
        self.assertIsNone(sqlite_file_path("postgresql://localhost/x"))

    def test_resolve_reuses_existing_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.db"
            seed.write_bytes(b"x")
            with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
                first = resolve_sqlite_dsn_for_runtime(f"sqlite:///{seed}")
                dest = sqlite_file_path(first)
                assert dest is not None
                Path(dest).write_bytes(b"cached")
                second = resolve_sqlite_dsn_for_runtime(f"sqlite:///{seed}")
            self.assertEqual(first, second)

    def test_resolve_writable_tmp_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "live.db"
            src.write_bytes(b"live")
            with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
                out = resolve_sqlite_dsn_for_runtime(f"sqlite:///{src}")
            self.assertEqual(out, f"sqlite:///{src.resolve()}")

    def test_delete_sqlite_file(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
            f.write(b"x")
        dsn = f"sqlite:///{path}"
        delete_sqlite_file(dsn)
        self.assertFalse(Path(path).is_file())


class IntrospectionMockTests(unittest.TestCase):
    def test_column_exists_via_sqlalchemy_inspector(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        sa_conn = object()
        with patch(
            "pyvelm.database.introspection._inspector_sa_connection",
            return_value=sa_conn,
        ), patch(
            "pyvelm.database.introspection.table_exists",
            return_value=True,
        ):
            inspector = MagicMock()
            inspector.get_table_names.return_value = ["demo"]
            inspector.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
            with patch("sqlalchemy.inspect", return_value=inspector):
                self.assertTrue(column_exists(conn, "demo", "name"))
                self.assertFalse(column_exists(conn, "demo", "missing"))
                inspector.get_table_names.return_value = ["DEMO"]
                self.assertTrue(column_exists(conn, "demo", "name"))

    def test_table_exists_information_schema_fallback(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        conn.execute.return_value.fetchone.return_value = (1,)
        with patch(
            "pyvelm.database.introspection.sqlalchemy_connection",
            return_value=None,
        ):
            self.assertTrue(table_exists(conn, "demo"))


class ConnectionAdapterMoreTests(unittest.TestCase):
    def test_placeholder_conversion_sqlite(self):
        cap = dialect_caps("sqlite")
        adapter = ConnectionAdapter(MagicMock(), capabilities=cap)
        self.assertEqual(adapter._convert_sql("WHERE x = %s"), "WHERE x = ?")

    def test_placeholder_conversion_mssql(self):
        cap = dialect_caps("mssql")
        adapter = ConnectionAdapter(MagicMock(), capabilities=cap)
        self.assertEqual(cap.placeholder, "?")
        self.assertEqual(adapter._convert_sql('WHERE "name" = %s'), 'WHERE "name" = ?')
        self.assertEqual(
            adapter._convert_sql('SELECT "id" FROM "t" WHERE TRUE'),
            'SELECT "id" FROM "t" WHERE 1=1',
        )

    def test_placeholder_conversion_oracle(self):
        cap = dialect_caps("oracle")
        adapter = ConnectionAdapter(MagicMock(), capabilities=cap)
        self.assertEqual(
            adapter._convert_sql('WHERE "name" = %s AND "version" = %s'),
            'WHERE "name" = :1 AND "version" = :2',
        )

    def test_commit_rollback_via_dbapi(self):
        dbapi = MagicMock()
        dbapi.autocommit = False
        adapter = ConnectionAdapter(None, capabilities=dialect_caps("postgresql"), dbapi_conn=dbapi)
        adapter.commit()
        adapter.rollback()
        dbapi.commit.assert_called_once()
        dbapi.rollback.assert_called_once()

    def test_close_autocommit_commits(self):
        sa = MagicMock()
        adapter = ConnectionAdapter(sa, capabilities=dialect_caps("postgresql"))
        adapter.autocommit = True
        adapter.close()
        sa.commit.assert_called_once()
        sa.close.assert_called_once()

    def test_close_autocommit_commit_failure_rolls_back(self):
        sa = MagicMock()
        sa.commit.side_effect = RuntimeError("fail")
        adapter = ConnectionAdapter(sa, capabilities=dialect_caps("postgresql"))
        adapter.autocommit = True
        adapter.close()
        sa.rollback.assert_called_once()

    def test_conn_capabilities_fallbacks(self):
        conn = MagicMock(spec=[])
        conn.dialect_name = "sqlite"
        self.assertEqual(conn_capabilities(conn).name, "sqlite")
        bare = MagicMock(spec=[])
        self.assertEqual(conn_capabilities(bare).name, "postgresql")

    def test_sqlalchemy_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sa_conn.db"
            db = create_database_from_dsn(f"sqlite:///{path}", pool_size=1)
            with db.engine.connect() as sa:
                adapter = ConnectionAdapter.from_sa_connection(sa, db.capabilities)
                self.assertIs(sqlalchemy_connection(adapter), sa)
            db.dispose()

    def test_open_connection_and_dispose(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "adapter.db"
            db = create_database_from_dsn(f"sqlite:///{path}", pool_size=1)
            conn = db.open_connection()
            try:
                conn.execute('CREATE TABLE "x" ("id" INTEGER PRIMARY KEY)')
            finally:
                conn.close()
            self.assertIsNotNone(db.inspector())
            db.dispose()


class DdlRemainingGapsTests(unittest.TestCase):
    def test_add_column_if_not_exists_postgres(self):
        from pyvelm.database.ddl import add_column_if_not_exists_sql

        cap = dialect_caps("postgresql")
        sql = add_column_if_not_exists_sql("t", "c", "text", cap)
        self.assertIn("IF NOT EXISTS", sql or "")
        self.assertIsNone(add_column_if_not_exists_sql("t", "c", "text", dialect_caps("mysql")))

    def test_add_column_sql_mssql_oracle_omit_column_keyword(self):
        from pyvelm.database.ddl import add_column_sql

        mssql_sql = add_column_sql("t", "c", "BIT", dialect_caps("mssql"))
        self.assertEqual(mssql_sql, "ALTER TABLE [t] ADD [c] BIT")
        self.assertNotIn("ADD COLUMN", mssql_sql)
        oracle_sql = add_column_sql("t", "c", "INTEGER", dialect_caps("oracle"))
        self.assertEqual(oracle_sql, 'ALTER TABLE "t" ADD "c" INTEGER')

    def test_sa_type_for_field_mssql_text_uses_nvarchar_max(self):
        from sqlalchemy.dialects.mssql import NVARCHAR

        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import compile_create_table, model_table_columns
        from pyvelm.fields import Text
        from pyvelm.model import BaseModel
        from pyvelm.registry import Registry

        cap = dialect_capabilities("mssql")
        reg = Registry()
        with reg.activate():

            class Demo(BaseModel):
                _name = "demo.arch"
                _table = "demo_arch"
                arch = Text()

        cols = model_table_columns(Demo, reg, cap)
        from pyvelm.database.sa_ddl import table_from_columns

        tbl = table_from_columns("demo_arch", cols, cap=cap)
        sql = compile_create_table(tbl, cap)
        self.assertIn("NVARCHAR(MAX)", sql.upper().replace(" ", ""))
        arch_col = next(c for c in cols if c.name == "arch")
        self.assertIsInstance(arch_col.type, NVARCHAR)
        self.assertIsNone(arch_col.type.length)

    def test_effective_fk_ondelete_mssql_maps_cascade_actions_to_no_action(self):
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import effective_fk_ondelete

        cap = dialect_capabilities("mssql")
        for action in ("CASCADE", "SET NULL", "set null"):
            self.assertEqual(
                effective_fk_ondelete(
                    action,
                    local_table="res_partner",
                    ref_table="res_country",
                    cap=cap,
                ),
                "NO ACTION",
                action,
            )
        self.assertEqual(
            effective_fk_ondelete(
                "CASCADE",
                local_table="res_partner",
                ref_table="res_country",
                cap=dialect_capabilities("postgresql"),
            ),
            "CASCADE",
        )

    def test_core_table_insert_uses_field_column_types(self):
        from datetime import datetime

        from sqlalchemy import bindparam, insert

        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import _sqlalchemy_dialect, core_table
        from pyvelm.fields import Char, Datetime
        from pyvelm.model import BaseModel
        from pyvelm.registry import Registry

        cap = dialect_capabilities("postgresql")
        reg = Registry()
        with reg.activate():

            class Group(BaseModel):
                _name = "res.groups"
                _table = "res_groups"
                name = Char(required=True)
                created_at = Datetime()
                updated_at = Datetime()

        tbl = core_table(
            "res_groups",
            cap,
            "name",
            "created_at",
            "updated_at",
            "id",
            registry=reg,
            model_cls=Group,
        )
        now = datetime(2026, 6, 1, 12, 0, 0)
        stmt = insert(tbl).values(
            name=bindparam("name"),
            created_at=bindparam("created_at"),
            updated_at=bindparam("updated_at"),
        ).returning(tbl.c.id)
        sql = str(
            stmt.compile(
                dialect=_sqlalchemy_dialect(cap),
                compile_kwargs={"literal_binds": False},
            )
        )
        self.assertNotIn("::VARCHAR", sql)
        self.assertIn("created_at", sql)

    def test_core_table_dml_matches_ddl_quoting(self):
        from sqlalchemy import insert

        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import _sqlalchemy_dialect, core_table

        for dialect, needle in (
            ("oracle", '"res_groups"'),
            ("mssql", "[res_groups]"),
        ):
            with self.subTest(dialect=dialect):
                cap = dialect_capabilities(dialect)
                tbl = core_table("res_groups", cap, "id", "name")
                sql = str(
                    insert(tbl)
                    .values(name="Admin")
                    .compile(dialect=_sqlalchemy_dialect(cap))
                )
                self.assertIn(needle, sql)

    def test_execute_create_table_skips_existing_fk_stub(self):
        """Oracle has no CREATE IF NOT EXISTS; stub targets may already exist."""
        from unittest.mock import MagicMock, patch

        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import (
            _execute_create_table_stmt,
            primary_key_column,
            table_from_columns,
        )
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        cap = dialect_capabilities("oracle")
        conn = MagicMock()
        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="oracle")
        stub = table_from_columns("res_region", [primary_key_column(cap)], cap=cap)

        with patch("pyvelm.database.introspection.table_exists", return_value=True):
            _execute_create_table_stmt(
                conn, conn._sa, stub, cap=cap, if_not_exists=False
            )
        self.assertEqual(executed, [])

    def test_execute_create_table_swallows_duplicate_object(self):
        from unittest.mock import MagicMock, patch

        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import (
            _execute_create_table_stmt,
            primary_key_column,
            table_from_columns,
        )
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        cap = dialect_capabilities("oracle")
        conn = MagicMock()
        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="oracle")
        tbl = table_from_columns("res_region", [primary_key_column(cap)], cap=cap)

        def boom(stmt, params=None):
            raise Exception("ORA-00955: name is already used by an existing object")

        conn._sa.execute = boom
        with patch("pyvelm.database.introspection.table_exists", return_value=False):
            _execute_create_table_stmt(
                conn, conn._sa, tbl, cap=cap, if_not_exists=False
            )

    def test_compile_add_column_mssql_requires_table_bound_column(self):
        from sqlalchemy import Column
        from sqlalchemy.dialects.mssql import NVARCHAR

        from pyvelm.database.sa_ddl import compile_add_column

        col = Column("name", NVARCHAR(255), nullable=False)
        sql = compile_add_column("res_partner", col, dialect_caps("mssql"))
        self.assertIn("NVARCHAR", sql)
        self.assertIn("ADD", sql.upper())
        self.assertIn("[res_partner]", sql)

    def test_reset_schema_drop_schema_path(self):
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        executed: list[str] = []

        wire_sa_conn(
            conn,
            executed,
            base_execute=lambda sql, params=None: MagicMock(),
        )
        cap = dialect_caps("postgresql")
        reset_schema(conn, cap)
        self.assertTrue(any("DROP SCHEMA" in s for s in executed))
        self.assertTrue(any("CREATE SCHEMA" in s for s in executed))

    def test_reset_schema_oracle_uses_user_tables_and_purges(self):
        """Oracle reset must not rely on the inspector (it hides recyclebin
        objects). It queries user_tables, drops with CASCADE CONSTRAINTS PURGE,
        then empties the recyclebin so nothing resurfaces as ORA-00955."""
        conn = MagicMock()

        def execute(sql, params=None):
            r = MagicMock()
            if "user_tables" in sql.lower():
                r.fetchall.return_value = [("base_automation",), ("res_partner",)]
            else:
                r.fetchall.return_value = []
            return r

        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="oracle", base_execute=execute)
        reset_schema(conn, dialect_caps("oracle"))
        calls = executed
        self.assertTrue(any("user_tables" in s.lower() for s in calls))
        self.assertIn(
            'DROP TABLE "base_automation" CASCADE CONSTRAINTS PURGE', calls
        )
        self.assertIn('DROP TABLE "res_partner" CASCADE CONSTRAINTS PURGE', calls)
        self.assertIn("PURGE RECYCLEBIN", calls)

    def test_normalize_helpers_empty_map(self):
        cap = dialect_caps("postgresql")
        self.assertEqual(normalize_sql_type("text", cap), "text")
        self.assertEqual(normalize_column_ddl('"x" text', cap), '"x" text')

    def test_require_sa_connection_raises_without_sa(self):
        from pyvelm.database.sa_ddl import require_sa_connection

        conn = MagicMock()
        with patch("pyvelm.database.sa_ddl.sqlalchemy_connection", return_value=None):
            with self.assertRaises(RuntimeError):
                require_sa_connection(conn)

    def test_sa_ddl_unsupported_dialect_and_model_lookup(self):
        from pyvelm.database.sa_ddl import _sqlalchemy_dialect, model_cls_for_table

        bad_cap = MagicMock()
        bad_cap.name = "unknown"
        with self.assertRaises(ValueError):
            _sqlalchemy_dialect(bad_cap)
        self.assertIsNone(model_cls_for_table(None, "any_table"))

    def test_sa_type_mssql_nvarchar_sized(self):
        from sqlalchemy.dialects.mssql import NVARCHAR

        from pyvelm.database.sa_ddl import sa_type_for_field
        from pyvelm.fields import Char

        cap = dialect_caps("mssql")
        sized = sa_type_for_field(Char(string="Name"), cap)
        self.assertIsInstance(sized, NVARCHAR)
        self.assertEqual(sized.length, 255)
        explicit = Char(string="Code")
        explicit.sql_type = "NVARCHAR(64)"
        self.assertEqual(sa_type_for_field(explicit, cap).length, 64)

    def test_execute_create_table_from_name_and_columns(self):
        from sqlalchemy import Column, Integer, String

        from pyvelm.database.sa_ddl import execute_create_table, primary_key_column
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        cap = dialect_caps("sqlite")
        conn = MagicMock()
        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="sqlite")
        cols = [
            primary_key_column(cap),
            Column("name", String(64), nullable=False),
        ]
        with patch("pyvelm.database.introspection.table_exists", return_value=False):
            execute_create_table(conn, "demo_named", cols, cap=cap)
        self.assertTrue(any("CREATE TABLE" in s.upper() for s in executed))

    def test_sort_models_skips_related_and_missing_comodel(self):
        from pyvelm.database.sa_ddl import sort_models_for_table_setup
        from pyvelm.fields import Char, Many2one

        related_parent = Many2one("missing.parent")
        related_parent.related = "x"
        related_parent.is_stored = True
        ghost = Many2one("ghost.model")
        ghost.is_stored = True

        class Parent:
            _name = "parent.model"
            _table = "parent_model"
            _fields = {"name": Char()}

        class Child:
            _name = "child.model"
            _table = "child_model"
            _fields = {
                "name": Char(),
                "parent_id": Many2one("parent.model"),
                "related_parent_id": related_parent,
                "ghost_id": ghost,
            }

        models = {"parent.model": Parent, "child.model": Child}
        reg = MagicMock()
        reg.__contains__ = lambda _s, n: n in models
        reg.__getitem__ = lambda _s, n: models[n]
        ordered = sort_models_for_table_setup([Child], reg)
        self.assertEqual(
            [m._name for m in ordered],
            ["parent.model", "child.model"],
        )

    def test_table_bound_column_already_bound(self):
        from sqlalchemy import Column, Integer, MetaData, Table

        from pyvelm.database.sa_ddl import table_bound_column

        metadata = MetaData()
        tbl = Table("t", metadata, Column("id", Integer, primary_key=True), quote=True)
        bound = table_bound_column("t", tbl.c.id)
        self.assertIs(bound, tbl.c.id)

    def test_execute_add_column_strips_if_not_exists_when_disabled(self):
        from sqlalchemy import Column, Text

        from pyvelm.database.sa_ddl import execute_add_column
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        cap = dialect_caps("postgresql")
        conn = MagicMock()
        executed: list[str] = []
        wire_sa_conn(conn, executed, dialect_name="postgresql")
        col = Column("note", Text(), nullable=True)
        execute_add_column(conn, "demo_tbl", col, cap=cap, if_not_exists=False)
        self.assertEqual(len(executed), 1)
        self.assertNotIn("IF NOT EXISTS", executed[0].upper())


class EnvRemainingGapsTests(unittest.TestCase):
    def test_load_testing_env_missing_file(self):
        fake_dotenv = MagicMock()
        fake_dotenv.find_dotenv.return_value = ""
        with patch.dict("sys.modules", {"dotenv": fake_dotenv}):
            from pyvelm.database.env import load_testing_env

            self.assertFalse(load_testing_env())

    def test_require_dsn_from_env(self):
        from pyvelm.database.env import require_dsn_from_env

        with patch.dict(os.environ, {"PYVELM_DSN": "sqlite:///tmp/x.db"}, clear=True):
            self.assertIn("sqlite", require_dsn_from_env())

    def test_is_transaction_pooler_parse_error(self):
        from pyvelm.database.env import is_transaction_pooler_dsn

        with patch("pyvelm.database.env.normalize_dsn", side_effect=ValueError("bad")):
            self.assertTrue(is_transaction_pooler_dsn("postgresql://x:6543/db"))

    def test_warn_if_poor_nuke_dsn_skips_when_not_serverless(self):
        import io

        with patch.dict(os.environ, {}, clear=True):
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                warn_if_poor_nuke_dsn("postgresql://localhost:6543/db")
            self.assertEqual(buf.getvalue(), "")

    def test_uses_serverless_schema_wipe_lambda(self):
        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "fn"}, clear=True):
            self.assertTrue(uses_serverless_schema_wipe())


class DialectRemainingGapsTests(unittest.TestCase):
    def test_mssql_helpers(self):
        self.assertIn("DATETIMEOFFSET", mssql.timestamp_sql_type())
        self.assertIn("SYSDATETIMEOFFSET", mssql.now_sql())
        self.assertIn("NVARCHAR(255)", mssql.string_sql_type(primary_key=True))
        self.assertFalse(mssql.supports_create_table_if_not_exists())
        self.assertEqual(mssql.bind_params((2,)), (2,))
        self.assertIn("IDENTITY", mssql.serial_primary_key())
        self.assertEqual(
            mssql.normalize_dsn("mssql://localhost/db"),
            "mssql+pyodbc://localhost/db",
        )
        mssql.after_reset_all_tables(MagicMock())

    def test_mssql_configure_engine_connect_sets_quoted_identifier(self):
        hooks: list = []

        def capture(_target, _identifier):
            def decorator(fn):
                hooks.append(fn)
                return fn

            return decorator

        with patch("sqlalchemy.event.listens_for", side_effect=capture):
            mssql.configure_engine(MagicMock())
        dbapi = MagicMock()
        cursor = MagicMock()
        dbapi.cursor.return_value = cursor
        hooks[0](dbapi, None)
        cursor.execute.assert_called_once_with("SET QUOTED_IDENTIFIER ON")

    def test_mssql_pagination_with_custom_order(self):
        sql = mssql.append_search_pagination(
            "SELECT 1",
            base_table_sql='"t"',
            limit=5,
            offset=0,
            order='"t"."name"',
        )
        self.assertIn('"t"."name"', sql)

    def test_mysql_bind_params(self):
        self.assertEqual(mysql.bind_params((3,)), (3,))

    def test_mysql_helpers_full(self):
        self.assertIn("AUTO_INCREMENT", mysql.serial_primary_key())
        self.assertEqual(mysql.timestamp_sql_type(), "TIMESTAMP(6)")
        self.assertIn("CURRENT", mysql.now_sql())
        self.assertEqual(mysql.string_sql_type(primary_key=True), "VARCHAR(255)")
        self.assertTrue(mysql.supports_create_table_if_not_exists())

    def test_mysql_configure_engine_connect_sets_ansi_quotes(self):
        hooks: list = []

        def capture(_target, _identifier):
            def decorator(fn):
                hooks.append(fn)
                return fn

            return decorator

        with patch("sqlalchemy.event.listens_for", side_effect=capture):
            mysql.configure_engine(MagicMock())
        dbapi = MagicMock()
        cursor = MagicMock()
        dbapi.cursor.return_value = cursor
        hooks[0](dbapi, None)
        cursor.execute.assert_called_once_with("SET SESSION sql_mode = 'ANSI_QUOTES'")

    def test_oracle_helpers(self):
        self.assertIn("TIMESTAMP", oracle.timestamp_sql_type())
        self.assertIn("TIMESTAMP", oracle.now_sql())
        self.assertIn("VARCHAR2", oracle.string_sql_type(primary_key=True))
        self.assertEqual(oracle.bind_params((1,)), (1,))
        oracle.before_reset_all_tables(MagicMock())
        oracle.after_reset_all_tables(MagicMock())

    def test_sqlite_pagination_limit_and_offset(self):
        sql = sqlite.append_search_pagination(
            "SELECT 1",
            base_table_sql='"t"',
            limit=10,
            offset=2,
            order=None,
        )
        self.assertIn("LIMIT 10", sql)
        self.assertIn("OFFSET 2", sql)

    def test_mssql_configure_engine_registers_connect_listener(self):
        with patch("sqlalchemy.event.listens_for") as listen:
            mssql.configure_engine(MagicMock())
        listen.assert_called_once()

    def test_mssql_fetch_lastrowid_fallback_max(self):
        conn = MagicMock()
        conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(None,))),
            MagicMock(fetchone=MagicMock(return_value=(42,))),
        ]
        self.assertEqual(mssql.fetch_lastrowid(conn, "demo"), 42)

    def test_mssql_pagination_without_order_uses_id(self):
        sql = mssql.append_search_pagination(
            "SELECT * FROM demo",
            base_table_sql='"demo"',
            limit=5,
            offset=0,
            order=None,
        )
        self.assertIn("ORDER BY", sql.upper())
        self.assertIn("FETCH NEXT", sql.upper())

    def test_mssql_is_missing_table_error(self):
        self.assertTrue(mssql.is_missing_table_error("42s02 object missing"))

    def test_postgresql_pagination_offset(self):
        sql = postgresql.append_search_pagination(
            "SELECT 1", base_table_sql='"t"', limit=None, offset=3, order=None
        )
        self.assertIn("OFFSET 3", sql)

    def test_postgresql_fetch_lastrowid_empty(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        self.assertEqual(postgresql.fetch_lastrowid(conn, "t"), 0)


class IntrospectionGapsTests(unittest.TestCase):
    def test_column_exists_false_when_table_missing(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("sqlite")
        with patch("pyvelm.database.introspection.table_exists", return_value=False):
            self.assertFalse(column_exists(conn, "missing", "x"))

    def test_table_exists_sqlalchemy_inspector(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        sa_conn = MagicMock()
        with patch(
            "pyvelm.database.introspection.sqlalchemy_connection",
            return_value=sa_conn,
        ):
            inspector = MagicMock()
            inspector.has_table.return_value = True
            with patch("sqlalchemy.inspect", return_value=inspector):
                self.assertTrue(table_exists(conn, "demo"))

    def test_clear_reflection_cache(self):
        from pyvelm.database.introspection import clear_reflection_cache

        conn = MagicMock()
        sa_conn = MagicMock()
        inspector = MagicMock()
        with patch(
            "pyvelm.database.introspection._inspector_sa_connection",
            return_value=sa_conn,
        ), patch("sqlalchemy.inspect", return_value=inspector):
            clear_reflection_cache(conn)
        inspector.clear_cache.assert_called_once()

    def test_inspector_table_name_nosuchtable(self):
        from pyvelm.database.introspection import _inspector_table_name

        inspector = MagicMock()
        from sqlalchemy.exc import NoSuchTableError

        inspector.get_table_names.side_effect = NoSuchTableError("missing")
        self.assertIsNone(_inspector_table_name(inspector, "demo"))

    def test_inspector_table_name_case_insensitive_miss(self):
        from pyvelm.database.introspection import _inspector_table_name

        inspector = MagicMock()
        inspector.get_table_names.return_value = ["other"]
        self.assertIsNone(_inspector_table_name(inspector, "demo"))

    def test_column_exists_inspector_unresolved_table(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        sa_conn = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["other"]
        with patch(
            "pyvelm.database.introspection.sqlalchemy_connection",
            return_value=sa_conn,
        ), patch(
            "pyvelm.database.introspection.table_exists",
            return_value=True,
        ), patch("sqlalchemy.inspect", return_value=inspector):
            self.assertFalse(column_exists(conn, "demo", "id"))

    def test_column_exists_information_schema_fallback(self):
        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        conn.execute.return_value.fetchall.return_value = [("name",)]
        with patch(
            "pyvelm.database.introspection.sqlalchemy_connection",
            return_value=None,
        ), patch(
            "pyvelm.database.introspection.table_exists",
            return_value=True,
        ):
            self.assertTrue(column_exists(conn, "demo", "name"))
            self.assertFalse(column_exists(conn, "demo", "missing"))

    def test_table_exists_mock_schema_flag(self):
        conn = MagicMock()
        conn._pyvelm_mock_schema = True
        self.assertFalse(table_exists(conn, "demo"))

    def test_table_exists_nosuchtable_error(self):
        from sqlalchemy.exc import NoSuchTableError

        conn = MagicMock()
        conn.capabilities = dialect_caps("postgresql")
        sa_conn = MagicMock()
        inspector = MagicMock()
        inspector.has_table.side_effect = NoSuchTableError("gone")
        with patch(
            "pyvelm.database.introspection._inspector_sa_connection",
            return_value=sa_conn,
        ), patch("sqlalchemy.inspect", return_value=inspector):
            self.assertFalse(table_exists(conn, "demo"))


class SqliteRuntimeRemainingTests(unittest.TestCase):
    def test_sqlite_file_path_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                (Path("local.db")).write_bytes(b"x")
                out = sqlite_file_path("sqlite:///local.db")
                self.assertTrue(str(out).endswith("local.db"))
            finally:
                os.chdir(previous)

    def test_resolve_creates_empty_dest_when_no_source(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            out = resolve_sqlite_dsn_for_runtime("sqlite:///:memory:")
        self.assertIn("/tmp/pyvelm-", out)

    def test_delete_sqlite_file_missing_path(self):
        delete_sqlite_file("postgresql://localhost/x")


class AdapterRemainingGapsTests(unittest.TestCase):
    def test_from_sa_without_dbapi(self):
        sa = MagicMock(spec=["connection"])
        sa.connection = MagicMock(dbapi_connection=None)
        cap = dialect_caps("postgresql")
        adapter = ConnectionAdapter.from_sa_connection(sa, cap)
        self.assertIsNone(adapter._dbapi)

    def test_commit_rollback_when_only_dbapi(self):
        dbapi = MagicMock()
        adapter = ConnectionAdapter(None, capabilities=dialect_caps("postgresql"), dbapi_conn=dbapi)
        adapter.commit()
        adapter.rollback()

    def test_close_rollback_also_fails(self):
        sa = MagicMock()
        sa.commit.side_effect = RuntimeError("commit")
        sa.rollback.side_effect = RuntimeError("rollback")
        adapter = ConnectionAdapter(sa, capabilities=dialect_caps("postgresql"))
        adapter.autocommit = True
        adapter.close()  # must not raise

    def test_non_sqlite_engine_kwargs(self):
        with patch("pyvelm.database.adapter.create_engine") as create_engine:
            from pyvelm.database.adapter import Database

            create_engine.return_value = MagicMock()
            with patch("pyvelm.database.adapter.configure_engine"):
                Database.from_dsn("postgresql://localhost/test", pool_size=2)
            kwargs = create_engine.call_args[1]
            self.assertEqual(kwargs["pool_size"], 2)


if __name__ == "__main__":
    unittest.main()

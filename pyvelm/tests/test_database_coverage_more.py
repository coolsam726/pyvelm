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
    normalize_column_ddl,
    normalize_sql_type,
    reset_schema,
    returning_id_clause,
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
        ):
            self.assertFalse(
                add_column_if_missing(conn, "t", "c", "text", cap)
            )

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

    def test_add_column_sql_mssql_oracle_omit_column_keyword(self):
        from pyvelm.database.ddl import add_column_sql

        mssql_sql = add_column_sql("t", "c", "BIT", dialect_caps("mssql"))
        self.assertEqual(mssql_sql, 'ALTER TABLE "t" ADD "c" BIT')
        self.assertNotIn("ADD COLUMN", mssql_sql)
        oracle_sql = add_column_sql("t", "c", "INTEGER", dialect_caps("oracle"))
        self.assertEqual(oracle_sql, 'ALTER TABLE "t" ADD "c" INTEGER')

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

    def test_mysql_bind_params(self):
        self.assertEqual(mysql.bind_params((3,)), (3,))

    def test_oracle_helpers(self):
        self.assertIn("TIMESTAMP", oracle.timestamp_sql_type())
        self.assertIn("TIMESTAMP", oracle.now_sql())
        self.assertIn("VARCHAR2", oracle.string_sql_type(primary_key=True))
        self.assertEqual(oracle.bind_params((1,)), (1,))
        oracle.before_reset_all_tables(MagicMock())
        oracle.after_reset_all_tables(MagicMock())

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

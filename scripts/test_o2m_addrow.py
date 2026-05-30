"""End-to-end test: clicking 'Add a line' / 'Add row' in the partner
edit form inserts ONE horizontal <tr> with N <td>s, not a vertical
stack of fields. Run with PYVELM_DSN set."""

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
import uvicorn
from psycopg_pool import ConnectionPool

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.web import create_app


HERE = Path(__file__).resolve().parent.parent
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


def _bootstrap(dsn: str) -> tuple[int, Registry]:
    reg = Registry()
    with psycopg.connect(dsn, autocommit=True) as conn:
        env = Environment(conn, registry=reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, env, install_all=True)
        admin = env["res.users"].search([("login", "=", "admin")], limit=1)
        if not admin:
            raise SystemExit("admin user not found")
        company_id = admin.company_id.id if admin.company_id else None
        env2 = Environment(conn, registry=reg, uid=admin.id)
        if company_id is not None:
            env2 = env2.with_company(company_id)
        Partner = env2["res.partner"]
        rec = Partner.search([], limit=1)
        if not rec:
            rec = Partner.create({"name": "PVTestParent"})
        print(f"admin uid={admin.id} company_id={company_id} partner_id={rec.id}")
        return rec.id, reg


@contextmanager
def _server(dsn: str, reg: Registry, port: int = 8765):
    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=True)
    print(f"registry has {len(reg._models)} models; res.users present: {'res.users' in reg}")
    app = create_app(reg, pool, module_roots=MODULE_ROOTS)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=5)
        pool.close()


def main():
    from dotenv import load_dotenv
    load_dotenv(".env")
    dsn = os.environ["PYVELM_DSN"]
    pid, reg = _bootstrap(dsn)
    print(f"using partner id={pid}")

    from playwright.sync_api import sync_playwright

    with _server(dsn, reg) as base_url:
        url = f"{base_url}/web/views/partners/partner.form/record/{pid}/edit"
        print(f"GET {url}")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(f"{base_url}/login", wait_until="networkidle")
            page.fill("input[name='login']", "admin")
            page.fill("input[name='password']", "admin")
            with page.expect_navigation():
                page.click("button[type='submit'], input[type='submit']")
            print(f"after-login url: {page.url}")
            if "/login" in page.url:
                err_text = page.locator("body").inner_text()[:300]
                print("login appears to have failed; body:", err_text)
                raise SystemExit(1)
            resp = page.goto(url, wait_until="networkidle")
            print(f"status={resp.status} url={page.url}")
            if resp.status != 200:
                body = page.content()[:500]
                print("body preview:", body)
                raise SystemExit(1)

            root = page.locator("[data-pv-o2m-root][data-pv-o2m-name='child_ids']")
            if root.count() == 0:
                # Maybe partner has no child_ids field visible — dump.
                Path("/tmp/o2m_page_dump.html").write_text(page.content())
                print("o2m root not found; dumped page to /tmp/o2m_page_dump.html")
                raise SystemExit(1)
            assert root.count() == 1, f"o2m root not found, got {root.count()}"

            header_tds = root.locator("thead th").count()
            print(f"thead columns: {header_tds}")
            assert header_tds == 6, f"expected 6 thead columns, got {header_tds}"

            initial_rows = root.locator("tbody tr[data-pv-o2m-row]").count()
            print(f"initial editable rows: {initial_rows}")

            page.click("[data-pv-o2m-add-row]")
            page.wait_for_timeout(200)

            rows = root.locator("tbody tr[data-pv-o2m-row]")
            assert rows.count() == initial_rows + 1, (
                f"expected {initial_rows + 1} rows after Add a line, got {rows.count()}"
            )

            new_row = rows.nth(initial_rows)
            tds = new_row.locator(":scope > td").count()
            print(f"new row td count: {tds}")
            assert tds == 6, f"expected 6 <td> in new row, got {tds}"

            stacked = page.evaluate("""(root) => {
                const trs = root.querySelectorAll('tbody > tr');
                const orphans = [];
                root.querySelectorAll('tbody').forEach(tb => {
                    tb.childNodes.forEach(n => {
                        if (n.nodeType === 1 && n.tagName !== 'TR') {
                            orphans.push(n.tagName);
                        }
                    });
                });
                return { trs: trs.length, orphans };
            }""", root.element_handle())
            print(f"tbody structure: {stacked}")
            assert not stacked["orphans"], (
                f"non-TR elements inside tbody: {stacked['orphans']}"
            )

            page.click("[data-pv-o2m-add]")
            page.wait_for_timeout(200)
            rows2 = root.locator("tbody tr[data-pv-o2m-row]")
            assert rows2.count() == initial_rows + 2, (
                f"Add row button should add a second row, got {rows2.count()}"
            )
            new_row_2 = rows2.nth(initial_rows + 1)
            tds_2 = new_row_2.locator(":scope > td").count()
            assert tds_2 == 6, f"expected 6 <td> in 2nd new row, got {tds_2}"

            name_input = new_row_2.locator("input[name$='[name]']")
            assert name_input.count() == 1, "name input missing in new row"
            name_attr = name_input.get_attribute("name")
            assert "__IDX__" not in name_attr, (
                f"__IDX__ token not rewritten: {name_attr}"
            )
            print(f"name input attribute: {name_attr}")

            m2o = new_row_2.locator(".pv-m2o")
            m2o_count = m2o.count()
            print(f"pv-m2o count in row2: {m2o_count}")
            assert m2o_count >= 1, "M2O combobox missing in new row"
            mounted_states = page.evaluate(
                """row => Array.from(row.querySelectorAll('.pv-m2o'))
                       .map(el => !!el._x_dataStack)""",
                new_row_2.element_handle(),
            )
            print(f"Alpine mounted per M2O: {mounted_states}")
            assert all(mounted_states), "Alpine did not initialize all M2O cells"

            browser.close()

    print("\nOK: Add line and Add row both insert proper <tr> with 6 <td>s.")
    print("OK: __IDX__ is rewritten, Alpine initialized on cloned rows.")


if __name__ == "__main__":
    main()

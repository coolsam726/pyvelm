"""Idempotent seed for the demo example app.

Every block below uses a `search`-then-`create` pattern so reinstalling
the demo module (or running serve.py twice) doesn't double-up records.
The natural key per model is named in the helper docstring.

Layout:
  1. Regions + countries (geo data)
  2. Tags (M2m demo: VIP, Wholesale, ...)
  3. Extra users + groups so multi-user filter/group-by has variety
  4. Partners (20 across countries, ages, tags, VIP markers)
  5. CRM leads (15 across stages and salespeople)
  6. A server action + automation rule + cron job that point at the
     workflow models so the Settings views aren't empty.
  7. A mail.message thread on one partner so the inbox isn't empty.
"""


def install(env):
    _seed_geo(env)
    tags = _seed_tags(env)
    _seed_extra_users(env)
    partners = _seed_partners(env, tags)
    _seed_leads(env, partners)
    _seed_workflow_examples(env)
    _seed_mail_thread(env, partners)


# ---------------------------------------------------------------- geo

def _seed_geo(env):
    """Seed res.region + res.country. Natural key is `name`."""
    Region = env["res.region"]
    Country = env["res.country"]

    region_data = ["Europe", "Asia", "Americas", "Oceania"]
    regions = {}
    for name in region_data:
        existing = Region.search([("name", "=", name)], limit=1)
        regions[name] = existing if existing else Region.create({"name": name})

    country_data = [
        ("France", "FR", "Europe"),
        ("Germany", "DE", "Europe"),
        ("United Kingdom", "GB", "Europe"),
        ("Spain", "ES", "Europe"),
        ("Japan", "JP", "Asia"),
        ("China", "CN", "Asia"),
        ("Singapore", "SG", "Asia"),
        ("United States", "US", "Americas"),
        ("Brazil", "BR", "Americas"),
        ("Mexico", "MX", "Americas"),
        ("Australia", "AU", "Oceania"),
    ]
    for name, code, region in country_data:
        existing = Country.search([("code", "=", code)], limit=1)
        if existing:
            continue
        Country.create({
            "name": name,
            "code": code,
            "region_id": regions[region],
        })


# ---------------------------------------------------------------- tags

def _seed_tags(env):
    """Seed res.tag. Returns a dict {name: recordset}."""
    Tag = env["res.tag"]
    out = {}
    for name in ("VIP", "Wholesale", "Strategic", "Distributor", "Reseller"):
        existing = Tag.search([("name", "=", name)], limit=1)
        out[name] = existing if existing else Tag.create({"name": name})
    return out


# ------------------------------------------------------------- users / groups

def _seed_extra_users(env):
    """Add a 'Sales' group + a couple of demo users so multi-user
    filters (Group By Salesperson, etc.) have something to do.
    """
    Group = env["res.groups"]
    User = env["res.users"]

    sales = Group.search([("name", "=", "Sales")], limit=1)
    if not sales:
        sales = Group.create({"name": "Sales"})

    # Grant Sales group read+write on partners & leads so the demo
    # users can actually click around productively.
    Access = env["ir.model.access"]
    for model in ("res.partner", "crm.lead", "res.tag", "res.country", "res.region"):
        existing = Access.search([
            ("name", "=", f"Sales/{model}"),
        ], limit=1)
        if existing:
            continue
        Access.create({
            "name": f"Sales/{model}",
            "model": model,
            "group_id": sales,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": False,
        })

    demo_users = [
        ("alice.sales", "Alice Sales", "alice.sales"),
        ("bob.sales", "Bob Sales", "bob.sales"),
        ("carol.sales", "Carol Sales", "carol.sales"),
    ]
    for login, name, password in demo_users:
        existing = User.search([("login", "=", login)], limit=1)
        if existing:
            continue
        User.create({
            "login": login,
            "name": name,
            "password": password,
            "group_ids": [sales],
        })


# ---------------------------------------------------------------- partners

def _seed_partners(env, tags):
    """Seed res.partner records. Natural key is `code` (unique-by-convention).

    Returns a dict {code: partner recordset} so downstream seeders can
    reference them. Sets country_id, age, tag_ids, and the partners_pro
    `vip_note` for a few VIPs.
    """
    Partner = env["res.partner"]
    Country = env["res.country"]
    by_code = {c.code: c for c in Country.search([])}

    partner_specs = [
        # (code, name, country_code, age, tag_names, vip_note_or_None)
        ("CONT-001", "Alpha Industries", "US", 42, ["VIP", "Strategic"], "Enterprise account — renew Q4."),
        ("CONT-002", "Beta Distribution", "DE", 35, ["Wholesale", "Distributor"], None),
        ("CONT-003", "Gamma Foods", "FR", 51, ["Strategic"], "Long-term contract — escalations to legal."),
        ("CONT-004", "Delta Logistics", "JP", 28, ["Wholesale"], None),
        ("CONT-005", "Epsilon Tech", "US", 39, ["VIP"], "Whale account."),
        ("CONT-006", "Zeta Holdings", "GB", 47, ["Strategic", "VIP"], None),
        ("CONT-007", "Eta Manufacturing", "CN", 33, ["Wholesale"], None),
        ("CONT-008", "Theta Retail", "ES", 26, ["Reseller"], None),
        ("CONT-009", "Iota Services", "MX", 44, [], None),
        ("CONT-010", "Kappa Energy", "BR", 56, ["Strategic"], None),
        ("CONT-011", "Lambda Software", "SG", 31, ["Reseller", "VIP"], "Renewal pending."),
        ("CONT-012", "Mu Pharma", "GB", 49, ["Strategic"], None),
        ("CONT-013", "Nu Realty", "AU", 38, [], None),
        ("CONT-014", "Xi Trading", "JP", 41, ["Wholesale", "Distributor"], None),
        ("CONT-015", "Omicron Auto", "DE", 53, ["VIP"], "Direct line to ops."),
        ("CONT-016", "Pi Cosmetics", "FR", 29, ["Reseller"], None),
        ("CONT-017", "Rho Insurance", "US", 45, [], None),
        ("CONT-018", "Sigma Bank", "GB", 60, ["Strategic", "VIP"], "Sensitive — disclosures via legal."),
        ("CONT-019", "Tau Tools", "MX", 36, [], None),
        ("CONT-020", "Upsilon Materials", "CN", 48, ["Wholesale"], None),
    ]
    out = {}
    for code, name, ccode, age, tag_names, vip_note in partner_specs:
        existing = Partner.search([("code", "=", code)], limit=1)
        if existing:
            out[code] = existing
            continue
        vals = {
            "name": name,
            "code": code,
            "age": age,
            "country_id": by_code.get(ccode),
            "tag_ids": [tags[t] for t in tag_names if t in tags],
        }
        # partners_pro adds vip_note via _inherit; safe to set when present.
        if vip_note is not None and "vip_note" in Partner._fields:
            vals["vip_note"] = vip_note
        out[code] = Partner.create(vals)
    return out


# ---------------------------------------------------------------- leads

def _seed_leads(env, partners):
    """Seed crm.lead. Natural key is `name`."""
    Lead = env["crm.lead"]
    # Pick a small rotation of partners as contacts.
    p_codes = list(partners.keys())

    lead_specs = [
        # (name, partner_code, stage, priority, revenue, probability, salesperson)
        ("Alpha annual renewal", "CONT-001", "qualified", 2, 220.0, 80, "alice.sales"),
        ("Beta — Q3 expansion", "CONT-002", "proposal", 1, 90.0, 55, "bob.sales"),
        ("Gamma master agreement", "CONT-003", "won", 2, 350.0, 100, "alice.sales"),
        ("Delta freight upgrade", "CONT-004", "new", 0, 18.0, 15, "carol.sales"),
        ("Epsilon platform pilot", "CONT-005", "qualified", 2, 140.0, 70, "alice.sales"),
        ("Zeta consultancy hours", "CONT-006", "lost", 1, 60.0, 0, "bob.sales"),
        ("Eta SKU integration", "CONT-007", "new", 1, 45.0, 30, "carol.sales"),
        ("Theta seasonal promo", "CONT-008", "proposal", 0, 25.0, 50, "carol.sales"),
        ("Iota retainer", "CONT-009", "qualified", 1, 36.0, 60, "alice.sales"),
        ("Kappa drilling support", "CONT-010", "new", 2, 180.0, 25, "bob.sales"),
        ("Lambda dev hours bundle", "CONT-011", "won", 1, 72.0, 100, "alice.sales"),
        ("Mu regulatory consulting", "CONT-012", "proposal", 2, 110.0, 65, "bob.sales"),
        ("Nu lease renewal", "CONT-013", "new", 0, 28.0, 20, "carol.sales"),
        ("Xi multi-region trial", "CONT-014", "qualified", 1, 88.0, 55, "alice.sales"),
        ("Omicron parts contract", "CONT-015", "lost", 2, 210.0, 0, "bob.sales"),
    ]
    for name, p_code, stage, prio, rev, prob, sp in lead_specs:
        existing = Lead.search([("name", "=", name)], limit=1)
        if existing:
            continue
        partner = partners.get(p_code)
        Lead.create({
            "name": name,
            "partner_id": partner if partner else None,
            "stage": stage,
            "priority": prio,
            "expected_revenue": rev,
            "probability": prob,
            "salesperson": sp,
        })
    # Suppress "p_codes unused" warning when the partners dict is empty.
    _ = p_codes


# ---------------------------------------------------------------- workflow

def _seed_workflow_examples(env):
    """Drop a couple of records into the workflow models so their
    list / form views aren't empty. The actions point at res.partner
    so they're meaningful but stay opt-in (active=False on the cron)."""
    if "ir.actions.server" not in env.registry:
        return
    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    Auto = env["base.automation"]

    action_name = "Deactivate inactive partners"
    action = Action.search([("name", "=", action_name)], limit=1)
    if not action:
        action = Action.create({
            "name": action_name,
            "model": "res.partner",
            "action_type": "code",
            "code": (
                "for r in records:\n"
                "    if r.age and r.age > 70:\n"
                "        r.active = False\n"
            ),
        })

    cron_name = "Demo — nightly partner sweep"
    if not Cron.search([("name", "=", cron_name)], limit=1):
        Cron.create({
            "name": cron_name,
            "action_id": action,
            "interval_number": 1,
            "interval_type": "days",
            "active": False,
        })

    auto_name = "Demo — log on new lead"
    if "crm.lead" in env.registry and not Auto.search([("name", "=", auto_name)], limit=1):
        # A no-op automation that just exists for the list view to
        # have an entry. Points at a benign code action so triggering
        # it has no side effects.
        noop = Action.search([("name", "=", "Demo noop")], limit=1)
        if not noop:
            noop = Action.create({
                "name": "Demo noop",
                "model": "crm.lead",
                "action_type": "code",
                "code": "pass\n",
            })
        Auto.create({
            "name": auto_name,
            "model": "crm.lead",
            "trigger": "on_create",
            "action_id": noop,
            "active": False,
        })


# ---------------------------------------------------------------- mail

def _seed_mail_thread(env, partners):
    """Post a couple of mail.message records against the first VIP
    partner so the message list has something to display."""
    if "mail.message" not in env.registry:
        return
    if not partners:
        return
    Message = env["mail.message"]
    target = partners.get("CONT-001")
    if target is None:
        return
    existing = Message.search([
        ("model", "=", "res.partner"),
        ("res_id", "=", target.id),
    ], limit=1)
    if existing:
        return
    Message.create({
        "model": "res.partner",
        "res_id": target.id,
        "author_id": env.uid,
        "body": "Account onboarded. Welcome aboard, Alpha Industries.",
        "message_type": "comment",
    })
    Message.create({
        "model": "res.partner",
        "res_id": target.id,
        "author_id": env.uid,
        "body": "Quarterly review scheduled with the customer-success team.",
        "message_type": "comment",
    })

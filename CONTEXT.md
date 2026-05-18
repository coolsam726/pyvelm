# Project context

Building an Odoo-style ERP framework in Python. Currently at the end of
Stage 1 (declarative model layer + recordsets + basic CRUD/search).

## Architectural decisions already made
- Recordset-is-the-model: BaseModel instances represent 0/1/many records.
  Singleton access uses ensure_one(); the descriptor protocol routes
  field reads through env.cache.
- Field values live in env.cache keyed by (model, id, field), NOT on
  instances. This is what makes computed-field invalidation tractable later.
- Environment is first-class and threads through every recordset. ACL,
  multi-company, context all flow through it.
- Sync ORM. Async only at the FastAPI/HTTP boundary later.
- PostgreSQL from the start (via psycopg 3, sync). Raw SQL by string concat
  for now; SQLAlchemy Core (not ORM) is on the table for Stage 3.

## Roadmap
1. ✅ Declarative model layer + recordsets + CRUD/search (done)
2. ⏭ Relational fields (Many2one, One2many, Many2many) + computed fields
     with @depends + dependency graph
3. Module loading + schema migrations + registry lifecycle
4. Views (form/list/kanban) as data + generic UI endpoints
5. ACL: groups, model permissions, record rules (domain-based row security)
6. Workflows: server actions, automated actions, scheduled jobs, mail threads
7. Module inheritance: _inherit for models, XPath-style view patches

## Deliberately deferred (will bite us, fix when they do)
- Cache has no LRU or invalidation cascades
- Domain language is AND-only, no relational traversal, no polish notation
- No transaction boundaries beyond psycopg autocommit
- SQL by string concat (works because inputs are controlled)
- _active_registry is a module global (fine until Stage 3)

## Next concrete task
Stage 2, starting with Many2one fields. This forces decisions about:
- How the field stores an int column but exposes a recordset
- Traversal: how `partner.country_id.name` resolves through the cache
- Inverse One2many computed lazily from the Many2one side
- Cache invalidation when the related record changes
Then Many2many (auto relation table), then computed fields with @depends.
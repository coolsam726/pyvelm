"""Add res.currency + res.currency.rate; seed the minimal currency list.

Fresh installs get both tables via ``_setup_table`` from the model
declarations. Upgraded installs need the schema + FKs added here.
The seed step is factored into ``hooks._seed_currencies`` so a
fresh install (which doesn't run this migration) and an upgrade
(which does) share one code path.

Idempotent: every DDL uses ``IF NOT EXISTS``; the seed helper
looks each currency up by ``code`` before creating.
"""


def migrate(env):
    env.conn.execute(
        'CREATE TABLE IF NOT EXISTS "res_currency" ('
        '"id" SERIAL PRIMARY KEY, '
        '"code" text NOT NULL, '
        '"name" text, '
        '"symbol" text DEFAULT \'$\', '
        '"rounding" double precision DEFAULT 0.01, '
        '"active" boolean DEFAULT TRUE)'
    )
    env.conn.execute(
        'CREATE TABLE IF NOT EXISTS "res_currency_rate" ('
        '"id" SERIAL PRIMARY KEY, '
        '"currency_id" integer NOT NULL, '
        '"name" timestamp, '
        '"rate" double precision DEFAULT 1.0)'
    )
    # FK on the rate's currency_id — CASCADE so deleting a currency
    # also removes its rate history.
    env.conn.execute(
        'ALTER TABLE "res_currency_rate" '
        'DROP CONSTRAINT IF EXISTS "res_currency_rate_currency_id_fkey"'
    )
    env.conn.execute(
        'ALTER TABLE "res_currency_rate" '
        'ADD CONSTRAINT "res_currency_rate_currency_id_fkey" '
        'FOREIGN KEY ("currency_id") REFERENCES "res_currency"("id") '
        'ON DELETE CASCADE'
    )

    # Seed the minimal currency list. Shares the helper with the
    # install hook so fresh installs and upgrades end up with the
    # same seed.
    from base import hooks
    hooks._seed_currencies(env)

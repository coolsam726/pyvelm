"""Add vellum.demo.comment for Vellum relation tests."""


def upgrade(env):
    env["vellum.demo.comment"]._setup_table(env.conn)
    env["vellum.demo.note"]._setup_table(env.conn)

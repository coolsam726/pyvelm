"""Add ``vellum.demo.comment`` for Vellum relation tests."""


def migrate(env):
    Comment = env["vellum.demo.comment"]
    Comment._setup_table(env.conn)
    Note = env["vellum.demo.note"]
    Note._setup_table(env.conn)

"""Install hook for mail_compose — grants ACL on ``mail.compose.message``."""


def install(env):
    from pyvelm.security import grant_model_access

    grant_model_access(
        env, "mail.compose.message", admin="crud", user="crud", public=None
    )

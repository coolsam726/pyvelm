"""Install hook for super_chain_demo."""


def install(env):
    from pyvelm.security import grant_model_access

    grant_model_access(env, "super_chain.order", admin="crud", user="read")

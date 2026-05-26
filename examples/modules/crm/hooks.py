"""Install hook for the crm module.

Seeds access grants so Admin can fully manage CRM leads.
"""


def install(env):
    from pyvelm.security import grant_model_access

    grant_model_access(env, "crm.lead", admin="crud", user="read")

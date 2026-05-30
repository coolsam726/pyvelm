from pathlib import Path as _Path

# Public version string. Keep in sync with ``[project].version`` in
# ``pyproject.toml`` — the release workflow refuses to publish if
# they diverge, but the check is only enforced in CI; bump both
# together when cutting a release.
__version__ = "0.26.0"

from .depends import depends
from .env import Environment
from .fields import (
    Boolean,
    Char,
    Code,
    Date,
    Datetime,
    Field,
    Float,
    Html,
    Integer,
    Many2many,
    Many2one,
    Monetary,
    One2many,
    Text,
    Time,
)
from . import builders
from . import loader
from . import types
from .model import BaseModel
from .registry import Registry
# NOTE: ServerAction, AutomatedAction, CronJob, Message, MailThread are
# NOT imported here because they define BaseModel subclasses which must
# only be evaluated inside a `with registry.activate():` block (i.e. during
# module loading).  Import them directly from their modules when needed:
#   from pyvelm.actions import ServerAction
#   from pyvelm.mail import MailThread, Message
# The engine helpers (AutomationEngine, CronJob.run_due) are always safe
# to import because they only touch the registry at call time.

# Discovery root for the modules bundled inside the wheel. Today the
# framework ships two: ``base`` (the primitives every app needs:
# ir.ui.view / res.users / res.groups / ir.model.access / ir.rule /
# ir.actions.server / base.automation / ir.cron / mail.message /
# res.country / res.region / res.company / ir.ui.menu) and ``admin``
# (the list/form views + sidebar menus that put a usable management
# UI in front of those models). Apps that boot the framework should
# include this in their ``loader.load_and_install`` call:
#
#     from pyvelm import BUILTIN_MODULE_ROOTS
#     loader.load_and_install(
#         BUILTIN_MODULE_ROOTS + [my_app_root], env,
#     )
#
# ``pyvelm-cron`` prepends these automatically so the CLI sees the
# framework modules even if the operator only set PYVELM_MODULE_ROOTS
# to their app's addons. The ``console`` module ships Artisan-style
# generators (``make:module``, ``make:command``). Import Vellum via
# ``from pyvelm.vellum import Vellum`` (bundled ``vellum`` module marker).
BUILTIN_MODULE_ROOTS: list[_Path] = [_Path(__file__).parent / "modules"]


__all__ = [
    "BUILTIN_MODULE_ROOTS",
    "__version__",
    "BaseModel",
    "Boolean",
    "Char",
    "Code",
    "Date",
    "Datetime",
    "Environment",
    "Field",
    "Float",
    "Html",
    "Integer",
    "Many2many",
    "Many2one",
    "Monetary",
    "One2many",
    "Registry",
    "Text",
    "builders",
    "depends",
    "loader",
    "types",
]

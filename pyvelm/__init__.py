from .depends import depends
from .env import Environment
from .fields import (
    Boolean,
    Char,
    Field,
    Float,
    Integer,
    Many2many,
    Many2one,
    One2many,
    Text,
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

__all__ = [
    "BaseModel",
    "Boolean",
    "Char",
    "Environment",
    "Field",
    "Float",
    "Integer",
    "Many2many",
    "Many2one",
    "One2many",
    "Registry",
    "Text",
    "builders",
    "depends",
    "loader",
    "types",
]

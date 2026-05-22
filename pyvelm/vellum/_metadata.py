"""Collect Vellum registries at class creation (scopes, accessors, events)."""
from __future__ import annotations

from .attribute import collect_accessors_mutators, merge_maps
from .events import collect_events, merge_events
from .scope import PYVELM_SCOPE


def install_vellum_metadata(cls) -> None:
    """Populate ``_vellum_*`` registries on a model class."""
    mro_bases = cls.__mro__[1:]
    scopes = merge_maps(mro_bases, "_vellum_scopes")
    accessors = merge_maps(mro_bases, "_vellum_accessors")
    mutators = merge_maps(mro_bases, "_vellum_mutators")
    events = merge_events(mro_bases)

    for name, attr in cls.__dict__.items():
        if getattr(attr, PYVELM_SCOPE, False):
            scopes[name] = attr
        acc_muts = collect_accessors_mutators({name: attr})
        accessors.update(acc_muts[0])
        mutators.update(acc_muts[1])
        ev = collect_events({name: attr})
        for event, names in ev.items():
            events.setdefault(event, []).extend(names)

    cls._vellum_scopes = scopes
    cls._vellum_accessors = accessors
    cls._vellum_mutators = mutators
    cls._vellum_events = events

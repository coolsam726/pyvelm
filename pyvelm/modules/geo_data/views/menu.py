"""Geography subsection under Settings."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("geo_data")

MENUS: list[Menu] = [
    # Settings group is owned by the admin module — point at it via
    # the (module, name) tuple so the loader resolves to admin.settings.
    m.group(
        "geography",
        "Geography",
        parent=("admin", "settings"),
        sequence=70,
    ),
    m.item(
        "geography.continents",
        "Continents",
        parent="geography",
        view="geo_data.continent.list",
        perm="read",
        model="res.continent",
        sequence=10,
    ),
    m.item(
        "geography.countries",
        "Countries",
        parent="geography",
        view="geo_data.country.list",
        perm="read",
        model="res.country",
        sequence=20,
    ),
    m.item(
        "geography.states",
        "States / provinces",
        parent="geography",
        view="geo_data.state.list",
        perm="read",
        model="res.country.state",
        sequence=30,
    ),
    m.item(
        "geography.cities",
        "Cities",
        parent="geography",
        view="geo_data.city.list",
        perm="read",
        model="res.city",
        sequence=40,
    ),
]

NAME: str = "geo_data"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = (
    "Continents, countries, states/provinces, and cities — seeded from "
    "pycountry + geonamescache."
)
CATEGORY: str = "Localization"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/geo.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "geo_data.hooks:install"

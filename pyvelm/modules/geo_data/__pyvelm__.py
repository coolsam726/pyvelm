NAME: str = "geo_data"
VERSION: tuple[int, ...] = (0, 2, 0)
SUMMARY: str = (
    "Continents, countries, states/provinces, and cities — seed on demand "
    "from pycountry + geonamescache (pip install pyvelm[geo])."
)
CATEGORY: str = "Localization"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/geo.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "geo_data.hooks:install"
WEB_ROUTES: str = "geo_data.web:register_routes"

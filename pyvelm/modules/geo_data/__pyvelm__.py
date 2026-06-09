"""geo_data module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("geo_data")
    .version(0, 2, 0)
    .summary(
        "Continents, countries, states/provinces, and cities — seed on demand "
        "from pycountry + geonamescache (pip install pyvelm[geo])."
    )
    .category("Localization")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/geo.py",
        "views/menu.py",
    )
    .install_hook("geo_data.hooks:install")
    .web_routes("geo_data.web:register_routes")
)

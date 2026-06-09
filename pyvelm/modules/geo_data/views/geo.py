"""List + form views for the geo_data models."""

from pyvelm.builders import Field, FormView, ListView, Page, ViewsData

views_data = (
    ViewsData.make()
    .views(
        # ---- res.continent -------------------------------------------------
        ListView.make("geo_data.continent.list")
        .model("res.continent")
        .title("Continents")
        .columns(["code", "name"])
        .form_view("geo_data.continent.form"),
        FormView.make("geo_data.continent.form")
        .model("res.continent")
        .title("Continent")
        .section("identity", "Identity", ["code", "name"])
        .section(
            "countries",
            "Countries",
            [Field.make("country_ids").widget("dialog")],
            cols=1,
        ),
        # ---- res.country ---------------------------------------------------
        ListView.make("geo_data.country.list")
        .model("res.country")
        .title("Countries")
        .columns(
            [
                "flag_emoji",
                "name",
                "code",
                "iso3",
                "continent_id",
                "capital",
                "currency_code",
                "phone_code",
                "population",
            ]
        )
        .form_view("geo_data.country.form")
        .page_actions(
            [
                {
                    "label": "Seed geography data",
                    "url": "/web/geo-data/seed",
                    "method": "POST",
                    "confirm": (
                        "Load continents, countries, states, and major cities from "
                        "geonamescache? Requires pyvelm[geo]. This may take a minute."
                    ),
                    "perm": "write",
                },
            ]
        ),
        ListView.make("geo_data.state.compact")
        .model("res.country.state")
        .columns(["name", "short_code", "code", "type"])
        .form_view("geo_data.state.form"),
        ListView.make("geo_data.city.compact")
        .model("res.city")
        .columns(
            [
                "name",
                "state_id",
                "population",
                Field.make("is_capital").toggle(),
            ]
        )
        .form_view("geo_data.city.form"),
        FormView.make("geo_data.country.form")
        .model("res.country")
        .title("Country")
        .cols(2)
        .section(
            "identity",
            "Identity",
            [
                "flag_emoji",
                "name",
                "code",
                "iso3",
                "continent_id",
            ],
        )
        .section(
            "facts",
            "Facts",
            [
                "capital",
                "currency_code",
                "phone_code",
                "population",
            ],
        )
        .notebook(
            "subdivisions",
            "Subdivisions",
            [
                Page.make("states", "States / provinces").fields(
                    [
                        Field.make("state_ids")
                        .widget("dialog")
                        .set(
                            edit_toggle=True,
                            list_view="geo_data.state.compact",
                            form_view="geo_data.state.form",
                            columns=[
                                "name",
                                "short_code",
                                "code",
                                "type",
                            ],
                        ),
                    ]
                ),
                Page.make("cities", "Cities").fields(
                    [
                        Field.make("city_ids")
                        .widget("dialog")
                        .set(
                            edit_toggle=True,
                            list_view="geo_data.city.compact",
                            form_view="geo_data.city.form",
                            columns=[
                                "name",
                                "state_id",
                                "population",
                                Field.make("is_capital").toggle(),
                            ],
                        ),
                    ]
                ),
            ],
        ),
        # ---- res.country.state --------------------------------------------
        ListView.make("geo_data.state.list")
        .model("res.country.state")
        .title("States / provinces")
        .columns(
            [
                "country_id",
                "name",
                "short_code",
                "code",
                "type",
            ]
        )
        .form_view("geo_data.state.form"),
        FormView.make("geo_data.state.form")
        .model("res.country.state")
        .title("State / province")
        .cols(2)
        .section(
            "identity",
            "Identity",
            [
                "country_id",
                "name",
                "short_code",
                "code",
                "type",
                "parent_id",
            ],
        ),
        # ---- res.city ------------------------------------------------------
        ListView.make("geo_data.city.list")
        .model("res.city")
        .title("Cities")
        .columns(
            [
                "name",
                "country_id",
                "state_id",
                "population",
                Field.make("is_capital").toggle(),
                "timezone",
            ]
        )
        .form_view("geo_data.city.form"),
        FormView.make("geo_data.city.form")
        .model("res.city")
        .title("City")
        .cols(2)
        .section(
            "identity",
            "Identity",
            [
                "name",
                "country_id",
                "state_id",
                Field.make("is_capital").toggle(),
                "geoname_id",
            ],
        )
        .section(
            "location",
            "Location",
            [
                "latitude",
                "longitude",
                "timezone",
                "population",
            ],
        ),
    )
)

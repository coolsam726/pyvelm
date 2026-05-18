"""Stage 1 smoke test against PostgreSQL.

Reads PYVELM_DSN from a `.env` file in the project root (see .env.example).
"""
import os
import sys

import psycopg
from dotenv import load_dotenv

from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Environment,
    Integer,
    Many2many,
    Many2one,
    One2many,
    depends,
    registry,
)

load_dotenv()


class Region(BaseModel):
    _name = "res.region"

    name = Char(required=True)


class Country(BaseModel):
    _name = "res.country"

    name = Char(required=True)
    code = Char()
    region_id = Many2one("res.region", ondelete="SET NULL")
    partner_ids = One2many("res.partner", "country_id")


class Tag(BaseModel):
    _name = "res.tag"

    name = Char(required=True)
    partner_ids = Many2many("res.partner")


class Partner(BaseModel):
    _name = "res.partner"

    name = Char(required=True)
    age = Integer()
    active = Boolean(default=True)
    country_id = Many2one("res.country", ondelete="SET NULL")
    parent_id = Many2one("res.partner", ondelete="SET NULL")
    child_ids = One2many("res.partner", "parent_id")
    tag_ids = Many2many("res.tag")

    # Non-stored compute with one-hop Many2one traversal.
    display_name = Char(compute="_compute_display_name")
    # Stored compute — has a real SQL column, recomputed when `age` changes.
    age_bucket = Char(compute="_compute_age_bucket", store=True)

    @depends("name", "country_id.code", "country_id.region_id.name")
    def _compute_display_name(self):
        for r in self:
            code = r.country_id.code if r.country_id else None
            region = r.country_id.region_id.name if (
                r.country_id and r.country_id.region_id
            ) else None
            parts = [r.name]
            if code:
                parts.append(f"[{code}]")
            if region:
                parts.append(f"({region})")
            r.display_name = " ".join(parts)

    @depends("age")
    def _compute_age_bucket(self):
        for r in self:
            a = r.age or 0
            r.age_bucket = "senior" if a >= 40 else ("mid" if a >= 30 else "young")


def main():
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env and fill it in)")

    with psycopg.connect(dsn, autocommit=True) as conn:
        registry.reset_db(conn)
        env = Environment(conn)
        Partner = env["res.partner"]
        Country = env["res.country"]

        Region = env["res.region"]
        europe = Region.create({"name": "Europe"})
        asia_region = Region.create({"name": "Asia"})

        france = Country.create({"name": "France", "code": "FR", "region_id": europe})
        japan = Country.create({"name": "Japan", "code": "JP", "region_id": asia_region})

        alice = Partner.create({"name": "Alice", "age": 30, "active": True, "country_id": france})
        bob = Partner.create({"name": "Bob", "age": 25, "active": True, "country_id": japan.id})
        carol = Partner.create({"name": "Carol", "age": 40, "active": False, "parent_id": alice})
        print("Created:", alice, bob, carol)

        assert alice.country_id == france, f"got {alice.country_id!r}"
        print("alice.country_id.name =", alice.country_id.name)
        print("bob.country_id =", bob.country_id, "code =", bob.country_id.code)
        assert not alice.parent_id, "alice should have no parent"
        assert carol.parent_id == alice
        print("carol.parent_id.name =", carol.parent_id.name)

        bob.country_id = france
        assert bob.country_id == france

        # One2many: inverse of Many2one. Re-queried each access (no cache yet).
        # alice now in France, bob also assigned to France above.
        print("france.partner_ids =", france.partner_ids, "names:",
              [p.name for p in france.partner_ids])
        assert set(france.partner_ids.ids) == {alice.id, bob.id}
        # Self-referential One2many.
        print("alice.child_ids =", alice.child_ids, "names:",
              [p.name for p in alice.child_ids])
        assert alice.child_ids.ids == [carol.id]
        assert list(bob.child_ids) == []  # empty One2many = empty recordset

        # Writing directly to a One2many is rejected.
        raised = False
        try:
            france.write({"partner_ids": [1, 2]})
        except ValueError as e:
            raised = True
            print("One2many write rejected:", e)
        assert raised

        bob.country_id = None
        assert not bob.country_id
        # After clearing, France should only have Alice.
        assert france.partner_ids.ids == [alice.id]

        # ----- Many2many -----
        Tag = env["res.tag"]
        vip = Tag.create({"name": "VIP"})
        eu = Tag.create({"name": "EU"})
        asia = Tag.create({"name": "Asia"})

        # create() accepts an iterable of recordsets and/or ids for M2M.
        dave = Partner.create({
            "name": "Dave",
            "age": 50,
            "tag_ids": [vip, eu.id],
        })
        print("dave.tag_ids =", dave.tag_ids, "names:", [t.name for t in dave.tag_ids])
        assert set(dave.tag_ids.ids) == {vip.id, eu.id}
        # Read from the inverse side — same junction table.
        print("vip.partner_ids =", vip.partner_ids, "names:",
              [p.name for p in vip.partner_ids])
        assert dave in vip.partner_ids

        # write() does a full replacement.
        dave.write({"tag_ids": [vip, asia]})
        assert set(dave.tag_ids.ids) == {vip.id, asia.id}
        assert dave not in eu.partner_ids
        assert dave in asia.partner_ids

        # __set__ accepts the same shapes.
        dave.tag_ids = [eu]
        assert dave.tag_ids.ids == [eu.id]

        # Clearing.
        dave.tag_ids = None
        assert list(dave.tag_ids) == []

        # Unlinking a tag cascades through the junction (ON DELETE CASCADE).
        dave.write({"tag_ids": [vip, eu]})
        vip.unlink()
        assert dave.tag_ids.ids == [eu.id]
        print("After vip.unlink(), dave.tag_ids =", dave.tag_ids)

        # ----- Computed fields -----
        # alice.country_id = France (Europe). display_name walks two M2o
        # hops: name + country.code + country.region.name.
        # bob.country_id is None at this point (we cleared it).
        assert alice.display_name == "Alice [FR] (Europe)"
        assert bob.display_name == "Bob"
        print("alice.display_name =", alice.display_name)
        print("dave.age_bucket =", dave.age_bucket, "(age 50)")
        assert dave.age_bucket == "senior"
        assert alice.age_bucket == "mid"  # age 30

        # Same-record invalidation: changing `name` invalidates display_name.
        alice.write({"name": "Alicia"})
        assert alice.display_name == "Alicia [FR] (Europe)"
        print("after rename:", alice.display_name)

        # One-hop M2o invalidation: France's code changes -> only partners
        # whose country_id points at France get their display_name dropped.
        france.write({"code": "FRA"})
        assert alice.display_name == "Alicia [FRA] (Europe)"
        assert bob.display_name == "Bob"  # bob has no country, unaffected
        print("after France code change:", alice.display_name)

        # Two-hop M2o invalidation: Europe's name changes -> reverse-walk
        # finds countries with region_id=Europe, then partners whose
        # country_id points at those countries.
        europe.write({"name": "EU"})
        assert alice.display_name == "Alicia [FRA] (EU)"
        print("after Europe rename:", alice.display_name)

        # Stored compute writes back to the SQL column on dep change.
        dave.write({"age": 28})
        assert dave.age_bucket == "young"

        # External writes to a compute field are rejected.
        raised = False
        try:
            alice.display_name = "Hacked"
        except ValueError as e:
            raised = True
            print("compute write rejected:", e)
        assert raised

        # Domain on a Many2one — value can be a recordset.
        in_france = Partner.search([("country_id", "=", france)])
        print("Partners in France:", [p.name for p in in_france])

        # Domain traversal through a Many2one chain: emits LEFT JOINs.
        # Find partners whose country is in Europe.
        in_europe = Partner.search([("country_id.region_id.name", "=", "EU")])
        print("Partners in Europe:", [p.name for p in in_europe])
        assert alice in in_europe
        assert bob not in in_europe  # bob has no country

        # Multiple path leaves in one domain reuse the same JOIN chain.
        french_eu = Partner.search([
            ("country_id.code", "=", "FRA"),
            ("country_id.region_id.name", "=", "EU"),
        ])
        assert french_eu.ids == [alice.id]

        # Collection-path domains: O2m via EXISTS subquery.
        # Find partners with at least one child named "Carol".
        parents_of_carol = Partner.search([("child_ids.name", "=", "Carol")])
        print("Parents of Carol:", [p.name for p in parents_of_carol])
        assert parents_of_carol.ids == [alice.id]

        # Collection-path domains: M2m via EXISTS subquery.
        # Give Alice a couple of tags so the M2m query has signal.
        alice.write({"tag_ids": [eu, asia]})
        eu_tagged = Partner.search([("tag_ids.name", "=", "EU")])
        print("Partners tagged EU:", [p.name for p in eu_tagged])
        assert alice in eu_tagged
        assert dave in eu_tagged  # dave still tagged EU from earlier

        # Two M2m leaves on the same attr: each gets its own EXISTS, so
        # "tagged EU" AND "tagged Asia" matches partners with BOTH tags.
        both = Partner.search([
            ("tag_ids.name", "=", "EU"),
            ("tag_ids.name", "=", "Asia"),
        ])
        print("Partners tagged BOTH EU and Asia:", [p.name for p in both])
        assert alice in both
        assert dave not in both  # dave is only tagged EU

        # Domain typo now raises locally instead of crashing in PG.
        raised = False
        try:
            Partner.search([("contry_id", "=", "FR")])
        except ValueError as e:
            raised = True
            print("domain typo caught:", e)
        assert raised, "expected ValueError on unknown domain field"

        print("alice.name =", alice.name)
        print("alice.age =", alice.age)

        adults = Partner.search([("age", ">=", 30)], order='"age" ASC')
        print("Adults:", adults, "names:", [r.name for r in adults])

        actives = Partner.search([("active", "=", True)])
        print("Active:", actives.ids)

        bob.write({"age": 26})
        print("bob.age after write =", bob.age)

        a_names = Partner.search([("name", "ilike", "%a%")])
        print("Names ILIKE %a%:", [r.name for r in a_names])

        some = Partner.search([("id", "in", [alice.id, carol.id])])
        print("By id IN:", some.ids)

        carol.unlink()
        print("After unlink, count =", Partner.search_count([]))

        multi = Partner.search([("active", "=", True)])
        assert len(multi) > 1, "need a multi-record recordset to test this"
        raised = False
        try:
            _ = multi.name
        except ValueError as e:
            raised = True
            print(f"singleton guard fired as expected on {multi!r}: {e}")
        assert raised, "expected ValueError from ensure_one() on multi-record access"


if __name__ == "__main__":
    main()

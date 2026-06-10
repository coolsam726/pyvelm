"""``res.currency.rate`` — dated exchange rates."""
from __future__ import annotations

import logging
import urllib.request
from datetime import datetime
from xml.etree import ElementTree as ET

from pyvelm import Char, Datetime, Float, Many2one, depends, models

log = logging.getLogger("pyvelm.currency")

# ECB publishes daily reference rates expressed as units of foreign
# currency per 1 EUR. No API key, no signup. Skipped on weekends and
# TARGET holidays — the cron tolerates an unchanged-since-yesterday
# document via the idempotent same-day check below.
ECB_DAILY_URL = (
    "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
)
_ECB_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


class ResCurrencyRate(models.Model):
    """A dated exchange rate for a single currency.

    Multiple rows per currency cover history. ``date`` is the
    effective-from datetime; the rate stays in force until a later
    row supersedes it. Conversion picks the row whose ``date`` is the
    largest at or before the query date.

    ``name`` is a computed display label of the form ``"<code> @
    <date>"`` so list views and Many2one fallbacks render something
    meaningful without operators maintaining a separate label."""

    _name = "res.currency.rate"

    currency_id = Many2one("res.currency", ondelete="CASCADE", required=True)
    date = Datetime(string="Conversion Date", required=True)
    rate = Float(default=1.0)

    name = Char(compute="_compute_name", string="Label")

    @depends("currency_id.code", "date")
    def _compute_name(self):
        for r in self:
            code = r.currency_id.code if r.currency_id else ""
            stamp = (
                r.date.strftime("%Y-%m-%d %H:%M")
                if r.date is not None else "—"
            )
            r.name = f"{code} @ {stamp}" if code else stamp

    # ---- ECB rate fetcher ----------------------------------------------

    @classmethod
    def fetch_from_ecb(cls, env) -> dict:
        """Refresh exchange rates from the ECB daily feed.

        Wired up by the bundled ``ECB rate fetcher`` cron (created
        inactive — operators opt in by flipping ``active=True``). Runs
        unconditionally when called directly so admins can trigger an
        ad-hoc refresh from a server action.

        ECB rates are expressed as units of foreign currency per 1 EUR.
        pyvelm stores rates as units-per-implicit-reference, where the
        reference is whichever currency carries ``rate == 1.0`` in its
        most recent row (USD by default seed). We rebase ECB's numbers
        against that anchor before writing.

        Idempotent: if a row already exists for the same currency at
        ECB's publication date, that currency is skipped.

        Returns a small stats dict ``{"written", "skipped",
        "as_of"}`` for logging / server-action introspection.
        """
        with urllib.request.urlopen(ECB_DAILY_URL, timeout=30) as resp:
            data = resp.read()
        dated_cube = ET.fromstring(data).find(f".//{_ECB_NS}Cube[@time]")
        if dated_cube is None:
            raise RuntimeError("ECB feed missing dated <Cube time=...> element")
        rate_date = datetime.strptime(dated_cube.get("time"), "%Y-%m-%d")
        ecb: dict[str, float] = {}
        for c in dated_cube.findall(f"{_ECB_NS}Cube"):
            code = c.get("currency")
            try:
                rate = float(c.get("rate"))
            except (TypeError, ValueError):
                continue
            if code and rate > 0:
                ecb[code] = rate

        # ACL bypass: the cron context has no operator identity and
        # currency tables are write-protected to Admin in the install
        # hook. Mirrors the mail dispatcher.
        prev = getattr(env, "_acl_bypass", False)
        env._acl_bypass = True
        try:
            return cls._apply_ecb_rates(env, ecb, rate_date)
        finally:
            env._acl_bypass = prev

    @classmethod
    def _apply_ecb_rates(cls, env, ecb: dict, rate_date: datetime) -> dict:
        Currency = env["res.currency"]
        Rate = env["res.currency.rate"]
        currencies = Currency.search([("active", "=", True)])

        # Anchor = the currency whose latest rate row is 1.0. That's the
        # implicit reference used throughout pyvelm's conversion math.
        anchor = None
        for c in currencies:
            latest = Rate.search(
                [("currency_id", "=", c.id)],
                order='"date" DESC, "id" DESC',
                limit=1,
            )
            if latest and abs(latest.rate - 1.0) < 1e-9:
                anchor = c
                break
        if anchor is None:
            raise RuntimeError(
                "No anchor currency found (none has a most-recent rate of 1.0); "
                "cannot rebase ECB rates."
            )
        if anchor.code == "EUR":
            anchor_in_eur = 1.0
        else:
            anchor_in_eur = ecb.get(anchor.code)
            if not anchor_in_eur:
                raise RuntimeError(
                    f"Anchor currency {anchor.code!r} is not in the ECB feed; "
                    "cannot rebase."
                )

        written = 0
        skipped = 0
        with env.transaction():
            for c in currencies:
                if c.id == anchor.id:
                    continue
                if c.code == "EUR":
                    new_rate = 1.0 / anchor_in_eur
                elif c.code in ecb:
                    new_rate = ecb[c.code] / anchor_in_eur
                else:
                    skipped += 1
                    continue
                # Idempotency: same currency + same date stamp is a no-op.
                existing = Rate.search(
                    [("currency_id", "=", c.id), ("date", "=", rate_date)],
                    limit=1,
                )
                if existing:
                    skipped += 1
                    continue
                Rate.create(
                    {
                        "currency_id": c.id,
                        "date": rate_date,
                        "rate": new_rate,
                    }
                )
                written += 1
        as_of = rate_date.strftime("%Y-%m-%d")
        log.info(
            "ECB rate fetch: %s — %d written, %d skipped",
            as_of, written, skipped,
        )
        return {"written": written, "skipped": skipped, "as_of": as_of}

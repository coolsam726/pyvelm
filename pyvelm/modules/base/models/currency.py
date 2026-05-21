"""Currency primitives shipped with the `base` module.

Two models cooperate:

* ``res.currency`` — a currency definition: ISO 4217 code, display
  name, symbol, rounding step, active flag.
* ``res.currency.rate`` — a dated exchange rate. Many rows per
  currency; the conversion helper picks the row whose ``date`` is the
  largest value at or before the query date.

Rates are stored on an implicit common reference — the base unit
the seed picks (USD by default, with rate=1.0). Cross-currency
conversion never names the reference explicitly because the math
cancels:

    amount_in_ref = amount_in_X / rate_X_at(date)
    result        = amount_in_ref * rate_Y_at(date)

That keeps the data model simple — no "anchor currency" column on
``res.currency`` to maintain.
"""
from __future__ import annotations

from datetime import datetime

from pyvelm import (
    BaseModel, Boolean, Char, Datetime, Float, Many2one, One2many, depends,
)


class Currency(BaseModel):
    """A currency definition + conversion helper."""

    _name = "res.currency"

    # ISO 4217 code (USD, EUR, JPY, …). Acts as the natural key —
    # the seed and tests look currencies up by code rather than id.
    code = Char(required=True)
    name = Char()
    symbol = Char(default="$")
    # Smallest representable unit. 0.01 for cents, 1 for JPY, etc.
    # The Monetary widget rounds amounts to this step.
    rounding = Float(default=0.01)
    active = Boolean(default=True)

    rate_ids = One2many("res.currency.rate", "currency_id")

    def convert(
        self,
        amount: float,
        to_currency: "Currency",
        date: datetime | None = None,
    ) -> float:
        """Convert ``amount`` from this currency to ``to_currency``.

        ``date`` selects the rate effective at that moment (the row
        with the latest ``date`` at or before ``date``). When omitted,
        defaults to "now" — the rate currently in effect.

        Raises ``ValueError`` if either side has no rate covering
        the requested date.
        """
        self.ensure_one()
        to_currency.ensure_one()
        if self.id == to_currency.id:
            return amount
        from_rate = self._rate_at(date)
        to_rate = to_currency._rate_at(date)
        return amount / from_rate * to_rate

    def _rate_at(self, date: datetime | None = None) -> float:
        """Return the rate active at ``date``, falling back to the
        most recent rate not in the future when ``date`` is None.
        """
        self.ensure_one()
        if date is None:
            date = datetime.utcnow()
        Rate = self.env["res.currency.rate"]
        rates = Rate.search(
            [
                ("currency_id", "=", self.id),
                ("date", "<=", date),
            ],
            order='"date" DESC, "id" DESC',
            limit=1,
        )
        if not rates:
            raise ValueError(
                f"Currency {self.code or self.id}: no rate effective at "
                f"or before {date.isoformat()}"
            )
        return rates.rate


class CurrencyRate(BaseModel):
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

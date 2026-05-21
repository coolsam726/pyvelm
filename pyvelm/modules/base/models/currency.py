"""Currency primitives shipped with the `base` module.

Two models cooperate:

* ``res.currency`` — a currency definition: ISO 4217 code, display
  name, symbol, rounding step, active flag.
* ``res.currency.rate`` — a dated exchange rate. Many rows per
  currency; the conversion helper picks the one whose ``name``
  (the effective-from date) is the latest at or before the query
  date.

Rates are stored on an implicit common reference — the base unit
the seed picks (USD by default, with rate=1.0). Cross-currency
conversion never names the reference explicitly because the math
cancels:

    amount_in_ref = amount_in_X / rate_X_at(date)
    result        = amount_in_ref * rate_Y_at(date)

That keeps the data model simple — no "anchor currency" column on
``res.currency`` to maintain. A future improvement is to honor
``res.company.currency_id`` as the per-company anchor (queued for
slice B).
"""
from __future__ import annotations

from datetime import datetime

from pyvelm import BaseModel, Boolean, Char, Float, Many2one, One2many
from pyvelm.cron import _DatetimeField


class Currency(BaseModel):
    """A currency definition + conversion helper."""

    _name = "res.currency"

    # ISO 4217 code (USD, EUR, JPY, …). Acts as the natural key —
    # the seed and tests look currencies up by code rather than id.
    code = Char(required=True)
    name = Char()
    symbol = Char(default="$")
    # Smallest representable unit. 0.01 for cents, 1 for JPY, etc.
    # The Monetary widget (slice C) will round amounts to this step.
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
        with the latest ``name`` at or before ``date``). When
        omitted, defaults to "now" — the rate currently in effect.

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
                ("name", "<=", date),
            ],
            order='"name" DESC, "id" DESC',
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

    Multiple rows per currency cover history. ``name`` is the
    effective-from datetime; the rate stays in force until a later
    row supersedes it. Conversion picks the row whose ``name`` is
    the largest at or before the query date.
    """

    _name = "res.currency.rate"

    currency_id = Many2one("res.currency", ondelete="CASCADE", required=True)
    name = _DatetimeField()        # effective-from datetime
    rate = Float(default=1.0)

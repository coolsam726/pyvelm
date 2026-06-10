"""``res.currency`` — ISO currency definition and conversion helper."""
from __future__ import annotations

from datetime import datetime

from pyvelm import Boolean, Char, Float, One2many, depends, models
from pyvelm.timestamps import utc_now


class ResCurrency(models.Model):
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
        to_currency: "ResCurrency",
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
            date = utc_now()
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

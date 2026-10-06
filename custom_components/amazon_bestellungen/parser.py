"""HTML parsing for the Amazon order history page (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
import re

from bs4 import BeautifulSoup, Tag

ORDER_ID_RE = re.compile(r"\b(\d{3}-\d{7}-\d{7}|D\d{2}-\d{7}-\d{7})\b")

MONTHS = {
    # German
    "januar": 1, "jan": 1, "jänner": 1, "februar": 2, "feb": 2, "märz": 3,
    "mär": 3, "maerz": 3, "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
    "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "sept": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
    # English
    "january": 1, "february": 2, "march": 3, "mar": 3, "may": 5, "june": 6,
    "july": 7, "october": 10, "oct": 10, "december": 12, "dec": 12,
    # French / Italian / Spanish / Dutch (common ones)
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9,
    "ottobre": 10, "dicembre": 12, "enero": 1, "febrero": 2, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12, "januari": 1, "februari": 2, "maart": 3,
    "mei": 5, "augustus": 8,
}

WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonntag": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}

DELIVERED_WORDS = ("zugestellt", "delivered", "livré", "consegnato", "entregado", "bezorgd")
CANCELLED_WORDS = ("storniert", "cancelled", "canceled", "annulé", "annullato", "cancelado", "geannuleerd")
TODAY_WORDS = ("heute", "today", "aujourd'hui", "oggi", "hoy", "vandaag")
YESTERDAY_WORDS = ("gestern", "yesterday", "ieri", "ayer", "gisteren")

_MONTH_ALT = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DAY_MONTH_RE = re.compile(rf"(\d{{1,2}})\.?\s+({_MONTH_ALT})\.?(?:\s+(\d{{4}}))?", re.IGNORECASE)
MONTH_DAY_RE = re.compile(rf"({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
NUMERIC_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")


@dataclass
class Shipment:
    """A shipment (delivery box) inside an order."""

    status: str
    delivered: bool
    delivered_on: date | None = None


@dataclass
class Order:
    """An Amazon order."""

    order_id: str
    order_date: date | None
    total: str | None
    url: str
    items: list[str] = field(default_factory=list)
    shipments: list[Shipment] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Combined human readable status."""
        return " | ".join(dict.fromkeys(s.status for s in self.shipments if s.status)) or "Unbekannt"

    @property
    def delivered(self) -> bool:
        """True when every shipment of the order has been delivered."""
        return bool(self.shipments) and all(s.delivered for s in self.shipments)

    @property
    def cancelled(self) -> bool:
        """True when the order was cancelled."""
        return any(w in self.status.lower() for w in CANCELLED_WORDS)

    @property
    def delivered_on(self) -> date | None:
        """Date of the last delivery, if known for every shipment."""
        dates = [s.delivered_on for s in self.shipments]
        if not self.delivered or any(d is None for d in dates):
            return None
        return max(dates)  # type: ignore[type-var]

    def as_dict(self) -> dict:
        """Serialize for state attributes."""
        data = asdict(self)
        data.pop("shipments")
        data["order_date"] = self.order_date.isoformat() if self.order_date else None
        data["status"] = self.status
        data["delivered"] = self.delivered
        return data


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _infer_year(day: int, month: int, today: date) -> date | None:
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    # Status texts without a year refer to the past (or the near future for
    # announced deliveries); a date far in the future belongs to last year.
    if candidate > today + timedelta(days=60):
        candidate = candidate.replace(year=today.year - 1)
    return candidate


def parse_date(text: str, today: date | None = None) -> date | None:
    """Parse a localized date from a free text like 'Zugestellt am 3. Oktober'."""
    today = today or date.today()
    lower = text.lower()

    if any(re.search(rf"\b{re.escape(w)}\b", lower) for w in YESTERDAY_WORDS):
        return today - timedelta(days=1)
    if any(re.search(rf"\b{re.escape(w)}\b", lower) for w in TODAY_WORDS):
        return today

    if m := NUMERIC_RE.search(lower):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass

    for regex, day_idx, month_idx in ((DAY_MONTH_RE, 1, 2), (MONTH_DAY_RE, 2, 1)):
        if m := regex.search(lower):
            day = int(m.group(day_idx))
            month = MONTHS[m.group(month_idx).lower()]
            if m.group(3):
                try:
                    return date(int(m.group(3)), month, day)
                except ValueError:
                    return None
            return _infer_year(day, month, today)

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lower):
            # A delivered status naming only a weekday refers to the past week.
            delta = (today.weekday() - weekday) % 7
            return today - timedelta(days=delta)

    return None


def _parse_shipment(text: str, today: date) -> Shipment:
    text = _clean(text)
    lower = text.lower()
    delivered = any(w in lower for w in DELIVERED_WORDS) and "nicht" not in lower and "not " not in lower
    return Shipment(
        status=text,
        delivered=delivered,
        delivered_on=parse_date(text, today) if delivered else None,
    )


def _header_value(card: Tag, labels: tuple[str, ...]) -> str | None:
    """Find the value next to a header label like 'Bestellung aufgegeben'."""
    for label_el in card.find_all(string=True):
        label = _clean(str(label_el)).lower()
        if label and any(label.startswith(lbl) for lbl in labels):
            # The value sits in a sibling element; walk up until one is found.
            container = label_el.parent
            for _ in range(3):
                if container is None or container is card:
                    break
                texts = [_clean(t) for t in container.stripped_strings]
                lowered = [t.lower() for t in texts]
                if label in lowered:
                    values = texts[lowered.index(label) + 1 :]
                    if values:
                        return values[0]
                container = container.parent
    return None


def _find_cards(soup: BeautifulSoup) -> list[Tag]:
    for selector in ("div.order-card", "div.js-order-card", "div.order"):
        cards = soup.select(selector)
        if cards:
            return cards
    return []


def parse_order_history(html: str, base_url: str, today: date | None = None) -> list[Order]:
    """Parse orders out of an order history page."""
    today = today or date.today()
    soup = BeautifulSoup(html, "html.parser")
    orders: list[Order] = []
    seen: set[str] = set()

    for card in _find_cards(soup):
        id_el = card.select_one(".yohtmlc-order-id span[dir=ltr], .yohtmlc-order-id .value, bdi[dir=ltr]")
        match = ORDER_ID_RE.search(id_el.get_text() if id_el else card.get_text(" "))
        if not match or match.group(1) in seen:
            continue
        order_id = match.group(1)
        seen.add(order_id)

        date_text = _header_value(card, ("bestellung aufgegeben", "order placed", "commande effectuée", "ordine effettuato", "pedido realizado", "bestelling geplaatst"))
        total = _header_value(card, ("summe", "gesamt", "total", "totale", "totaal"))

        status_els = card.select(
            ".delivery-box__primary-text, .yohtmlc-shipment-status-primaryText, "
            ".js-shipment-info-container .a-row:first-child .a-size-medium"
        )
        shipments = [_parse_shipment(el.get_text(" "), today) for el in status_els]
        shipments = [s for s in shipments if s.status]

        items: list[str] = []
        for el in card.select(".yohtmlc-product-title, .yohtmlc-item a.a-link-normal, a.a-link-normal[href*='/dp/'], a.a-link-normal[href*='/gp/product/']"):
            title = _clean(el.get_text(" "))
            if title and title not in items and len(title) > 3:
                items.append(title)

        orders.append(
            Order(
                order_id=order_id,
                order_date=parse_date(date_text, today) if date_text else None,
                total=total,
                url=f"{base_url}/gp/your-account/order-details?orderID={order_id}",
                items=items,
                shipments=shipments,
            )
        )
    return orders


def has_next_page(html: str) -> bool:
    """Return True if the order history has another page."""
    soup = BeautifulSoup(html, "html.parser")
    last = soup.select_one("ul.a-pagination li.a-last")
    return last is not None and "a-disabled" not in (last.get("class") or [])

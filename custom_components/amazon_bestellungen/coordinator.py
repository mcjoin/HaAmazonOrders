"""Data update coordinator for Amazon Bestellungen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AmazonApprovalRequired,
    AmazonAuthError,
    AmazonCaptchaError,
    AmazonClient,
    AmazonError,
    AmazonMfaRequired,
)
from .const import (
    CONF_MAX_PAGES,
    CONF_RETENTION_DAYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAX_PAGES,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

type AmazonConfigEntry = ConfigEntry[AmazonOrdersCoordinator]


@dataclass
class OrdersData:
    """Result of one update."""

    orders: list[dict[str, Any]]

    @property
    def in_transit(self) -> list[dict[str, Any]]:
        """Orders that are not delivered yet."""
        return [o for o in self.orders if not o["delivered"]]


class AmazonOrdersCoordinator(DataUpdateCoordinator[OrdersData]):
    """Fetches orders and drops those delivered longer than the retention period."""

    config_entry: AmazonConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AmazonConfigEntry, client: AmazonClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # order_id -> ISO date when the order was first seen as delivered
        self._delivered_seen: dict[str, str] = {}

    async def async_load(self) -> None:
        """Restore cookies and delivery bookkeeping."""
        stored = await self._store.async_load() or {}
        self._delivered_seen = stored.get("delivered_seen", {})
        # Cookies from a (re-)login in the config flow win over older stored ones.
        data = self.config_entry.data
        if data.get("cookies_ts", 0) > stored.get("cookies_ts", 0):
            self.client.import_cookies(data.get("cookies", {}))
        else:
            self.client.import_cookies(stored.get("cookies", {}))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "cookies": self.client.export_cookies(),
                "cookies_ts": time.time(),
                "delivered_seen": self._delivered_seen,
            }
        )

    async def _async_update_data(self) -> OrdersData:
        options = self.config_entry.options
        retention = options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        max_pages = options.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)

        try:
            orders = await self.client.async_get_orders(max_pages)
        except (AmazonAuthError, AmazonMfaRequired, AmazonApprovalRequired) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AmazonCaptchaError as err:
            raise UpdateFailed(
                "Amazon verlangt ein Captcha. Bitte später erneut versuchen oder "
                "die Integration neu authentifizieren."
            ) from err
        except AmazonError as err:
            raise UpdateFailed(str(err)) from err

        today = dt_util.now().date()
        result: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for order in orders:
            seen_ids.add(order.order_id)
            data = order.as_dict()
            delivered_on: date | None = None
            if order.delivered:
                first_seen = self._delivered_seen.setdefault(order.order_id, today.isoformat())
                delivered_on = order.delivered_on or date.fromisoformat(first_seen)
                if (today - delivered_on).days > retention:
                    continue
            data["delivered_on"] = delivered_on.isoformat() if delivered_on else None
            data["remove_after"] = (
                (delivered_on + timedelta(days=retention)).isoformat() if delivered_on else None
            )
            result.append(data)

        # Forget bookkeeping for orders that are no longer in the history.
        self._delivered_seen = {k: v for k, v in self._delivered_seen.items() if k in seen_ids}
        await self._async_save()

        result.sort(key=lambda o: o["order_date"] or "", reverse=True)
        return OrdersData(orders=result)

"""Sensors for Amazon Bestellungen."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DOMAIN, DOMAIN
from .coordinator import AmazonConfigEntry, AmazonOrdersCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [OrdersSensor(coordinator, "orders"), OrdersSensor(coordinator, "in_transit")]
    )


class OrdersSensor(CoordinatorEntity[AmazonOrdersCoordinator], SensorEntity):
    """Number of listed orders, with the order list as attribute."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "Bestellungen"

    def __init__(self, coordinator: AmazonOrdersCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = "mdi:package-variant-closed" if key == "orders" else "mdi:truck-delivery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Amazon ({entry.data[CONF_EMAIL]})",
            manufacturer="Amazon",
            model=entry.data[CONF_DOMAIN],
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.base_url + "/your-orders/orders",
        )

    def _orders(self) -> list[dict[str, Any]]:
        data = self.coordinator.data
        return data.orders if self._key == "orders" else data.in_transit

    @property
    def native_value(self) -> int:
        return len(self._orders())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"orders": self._orders()}

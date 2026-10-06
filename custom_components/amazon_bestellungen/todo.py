"""Read-only to-do list showing every order as an item."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AmazonConfigEntry, AmazonOrdersCoordinator
from .sensor import device_info

MAX_SUMMARY = 70


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do list."""
    async_add_entities([OrdersTodoList(entry.runtime_data)])


def _summary(order: dict[str, Any]) -> str:
    items = order["items"]
    if not items:
        return f"Bestellung {order['order_id']}"
    title = items[0]
    if len(title) > MAX_SUMMARY:
        title = title[: MAX_SUMMARY - 1].rstrip() + "…"
    if len(items) > 1:
        title += f" (+{len(items) - 1} weitere)"
    return title


def _description(order: dict[str, Any]) -> str:
    lines = [order["status"]]
    if order["delivered_on"]:
        lines.append(f"Wird am {date.fromisoformat(order['remove_after']):%d.%m.%Y} ausgeblendet")
    meta = [f"Bestellnr. {order['order_id']}"]
    if order["order_date"]:
        meta.append(f"bestellt am {date.fromisoformat(order['order_date']):%d.%m.%Y}")
    if order["total"]:
        meta.append(order["total"])
    lines.append(" · ".join(meta))
    if len(order["items"]) > 1:
        lines.extend(f"• {item}" for item in order["items"])
    lines.append(order["url"])
    return "\n".join(lines)


class OrdersTodoList(CoordinatorEntity[AmazonOrdersCoordinator], TodoListEntity):
    """All listed orders; delivered ones are checked off."""

    _attr_has_entity_name = True
    _attr_translation_key = "orders"
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator: AmazonOrdersCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_todo"
        self._attr_device_info = device_info(coordinator)

    @property
    def todo_items(self) -> list[TodoItem]:
        items = []
        for order in self.coordinator.data.orders:
            due = order["delivered_on"] or order["expected_on"]
            items.append(
                TodoItem(
                    uid=order["order_id"],
                    summary=_summary(order),
                    status=TodoItemStatus.COMPLETED if order["delivered"] else TodoItemStatus.NEEDS_ACTION,
                    due=date.fromisoformat(due) if due else None,
                    description=_description(order),
                )
            )
        return items

"""The Amazon Bestellungen integration."""

from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import AmazonClient
from .const import CONF_DOMAIN, CONF_OTP_SECRET
from .coordinator import AmazonConfigEntry, AmazonOrdersCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TODO]


def create_client(hass: HomeAssistant, data: dict) -> AmazonClient:
    """Create a client with its own cookie jar."""
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    return AmazonClient(
        session,
        data[CONF_DOMAIN],
        data[CONF_EMAIL],
        data[CONF_PASSWORD],
        data.get(CONF_OTP_SECRET),
    )


async def async_setup_entry(hass: HomeAssistant, entry: AmazonConfigEntry) -> bool:
    """Set up Amazon Bestellungen from a config entry."""
    client = create_client(hass, dict(entry.data))
    entry.async_on_unload(client.async_close)
    coordinator = AmazonOrdersCoordinator(hass, entry, client)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: AmazonConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AmazonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

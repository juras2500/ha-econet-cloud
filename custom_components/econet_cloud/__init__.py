"""PLUM ecoNET Cloud monitoring and supported user controls."""

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import CloudClient
from .const import CONF_INSTALLATION_ID, CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import CloudCoordinator

PLATFORMS = ("sensor", "binary_sensor", "select", "number", "button")


async def async_setup_entry(hass, entry):
    client = hass.data.setdefault(DOMAIN, {}).pop(entry.unique_id, None)
    if client is None:
        client = CloudClient(async_get_clientsession(hass), hass.async_add_executor_job,
                             entry.data["username"], entry.data[CONF_REFRESH_TOKEN],
                             entry.data[CONF_INSTALLATION_ID], device_key=entry.data.get("device_key"))
    client.installation_id = entry.data[CONF_INSTALLATION_ID]
    coordinator = CloudCoordinator(hass, entry, client)
    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.close()
        raise
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
    return unloaded

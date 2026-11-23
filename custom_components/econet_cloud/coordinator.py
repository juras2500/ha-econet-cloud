"""Lifecycle and availability of the cloud connection."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AuthError, CloudError
from .const import DOMAIN, CONF_REFRESH_TOKEN

LOGGER = logging.getLogger(__name__)


class CloudCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry: ConfigEntry, client):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry)
        self.entry = entry
        self.client = client
        self._task = None

    async def _run(self):
        try:
            await self.client.run(self._updated)
        except AuthError:
            self.async_set_update_error(UpdateFailed("ecoNET Cloud requires authentication"))
            self.entry.async_start_reauth(self.hass)

    def _updated(self):
        if self.client.refresh_token != self.entry.data[CONF_REFRESH_TOKEN]:
            self.hass.config_entries.async_update_entry(self.entry, data={
                **self.entry.data, CONF_REFRESH_TOKEN: self.client.refresh_token})
        self.async_set_updated_data(dict(self.client.values))

    async def _async_update_data(self):
        try:
            if self._task is None:
                await self.client.prepare()
                self._task = self.hass.async_create_background_task(self._run(), "ecoNET Cloud data stream")
                await asyncio.wait_for(self.client.first_values.wait(), timeout=40)
            else:
                await self.client.request_values()
            return dict(self.client.values)
        except AuthError as error:
            raise ConfigEntryAuthFailed("ecoNET Cloud authentication required") from error
        except (CloudError, TimeoutError):
            await self.close()
            detail = self.client.last_error or "No readings received"
            raise UpdateFailed(f"ecoNET Cloud: {detail}") from None

    async def close(self):
        await self.client.close()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self.entry.unique_id)}, "name": "Rekuperator",
                "configuration_url": "https://econetcloud.eu", **self.client.device}

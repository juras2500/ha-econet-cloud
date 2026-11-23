"""Shared entity helpers for confirmed controller settings."""

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import CloudError
from .controls import ControlError


class ControlEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, suffix, keys):
        super().__init__(coordinator)
        self._keys = keys
        self._attr_unique_id = f"{coordinator.entry.unique_id}_control_{suffix}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self):
        return super().available and self.coordinator.client.control_ready(self._keys)

    async def _command(self, coroutine):
        try:
            await coroutine
        except (CloudError, ControlError) as error:
            raise HomeAssistantError(str(error)) from None

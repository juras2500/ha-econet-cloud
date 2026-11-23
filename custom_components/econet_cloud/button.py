"""End a manually activated boost without replacing the schedule."""

from homeassistant.components.button import ButtonEntity

from .control_entity import ControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.client.control_profile:
        async_add_entities([StopBoost(entry.runtime_data)])


class StopBoost(ControlEntity, ButtonEntity):
    _attr_translation_key = "stop_boost"
    _attr_icon = "mdi:fan-off"

    def __init__(self, coordinator):
        super().__init__(coordinator, "stop_boost", ("u6639",))

    async def async_press(self):
        await self._command(self.coordinator.client.stop_boost())

"""Speed, boost and operating-mode selections."""

from homeassistant.components.select import SelectEntity

from .control_entity import ControlEntity
from .controls import SPEED_OPTIONS, MODE_OPTIONS, current_speed


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.client.control_profile:
        async_add_entities([CloudSpeed(entry.runtime_data), CloudMode(entry.runtime_data)])


class CloudSpeed(ControlEntity, SelectEntity):
    _attr_translation_key = "speed"
    _attr_icon = "mdi:fan"
    _attr_options = list(SPEED_OPTIONS)

    def __init__(self, coordinator):
        super().__init__(coordinator, "speed", ("u81", "u6639", "u6630", "u7074"))

    @property
    def current_option(self):
        return current_speed(self.coordinator.client.control_state())

    async def async_select_option(self, option):
        await self._command(self.coordinator.client.set_speed(option))


class CloudMode(ControlEntity, SelectEntity):
    _attr_translation_key = "operating_mode"
    _attr_icon = "mdi:calendar-clock"
    _attr_options = list(MODE_OPTIONS)

    def __init__(self, coordinator):
        super().__init__(coordinator, "mode", ("u6630",))

    @property
    def current_option(self):
        value = self.coordinator.client.control_state().get("u6630")
        return None if value is None else ("schedule" if int(value) & 1 else "manual")

    async def async_select_option(self, option):
        await self._command(self.coordinator.client.set_mode(option))

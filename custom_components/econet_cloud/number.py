"""Separate comfort temperatures for the three ventilation speeds."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature

from .control_entity import ControlEntity
from .controls import TEMPERATURE_KEYS


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.client.control_profile:
        async_add_entities(ComfortTemperature(entry.runtime_data, key, speed)
                           for speed, key in enumerate(TEMPERATURE_KEYS, 1))


class ComfortTemperature(ControlEntity, NumberEntity):
    _attr_icon = "mdi:thermometer"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key, speed):
        super().__init__(coordinator, f"comfort_{speed}", (key,))
        self.key = key
        self._attr_translation_key = f"comfort_{speed}"

    @property
    def available(self):
        return super().available and self.key in self.coordinator.client.bounds

    @property
    def native_value(self):
        return self.coordinator.client.control_state().get(self.key)

    @property
    def native_min_value(self):
        return self.coordinator.client.bounds.get(self.key, (0, 50))[0]

    @property
    def native_max_value(self):
        return self.coordinator.client.bounds.get(self.key, (0, 50))[1]

    async def async_set_native_value(self, value):
        await self._command(self.coordinator.client.set_temperature(self.key, value))

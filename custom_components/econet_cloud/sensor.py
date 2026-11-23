"""Sensors decoded from the manufacturer's display profile."""

import time

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import STALE_SECONDS


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(CloudSensor(coordinator, spec) for spec in coordinator.client.specs)


class CloudSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, spec):
        super().__init__(coordinator)
        self.spec = spec
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{spec.component}_{spec.key[1]}"
        self._attr_name = spec.name
        self._attr_device_info = coordinator.device_info
        if spec.options:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(dict.fromkeys(spec.options.values()))
        elif spec.unit:
            self._attr_native_unit_of_measurement = spec.unit
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if spec.unit == "°C":
                self._attr_device_class = SensorDeviceClass.TEMPERATURE
            elif spec.unit == "%" and "wilgot" in spec.name.lower():
                self._attr_device_class = SensorDeviceClass.HUMIDITY
        if spec.precision is not None and not spec.options:
            self._attr_suggested_display_precision = spec.precision

    @property
    def available(self):
        return (super().available and self.coordinator.client.connected and
                time.monotonic() - self.coordinator.client.seen.get(self.spec.key, 0) < STALE_SECONDS)

    @property
    def native_value(self):
        return self.spec.value(self.coordinator.data.get(self.spec.key))

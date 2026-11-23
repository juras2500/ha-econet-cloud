"""Fresh-data connectivity indication."""

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import EntityCategory


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CloudConnection(entry.runtime_data)])


class CloudConnection(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Połączenie"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_connection"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self):
        return True

    @property
    def is_on(self):
        return self.coordinator.client.live

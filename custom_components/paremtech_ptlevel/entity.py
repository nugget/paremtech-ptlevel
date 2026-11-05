"""Base entity for ParemTech PTLevel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, RECEIVER_MODEL
from .coordinator import PTLevelCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity import EntityDescription


class PTLevelEntity(CoordinatorEntity[PTLevelCoordinator]):
    """An entity belonging to one PTLevel receiver and its transmitter."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PTLevelCoordinator, description: EntityDescription
    ) -> None:
        """Initialize an entity reporting ``description`` for the receiver."""
        super().__init__(coordinator)
        self.entity_description = description
        status = coordinator.data.status
        self._attr_unique_id = f"{status.receiver_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, status.receiver_id)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(status.receiver_id))},
            configuration_url=str(coordinator.client.url().with_query(None)),
            manufacturer=MANUFACTURER,
            model=RECEIVER_MODEL,
            hw_version=status.hardware_version,
            sw_version=status.firmware_version,
            serial_number=status.receiver_id,
            name=coordinator.config_entry.title,
        )

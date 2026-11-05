"""Binary sensors for ParemTech PTLevel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import PTLevelEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PTLevelConfigEntry
    from .coordinator import PTLevelData


@dataclass(frozen=True, kw_only=True)
class PTLevelBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a PTLevel binary sensor."""

    is_on_fn: Callable[[PTLevelData], bool | None]


BINARY_SENSOR_DESCRIPTIONS: tuple[PTLevelBinarySensorEntityDescription, ...] = (
    PTLevelBinarySensorEntityDescription(
        key="report_overdue",
        translation_key="report_overdue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda data: data.report_overdue(dt_util.utcnow()),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PTLevelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PTLevel binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        PTLevelBinarySensorEntity(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class PTLevelBinarySensorEntity(PTLevelEntity, BinarySensorEntity):
    """A PTLevel binary sensor."""

    entity_description: PTLevelBinarySensorEntityDescription

    @property
    def available(self) -> bool:
        """Return whether the state is known."""
        return (
            super().available
            and self.entity_description.is_on_fn(self.coordinator.data) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.is_on_fn(self.coordinator.data)

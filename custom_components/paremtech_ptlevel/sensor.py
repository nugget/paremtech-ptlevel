"""Sensors for ParemTech PTLevel.

Transmitter values come from the last report the coordinator has seen, so
they stay available across receiver restarts; their age is what the
``last_report`` sensor and the ``report_overdue`` binary sensor are for.
Receiver values (WiFi and LoRa signal, failed transmissions) come from the
latest poll and go unavailable when the receiver does not report them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.util import dt as dt_util

from .coordinator import TRANSMITTER_STATUSES
from .entity import PTLevelEntity

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PTLevelConfigEntry
    from .coordinator import PTLevelData

type SensorValue = float | int | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class PTLevelSensorEntityDescription(SensorEntityDescription):
    """Describe a PTLevel sensor."""

    value_fn: Callable[[PTLevelData], SensorValue]


def _water_column(data: PTLevelData) -> float | None:
    """Return the water column to two decimals, or ``None`` when it has no scale."""
    if data.reading is None or (inches := data.reading.water_column_inches) is None:
        return None
    return round(inches, 2)


SENSOR_DESCRIPTIONS: tuple[PTLevelSensorEntityDescription, ...] = (
    PTLevelSensorEntityDescription(
        key="water_column",
        translation_key="water_column",
        native_unit_of_measurement=UnitOfLength.INCHES,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_water_column,
    ),
    PTLevelSensorEntityDescription(
        key="transmitter_status",
        translation_key="transmitter_status",
        device_class=SensorDeviceClass.ENUM,
        options=TRANSMITTER_STATUSES,
        value_fn=lambda data: data.transmitter_status(dt_util.utcnow()),
    ),
    PTLevelSensorEntityDescription(
        key="last_report",
        translation_key="last_report",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.last_report,
    ),
    PTLevelSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda data: data.reading.battery_voltage if data.reading else None,
    ),
    PTLevelSensorEntityDescription(
        key="raw_pressure",
        translation_key="raw_pressure",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.reading.raw if data.reading else None,
    ),
    PTLevelSensorEntityDescription(
        key="zero_point",
        translation_key="zero_point",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.reading.zero if data.reading else None,
    ),
    PTLevelSensorEntityDescription(
        key="transmitter_temperature",
        translation_key="transmitter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.reading.cpu_temperature if data.reading else None,
    ),
    PTLevelSensorEntityDescription(
        key="transmitter_signal",
        translation_key="transmitter_signal",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.tx_rssi,
    ),
    PTLevelSensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.wifi_rssi,
    ),
    PTLevelSensorEntityDescription(
        key="paired_transmitter",
        translation_key="paired_transmitter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.tx_id,
    ),
    PTLevelSensorEntityDescription(
        key="failed_transmissions",
        translation_key="failed_transmissions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.failed_transmissions,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: PTLevelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PTLevel sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        PTLevelSensorEntity(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class PTLevelSensorEntity(PTLevelEntity, SensorEntity):
    """A PTLevel sensor."""

    entity_description: PTLevelSensorEntityDescription

    @property
    def available(self) -> bool:
        """Return whether the receiver answered and the value is known."""
        return (
            super().available
            and self.entity_description.value_fn(self.coordinator.data) is not None
        )

    @property
    def native_value(self) -> SensorValue:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

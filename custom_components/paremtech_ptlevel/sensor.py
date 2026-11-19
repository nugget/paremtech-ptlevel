"""Sensors for ParemTech PTLevel.

Transmitter values come from the last report the coordinator has seen, so
they stay available across receiver restarts; their age is what the
``last_report`` sensor and the ``report_overdue`` binary sensor are for.
Receiver values (WiFi and LoRa signal, failed transmissions) come from the
latest poll and go unavailable when the receiver does not report them.

Water depth and percent full are derived from the water column and the tank
settings in the entry's options (see ``tank.py``). They exist only once those
settings are saved, and a tank sensor whose setting is removed is removed from
the entity registry rather than left behind as unavailable.
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
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    Platform,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import TRANSMITTER_STATUSES
from .entity import PTLevelEntity
from .tank import TankSettings

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import PTLevelConfigEntry
    from .coordinator import PTLevelCoordinator, PTLevelData

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


@dataclass(frozen=True, kw_only=True)
class PTLevelTankSensorEntityDescription(SensorEntityDescription):
    """Describe a sensor computed from the water column and the tank settings.

    ``value_fn`` receives the tank settings and the current water column in
    inches. ``needs_full_depth`` marks a sensor that exists only when the
    owner has set a full depth.
    """

    value_fn: Callable[[TankSettings, float], float | None]
    needs_full_depth: bool = False


def _percent_full(tank: TankSettings, water_column: float) -> float | None:
    """Return the fill level to one decimal, or ``None`` without a full depth."""
    percent = tank.percent_full(water_column)
    return None if percent is None else round(percent, 1)


TANK_SENSOR_DESCRIPTIONS: tuple[PTLevelTankSensorEntityDescription, ...] = (
    PTLevelTankSensorEntityDescription(
        key="water_depth",
        translation_key="water_depth",
        native_unit_of_measurement=UnitOfLength.INCHES,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda tank, water_column: round(tank.water_depth(water_column), 2),
    ),
    PTLevelTankSensorEntityDescription(
        key="percent_full",
        translation_key="percent_full",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_percent_full,
        needs_full_depth=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PTLevelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PTLevel sensors, including the tank sensors its settings allow."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        PTLevelSensorEntity(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    tank = TankSettings.from_options(entry.options)
    registry = er.async_get(hass)
    for description in TANK_SENSOR_DESCRIPTIONS:
        if tank is not None and (
            tank.full_depth is not None or not description.needs_full_depth
        ):
            entities.append(PTLevelTankSensorEntity(coordinator, tank, description))
            continue
        unique_id = f"{coordinator.data.status.receiver_id}_{description.key}"
        if entity_id := registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, unique_id
        ):
            registry.async_remove(entity_id)
    async_add_entities(entities)


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


class PTLevelTankSensorEntity(PTLevelEntity, SensorEntity):
    """A tank-level sensor, derived from the water column and tank settings.

    The settings are fixed for the entity's life: changing them reloads the
    entry, which builds new entities.
    """

    entity_description: PTLevelTankSensorEntityDescription

    def __init__(
        self,
        coordinator: PTLevelCoordinator,
        tank: TankSettings,
        description: PTLevelTankSensorEntityDescription,
    ) -> None:
        """Initialize a sensor for ``description`` on a tank set up as ``tank``."""
        super().__init__(coordinator, description)
        self._tank = tank

    @property
    def available(self) -> bool:
        """Return whether the receiver answered and there is a water column."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the sensor value, or ``None`` without a water column."""
        water_column = _water_column(self.coordinator.data)
        if water_column is None:
            return None
        return self.entity_description.value_fn(self._tank, water_column)

"""Sensors for ParemTech PTLevel.

Transmitter values come from the last report the coordinator has seen, so
they stay available across receiver restarts; their age is what the
``last_report`` sensor and the ``report_overdue`` binary sensor are for.
Receiver values (WiFi and LoRa signal, failed transmissions) come from the
latest poll and go unavailable when the receiver does not report them.

The tank sensors (water depth, percent full, water volume and tank capacity)
come from the tank settings in the entry's options (see ``tank.py``): the
first three from the water column and those settings, tank capacity from the
settings alone. They exist only once those settings are saved. A tank
sensor whose setting is removed is removed from the entity registry by entry
setup (``__init__.py``) rather than left behind as unavailable, even while
the receiver is unreachable.
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
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.util import dt as dt_util

from .coordinator import TRANSMITTER_STATUSES
from .entity import PTLevelEntity
from .tank import (
    PERCENT_FULL,
    TANK_CAPACITY,
    WATER_DEPTH,
    WATER_VOLUME,
    TankSettings,
    tank_sensor_keys,
)
from .units import from_gallons, volume_unit

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
    inches, or ``None`` when there is none; it returns ``None`` when the value
    is unknown. A ``volume`` sensor's value is in US gallons, and the entity
    reports it in the unit system's volume unit instead (see ``units.py``).
    Which settings a sensor needs is decided by its key, in
    ``tank.tank_sensor_keys``.
    """

    value_fn: Callable[[TankSettings, float | None], float | None]
    volume: bool = False


def _water_depth(tank: TankSettings, water_column: float | None) -> float | None:
    """Return the water depth to two decimals, or ``None`` without a water column."""
    if water_column is None:
        return None
    return round(tank.water_depth(water_column), 2)


def _percent_full(tank: TankSettings, water_column: float | None) -> float | None:
    """Return the fill level to one decimal, or ``None`` when it is unknown."""
    if water_column is None or (percent := tank.percent_full(water_column)) is None:
        return None
    return round(percent, 1)


def _water_volume(tank: TankSettings, water_column: float | None) -> float | None:
    """Return the water volume in US gallons, or ``None`` when it is unknown."""
    return None if water_column is None else tank.water_volume(water_column)


TANK_SENSOR_DESCRIPTIONS: tuple[PTLevelTankSensorEntityDescription, ...] = (
    PTLevelTankSensorEntityDescription(
        key=WATER_DEPTH,
        translation_key=WATER_DEPTH,
        native_unit_of_measurement=UnitOfLength.INCHES,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_water_depth,
    ),
    PTLevelTankSensorEntityDescription(
        key=PERCENT_FULL,
        translation_key=PERCENT_FULL,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_percent_full,
    ),
    PTLevelTankSensorEntityDescription(
        key=WATER_VOLUME,
        translation_key=WATER_VOLUME,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_water_volume,
        volume=True,
    ),
    PTLevelTankSensorEntityDescription(
        key=TANK_CAPACITY,
        translation_key=TANK_CAPACITY,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda tank, _water_column: tank.capacity,
        volume=True,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
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
    provided = tank_sensor_keys(entry.options)
    if tank is not None:
        entities.extend(
            PTLevelTankSensorEntity(coordinator, tank, description)
            for description in TANK_SENSOR_DESCRIPTIONS
            if description.key in provided
        )
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
    entry, which builds new entities. Volume sensors take their native unit
    from the unit system when they are built (litres or US gallons), so the
    state is a clean number in the unit most owners see; Home Assistant still
    converts it for any other display unit an owner picks. A change of unit
    system takes effect on the next reload or restart; until then Home
    Assistant shows the old native unit converted, unrounded.
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
        self._volume_unit: str | None = None
        if description.volume:
            self._volume_unit = volume_unit(coordinator.hass.config.units)
            self._attr_native_unit_of_measurement = self._volume_unit

    @property
    def available(self) -> bool:
        """Return whether the receiver answered and the value is known."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the sensor value, or ``None`` when it is unknown."""
        water_column = _water_column(self.coordinator.data)
        value = self.entity_description.value_fn(self._tank, water_column)
        if value is None or self._volume_unit is None:
            return value
        return from_gallons(value, self._volume_unit)

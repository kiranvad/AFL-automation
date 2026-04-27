from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class StockSolution:
    name: str
    concentration_mg_ml: float
    location: str
    available_volume_ul: float
    component: str = ""


@dataclass
class SampleTarget:
    sample_id: str
    component_concentrations_mg_ml: Dict[str, float]
    total_volume_ul: float
    destination: str
    temperature_c: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class PreparedSample:
    sample_id: str
    component_concentrations_mg_ml: Dict[str, float]
    total_volume_ul: float
    stock_volumes_ul: Dict[str, float]
    diluent_volume_ul: float
    source_location: str
    destination: str
    temperature_module_slot: str
    temperature_c: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class TemperatureProcessingRecord:
    sample_id: str
    temperature_c: float
    measurement_interval_s: float
    step_index: int
    total_steps: int
    temperature_module_slot: str
    destination: str
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class TransferRecord:
    sample_id: str
    from_location: str
    to_location: str
    carrier: str
    status: str = "transferred"
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class TurbidityMeasurement:
    sample_id: str
    component_concentrations_mg_ml: Dict[str, float]
    concentration_mg_ml: float
    temperature_c: float
    measurement_interval_s: float
    step_index: int
    total_steps: int
    label: str
    score: float
    image_metadata: Dict[str, object]
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class ExperimentRecord:
    sample_id: str
    component_concentrations_mg_ml: Dict[str, float]
    concentration_mg_ml: float
    temperature_c: float
    measurement_interval_s: float
    label: str
    score: float


DEFAULT_COMPONENT_BOUNDS: Dict[str, List[float]] = {
    "BSA": [0.0, 200.0],
    "YCl3": [0.0, 10.0],
}
DEFAULT_TEMPERATURE_RANGE_C = [4.0, 60.0]
DEFAULT_TEMPERATURE_COUNT = 4
DEFAULT_MEASUREMENT_INTERVAL_S = 30.0

DEFAULT_STOCKS: List[Dict[str, object]] = [
    {
        "name": "BSA_stock",
        "component": "BSA",
        "concentration_mg_ml": 200.0,
        "location": "4A1",
        "available_volume_ul": 5000.0,
    },
    {
        "name": "YCl3_stock",
        "component": "YCl3",
        "concentration_mg_ml": 10.0,
        "location": "4A2",
        "available_volume_ul": 5000.0,
    },
    {
        "name": "buffer",
        "component": "buffer",
        "concentration_mg_ml": 0.0,
        "location": "4A3",
        "available_volume_ul": 10000.0,
    },
]


DEFAULT_TARGETS: List[Dict[str, float]] = [
    {"BSA": 20.0, "YCl3": 1.0},
    {"BSA": 60.0, "YCl3": 3.0},
    {"BSA": 100.0, "YCl3": 5.0},
]
DEFAULT_TOTAL_VOLUME_UL = 200.0
DEFAULT_TEMP_MODULE_SLOT = "3"
DEFAULT_SAMPLE_PLATE = "corning_96_wellplate_360ul_flat"
DEFAULT_SAMPLE_WELLS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"]
DEFAULT_TURBIDITY_THRESHOLD = 90.0


def make_sample_target(index: int, component_concentrations_mg_ml: Dict[str, float], total_volume_ul: float, well: str, temperature_c: float) -> SampleTarget:
    return SampleTarget(
        sample_id=f"sample-{index:03d}",
        component_concentrations_mg_ml=dict(component_concentrations_mg_ml),
        total_volume_ul=total_volume_ul,
        destination=well,
        temperature_c=temperature_c,
    )


def measurement_to_dataset_payload(measurement: TurbidityMeasurement) -> Dict[str, object]:
    return {
        "sample_id": measurement.sample_id,
        "component_concentrations_mg_ml": dict(measurement.component_concentrations_mg_ml),
        "concentration_mg_ml": measurement.concentration_mg_ml,
        "temperature_c": measurement.temperature_c,
        "measurement_interval_s": measurement.measurement_interval_s,
        "step_index": measurement.step_index,
        "total_steps": measurement.total_steps,
        "label": measurement.label,
        "score": measurement.score,
        "image_metadata": measurement.image_metadata,
        "metadata": measurement.metadata,
    }

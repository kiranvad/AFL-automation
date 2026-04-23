from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from AFL.automation.APIServer.data.DataTiled import DataTiled


DEFAULT_TILED_URI = "file://localhost"
DEFAULT_TILED_API_KEY = ""
DEFAULT_TILED_BACKUP_DIR = Path(__file__).resolve().parent / ".tiled-backup"


class LocalTiledClient:
    def __init__(self):
        self._entries: List[Dict[str, object]] = []

    def write_array(self, array, metadata=None):
        entry = {
            "array": np.asarray(array),
            "metadata": dict(metadata or {}),
        }
        self._entries.append(entry)
        return entry

    def write_dataframe(self, dataframe, metadata=None):
        entry = {
            "dataframe": dataframe,
            "metadata": dict(metadata or {}),
        }
        self._entries.append(entry)
        return entry

    def search(self, **criteria):
        return [
            entry for entry in self._entries
            if all(entry["metadata"].get(key) == value for key, value in criteria.items())
        ]

    def latest(self, **criteria):
        matches = self.search(**criteria)
        if not matches:
            raise KeyError(f"No Tiled entry matches {criteria}")
        return matches[-1]

    def all_entries(self):
        return list(self._entries)


class ExampleDataTiled(DataTiled):
    def __init__(self, backup_path: Optional[Path] = None):
        self.backup_path = str(backup_path or DEFAULT_TILED_BACKUP_DIR)
        Path(self.backup_path).mkdir(parents=True, exist_ok=True)
        self.tiled_client = LocalTiledClient()
        from AFL.automation.APIServer.data.DataPacket import DataPacket

        DataPacket.__init__(self)
        self.arrays = {}


class ExampleTiledConfig:
    def __init__(
        self,
        uri: Optional[str] = None,
        api_key: str = DEFAULT_TILED_API_KEY,
        backup_path: Optional[Path] = None,
        use_fallback: bool = True,
    ):
        self.uri = uri
        self.api_key = api_key
        self.backup_path = Path(backup_path or DEFAULT_TILED_BACKUP_DIR)
        self.use_fallback = use_fallback


def build_data_backend(config: Optional[ExampleTiledConfig] = None):
    config = config or ExampleTiledConfig()
    config.backup_path.mkdir(parents=True, exist_ok=True)
    if config.uri:
        return DataTiled(config.uri, api_key=config.api_key, backup_path=str(config.backup_path))
    if config.use_fallback:
        return ExampleDataTiled(backup_path=config.backup_path)
    return None


def _as_record(payload: object) -> Dict[str, object]:
    if is_dataclass(payload):
        return asdict(payload)
    return dict(payload)


def _write_stage_record(data, sample_id: str, stage: str, array_name: str, payload: Dict[str, object], array=None):
    if data is None:
        return None
    data.reset()
    data.reset_sample()
    data["driver_name"] = stage
    data["sample_uuid"] = str(sample_id)
    data["sample_name"] = str(sample_id)
    data["data_name"] = stage
    data["array_name"] = array_name
    data[f"{stage}_record"] = payload
    if array is None:
        array = np.asarray([0.0], dtype=float)
    data.add_array(array_name, np.asarray(array))
    data.finalize()
    return payload


def store_preparation(data, prepared_sample: object):
    record = _as_record(prepared_sample)
    component_names = list(record.get("component_concentrations_mg_ml", {}).keys())
    array_values = [float(record["component_concentrations_mg_ml"][name]) for name in component_names]
    array_values.append(float(record["total_volume_ul"]))
    record["components"] = component_names
    array = np.asarray([array_values], dtype=float)
    return _write_stage_record(data, record["sample_id"], "opentrons_prepare", "prepared_sample", record, array=array)


def store_transfer(data, transfer: object):
    record = _as_record(transfer)
    array = np.asarray([[1.0]], dtype=float)
    return _write_stage_record(data, record["sample_id"], "xarm_transfer", "transfer_record", record, array=array)


def build_measurement_metadata(measurement: Dict[str, object]) -> Dict[str, object]:
    image_metadata = dict(measurement.get("image_metadata", {}))
    nested_metadata = dict(measurement.get("metadata", {}))
    return {
        "sample_uuid": str(measurement["sample_id"]),
        "sample_name": str(measurement["sample_id"]),
        "array_name": "turbidity_image",
        "component_concentrations_mg_ml": dict(measurement.get("component_concentrations_mg_ml", {})),
        "data_name": "turbidity",
        "label": str(measurement["label"]),
        "score": float(measurement["score"]),
        "concentration_mg_ml": float(measurement["concentration_mg_ml"]),
        "image_metadata": image_metadata,
        "measurement_metadata": nested_metadata,
    }


def store_measurement(data, measurement: Dict[str, object]):
    metadata = build_measurement_metadata(measurement)
    image_array = np.asarray(
        [[float(measurement["concentration_mg_ml"]), float(measurement["score"])]],
        dtype=float,
    )
    if data is None:
        return metadata
    data.reset()
    data.reset_sample()
    data["driver_name"] = "turbidity"
    for key, value in metadata.items():
        data[key] = value
    data["turbidity_record"] = dict(measurement)
    data.add_array("turbidity_image", image_array)
    data.finalize()
    return metadata


def store_agent_append(data, dataset, record: Dict[str, object]):
    sample_id = str(dataset.attrs.get("sample_uuid", dataset.coords["sample"].values[0]))
    array = np.asarray([[float(record["concentration_mg_ml"]), float(record["score"])]], dtype=float)
    payload = {
        "sample_id": sample_id,
        "record": dict(record),
        "dataset_attrs": dict(dataset.attrs),
    }
    return _write_stage_record(data, sample_id, "agent_append", "agent_observation", payload, array=array)


def store_agent_prediction(data, sample_id: str, composition: Dict[str, float], campaign_name: Optional[str] = None):
    payload = {
        "sample_id": str(sample_id),
        "next_composition": dict(composition),
        "AL_campaign_name": campaign_name,
    }
    component_names = list(composition.keys())
    array = np.asarray([[float(composition[name]) for name in component_names]], dtype=float)
    payload["components"] = component_names
    return _write_stage_record(data, sample_id, "agent_predict", "agent_prediction", payload, array=array)


def measurement_from_tiled_entry(entry: Dict[str, object]) -> Dict[str, object]:
    metadata = dict(entry["metadata"])
    return {
        "samponent_concentrations_mg_ml": dict(metadata.get("component_concentrations_mg_ml", {})),
        "comple_id": metadata["sample_uuid"],
        "concentration_mg_ml": metadata["concentration_mg_ml"],
        "label": metadata["label"],
        "score": metadata["score"],
        "image_metadata": metadata.get("image_metadata", {}),
        "metadata": metadata.get("measurement_metadata", {}),
        "tiled_array_name": metadata.get("array_name", "turbidity_image"),
    }


def records_for_sample(data, sample_id: str):
    if data is None:
        return []
    return data.tiled_client.search(sample_uuid=str(sample_id))


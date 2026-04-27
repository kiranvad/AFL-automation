from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

import xarray as xr

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver

from common import DEFAULT_MEASUREMENT_INTERVAL_S, DEFAULT_TEMPERATURE_COUNT, DEFAULT_TEMPERATURE_RANGE_C
from tiled_data import store_agent_append, store_agent_prediction


class AgentExampleDriver(Driver):
    defaults = {
        "component_bounds": {
            "BSA": [0.0, 200.0],
            "YCl3": [0.0, 10.0],
        },
        "temperature_bounds": DEFAULT_TEMPERATURE_RANGE_C,
        "temperature_count": DEFAULT_TEMPERATURE_COUNT,
        "measurement_interval_s": DEFAULT_MEASUREMENT_INTERVAL_S,
        "random_seed": None,
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(self, name="AgentExampleDriver", defaults=self.gather_defaults(), overrides=overrides)
        self._history: List[Dict[str, object]] = []
        self.data = data
        self._rng = random.Random(self.config.get("random_seed"))

    def _normalize_dataset(self, dataset: xr.Dataset) -> Dict[str, object]:
        score = float(dataset["score"].values[0])
        label_value = dataset["label"].values[0]
        if hasattr(label_value, "item"):
            label_value = label_value.item()
        label = str(label_value)
        record: Dict[str, object] = {
            "score": score,
            "label": label,
        }
        if "concentration_mg_ml" in dataset:
            record["concentration_mg_ml"] = float(dataset["concentration_mg_ml"].values[0])
        for variable_name, data_array in dataset.data_vars.items():
            if variable_name in {"score", "label", "concentration_mg_ml", "next_samples", "temperature_series"}:
                continue
            value = data_array.values[0]
            if hasattr(value, "item"):
                value = value.item()
            try:
                record[variable_name] = float(value)
            except (TypeError, ValueError):
                record[variable_name] = value
        if "temperature_series" in dataset:
            record["temperature_series"] = [float(value) for value in dataset["temperature_series"].values[0].tolist()]
        return record

    def _component_bounds(self) -> Dict[str, Tuple[float, float]]:
        bounds = {}
        for component, limits in dict(self.config["component_bounds"]).items():
            if len(limits) != 2:
                raise ValueError(f"Bounds for {component} must have exactly two values")
            lower = float(limits[0])
            upper = float(limits[1])
            if lower > upper:
                raise ValueError(f"Bounds for {component} are invalid: {limits}")
            bounds[str(component)] = (lower, upper)
        return bounds

    def _temperature_bounds(self) -> Tuple[float, float]:
        limits = list(self.config["temperature_bounds"])
        if len(limits) != 2:
            raise ValueError("temperature_bounds must have exactly two values")
        lower = float(limits[0])
        upper = float(limits[1])
        if lower > upper:
            raise ValueError(f"temperature_bounds are invalid: {limits}")
        return lower, upper

    def _random_composition(self) -> Dict[str, float]:
        bounds = self._component_bounds()
        for _ in range(1000):
            composition = {}
            total_fraction = 0.0
            for component, (lower, upper) in bounds.items():
                value = self._rng.uniform(lower, upper)
                composition[component] = round(value, 6)
                if upper > 0:
                    total_fraction += value / upper
            if total_fraction <= 1.0 + 1e-9:
                return composition
        raise RuntimeError("Unable to sample a feasible composition within the configured bounds")

    def _suggest_temperatures(self) -> List[float]:
        lower, upper = self._temperature_bounds()
        count = max(int(self.config["temperature_count"]), 1)
        if count == 1:
            return [round(lower, 6)]
        step = (upper - lower) / float(count - 1)
        return [round(lower + step * index, 6) for index in range(count)]

    @Driver.unqueued()
    def status(self):
        return {
            "history_count": len(self._history),
            "component_bounds": dict(self.config["component_bounds"]),
            "temperature_bounds": list(self.config["temperature_bounds"]),
            "temperature_count": int(self.config["temperature_count"]),
            "measurement_interval_s": float(self.config["measurement_interval_s"]),
        }

    @Driver.queued()
    def append(self, db_uuid: str, concat_dim: str = "sample"):
        dataset = self.retrieve_obj(db_uuid)
        if not isinstance(dataset, xr.Dataset):
            raise TypeError("Agent append expects an xarray Dataset")
        record = self._normalize_dataset(dataset)
        self._history.append(record)
        self.set_sample(
            str(dataset.attrs.get("sample_uuid", dataset.coords["sample"].values[0])),
            sample_uuid=str(dataset.attrs.get("sample_uuid", dataset.coords["sample"].values[0])),
        )
        store_agent_append(self.data, dataset, record)
        return record

    @Driver.queued()
    def predict(self, sample_uuid: Optional[str] = None, AL_campaign_name: Optional[str] = None):
        composition = self._random_composition()
        temperature_series = self._suggest_temperatures()
        sample_id = sample_uuid or "next-sample"
        campaign_name = AL_campaign_name or "bioformulations"
        measurement_interval_s = float(self.config["measurement_interval_s"])
        self.set_sample(sample_id, sample_uuid=sample_id, AL_campaign_name=campaign_name)
        store_agent_prediction(
            self.data,
            sample_id,
            composition,
            temperature_series,
            measurement_interval_s=measurement_interval_s,
            campaign_name=campaign_name,
        )
        components = list(composition.keys())
        values = [[composition[component] for component in components]]
        dataset = xr.Dataset(
            {
                "next_samples": xr.DataArray(
                    values,
                    dims=("sample", "component"),
                    coords={"sample": [sample_id], "component": components},
                ),
                "temperature_series": xr.DataArray(
                    [temperature_series],
                    dims=("sample", "temperature_index"),
                    coords={"sample": [sample_id], "temperature_index": list(range(len(temperature_series)))},
                ),
                "measurement_interval_s": xr.DataArray([measurement_interval_s], dims=("sample",)),
            }
        )
        return self.deposit_obj(dataset)

    @Driver.unqueued()
    def history(self):
        return list(self._history)



def build_server(host: str = "127.0.0.1", port: int = 5054, overrides: Optional[Dict] = None, data=None):
    server = APIServer("AgentExample", data=data)
    server.add_standard_routes()
    server.create_queue(AgentExampleDriver(overrides=overrides, data=data))
    return server, host, port


if __name__ == "__main__":
    server, host, port = build_server()
    server.run(host=host, port=port, debug=False, use_reloader=False)

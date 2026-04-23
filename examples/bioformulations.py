from __future__ import annotations

from typing import Dict, List, Optional

import xarray as xr

from AFL.automation.APIServer.Client import Client

from agent import build_server as build_agent_server
from common import DEFAULT_COMPONENT_BOUNDS, DEFAULT_STOCKS, DEFAULT_TARGETS, DEFAULT_TOTAL_VOLUME_UL
from example_logging import (
    get_logger,
    log_agent_suggestion,
    log_measurement_result,
    log_measurement_triggered,
    log_prepare_request,
    log_server_initialized,
    log_setup,
    log_transfer,
    silence_framework_logging,
    suppress_startup_output,
)
from opentrons import build_server as build_opentrons_server
from tiled_data import ExampleTiledConfig, build_data_backend, records_for_sample
from turbidity import build_server as build_turbidity_server
from xarm import build_server as build_xarm_server


DEFAULT_PORTS = {
    "prep": 5051,
    "load": 5052,
    "instrument": 5053,
    "agent": 5054,
}


def _prediction_to_composition(prediction: xr.Dataset) -> Dict[str, float]:
    components = [str(component) for component in prediction.coords["component"].values.tolist()]
    values = prediction["next_samples"].values[0].tolist()
    return {component: float(value) for component, value in zip(components, values)}


def _unwrap_queue_result(meta: Dict[str, object], task_name: str):
    result = meta.get("return_val")
    if isinstance(result, str) and result.startswith("Error:"):
        raise RuntimeError(f"{task_name} failed: {result}")
    return result

def start_local_servers(
    host: str = "127.0.0.1",
    ports: Optional[Dict[str, int]] = None,
    tiled_config: Optional[ExampleTiledConfig] = None,
    tiled_data=None,
    component_bounds: Optional[Dict[str, List[float]]] = None,
    logger=None,
):
    ports = ports or DEFAULT_PORTS
    servers = {}
    tiled_data = tiled_data or build_data_backend(tiled_config)
    agent_overrides = {"component_bounds": dict(component_bounds or DEFAULT_COMPONENT_BOUNDS)}
    prep_overrides = {"stocks": [dict(stock) for stock in DEFAULT_STOCKS]}
    builders = {
        "prep": lambda **kwargs: build_opentrons_server(data=tiled_data, overrides=prep_overrides, **kwargs),
        "load": lambda **kwargs: build_xarm_server(data=tiled_data, **kwargs),
        "instrument": lambda **kwargs: build_turbidity_server(data=tiled_data, **kwargs),
        "agent": lambda **kwargs: build_agent_server(data=tiled_data, overrides=agent_overrides, **kwargs),
    }
    silence_framework_logging()
    with suppress_startup_output():
        for name, builder in builders.items():
            server, _, _ = builder(host=host, port=ports[name])
            server.run_threaded(host=host, port=ports[name], debug=False, use_reloader=False, use_waitress=False)
            servers[name] = server
    if logger is not None:
        for name, port in ports.items():
            log_server_initialized(logger, name, host, port)
    servers["tiled_data"] = tiled_data
    return servers


def make_clients(host: str = "127.0.0.1", ports: Optional[Dict[str, int]] = None):
    ports = ports or DEFAULT_PORTS
    clients = {}
    for name, port in ports.items():
        client = Client(ip=host, port=str(port), interactive=True)
        client.login("BioformulationsExample")
        clients[name] = client
    return clients


def measurement_to_dataset(measurement: Dict[str, object]) -> xr.Dataset:
    component_concentrations = dict(measurement.get("component_concentrations_mg_ml", {}))
    data_vars = {
        "concentration_mg_ml": xr.DataArray([float(measurement["concentration_mg_ml"])], dims=("sample",)),
        "score": xr.DataArray([float(measurement["score"])], dims=("sample",)),
        "label": xr.DataArray([str(measurement["label"])], dims=("sample",)),
    }
    for component, concentration in component_concentrations.items():
        data_vars[str(component)] = xr.DataArray([float(concentration)], dims=("sample",))
    return xr.Dataset(
        data_vars,
        coords={"sample": [str(measurement["sample_id"])]},
        attrs={
            "sample_uuid": str(measurement["sample_id"]),
            "data_name": "turbidity",
            "tiled_array_name": str(measurement.get("tiled_array_name", "turbidity_image")),
            "component_concentrations_mg_ml": component_concentrations,
        },
    )


def load_sample_records(sample_id: str, tiled_data) -> List[Dict[str, object]]:
    return records_for_sample(tiled_data, sample_id)


def run_protocol(
    budget: int = 5,
    initial_targets: Optional[List[Dict[str, float]]] = None,
    total_volume_ul: float = DEFAULT_TOTAL_VOLUME_UL,
    host: str = "127.0.0.1",
    ports: Optional[Dict[str, int]] = None,
    tiled_config: Optional[ExampleTiledConfig] = None,
    component_bounds: Optional[Dict[str, List[float]]] = None,
):
    ports = ports or DEFAULT_PORTS
    component_bounds = dict(component_bounds or DEFAULT_COMPONENT_BOUNDS)
    logger = get_logger()
    start_local_servers(
        host=host,
        ports=ports,
        tiled_config=tiled_config,
        component_bounds=component_bounds,
        logger=logger,
    )
    clients = make_clients(host=host, ports=ports)
    log_setup(logger, DEFAULT_STOCKS, component_bounds)

    requested = [dict(target) for target in (initial_targets or DEFAULT_TARGETS)]
    history: List[Dict[str, object]] = []
    seen_compositions = set()

    while len(history) < budget:
        if requested:
            composition = dict(requested.pop(0))
        else:
            prediction_meta = clients["agent"].enqueue(task_name="predict", sample_uuid=f"sample-{len(history)+1:03d}")
            prediction_uuid = _unwrap_queue_result(prediction_meta, "predict")
            prediction = clients["agent"].retrieve_obj(uid=prediction_uuid)
            composition = _prediction_to_composition(prediction)
            log_agent_suggestion(logger, composition)

        composition_key = tuple(sorted((component, round(float(value), 6)) for component, value in composition.items()))
        if composition_key in seen_compositions:
            break
        seen_compositions.add(composition_key)

        log_prepare_request(logger, composition)
        prepare_meta = clients["prep"].enqueue(
            task_name="prepare",
            target={"component_concentrations_mg_ml": composition, "total_volume_ul": total_volume_ul},
        )
        prepare_result = _unwrap_queue_result(prepare_meta, "prepare")
        prepared_sample = prepare_result[0]

        log_transfer(logger, prepared_sample["sample_id"], "turbidity_station")
        transfer_meta = clients["load"].enqueue(task_name="transfer", sample=prepared_sample)
        transfer = _unwrap_queue_result(transfer_meta, "transfer")

        log_measurement_triggered(logger, prepared_sample["sample_id"])
        measurement_meta = clients["instrument"].enqueue(task_name="measure", transfer=transfer)
        measurement = _unwrap_queue_result(measurement_meta, "measure")
        stored_measurement = measurement
        log_measurement_result(logger, stored_measurement["sample_id"], stored_measurement["label"])

        dataset = measurement_to_dataset(stored_measurement)
        db_uuid = clients["agent"].deposit_obj(dataset)
        append_meta = clients["agent"].enqueue(task_name="append", db_uuid=db_uuid, concat_dim="sample")
        _unwrap_queue_result(append_meta, "append")

        next_meta = clients["agent"].enqueue(task_name="predict", sample_uuid=measurement["sample_id"])
        next_uuid = _unwrap_queue_result(next_meta, "predict")
        next_prediction = clients["agent"].retrieve_obj(uid=next_uuid)
        next_composition = _prediction_to_composition(next_prediction)
        log_agent_suggestion(logger, next_composition)

        history.append(
            {
                "requested_component_concentrations_mg_ml": composition,
                "prepared_sample": prepared_sample,
                "transfer": transfer,
                "measurement": stored_measurement,
                "next_component_concentrations_mg_ml": next_composition,
            }
        )
        requested.append(next_composition)

    return history


if __name__ == "__main__":
    run_protocol()

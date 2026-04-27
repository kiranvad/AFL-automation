from __future__ import annotations

import os
from typing import Dict, List, Optional

import xarray as xr

from AFL.automation.APIServer.Client import Client

from agent import build_server as build_agent_server
from common import (
    DEFAULT_COMPONENT_BOUNDS,
    DEFAULT_MEASUREMENT_INTERVAL_S,
    DEFAULT_STOCKS,
    DEFAULT_TARGETS,
    DEFAULT_TEMPERATURE_RANGE_C,
    DEFAULT_TOTAL_VOLUME_UL,
)
from example_logging import (
    get_logger,
    log_agent_suggestion,
    log_measurement_result,
    log_measurement_triggered,
    log_prepare_request,
    log_server_initialized,
    log_setup,
    log_temperature_plan,
    log_temperature_setpoint,
    log_transfer,
    silence_framework_logging,
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

DEFAULT_TILED_SERVER = "http://127.0.0.1:8000"
DEFAULT_TILED_API_KEY = "devkey"
DEFAULT_OT2_ROBOT_PORT = "31950"


def local_tiled_config(
    uri: Optional[str] = None,
    api_key: Optional[str] = None,
    use_fallback: bool = False,
) -> ExampleTiledConfig:
    return ExampleTiledConfig(
        uri=uri or os.environ.get("BIOFORMULATIONS_TILED_URI", DEFAULT_TILED_SERVER),
        api_key=api_key or os.environ.get("BIOFORMULATIONS_TILED_API_KEY", DEFAULT_TILED_API_KEY),
        use_fallback=use_fallback,
    )


def local_prep_config() -> Dict[str, object]:
    robot_ip = os.environ.get("BIOFORMULATIONS_OT2_IP")
    base_url = os.environ.get("BIOFORMULATIONS_OT2_BASE_URL")
    use_hardware = bool(base_url or robot_ip)
    config: Dict[str, object] = {
        "ot2_use_hardware": use_hardware,
        "ot2_base_url": base_url,
        "ot2_robot_ip": robot_ip,
        "ot2_robot_port": os.environ.get("BIOFORMULATIONS_OT2_PORT", DEFAULT_OT2_ROBOT_PORT),
        "temp_module_model": os.environ.get("BIOFORMULATIONS_OT2_TEMP_MODULE", "temperatureModuleV2"),
        "ot2_wait_for_temperature": os.environ.get("BIOFORMULATIONS_OT2_WAIT_FOR_TEMP", "true").lower() not in {"0", "false", "no"},
        "ot2_temperature_timeout": int(os.environ.get("BIOFORMULATIONS_OT2_TEMP_TIMEOUT", "120")),
    }
    return config


def _prediction_to_request(prediction: xr.Dataset) -> Dict[str, object]:
    components = [str(component) for component in prediction.coords["component"].values.tolist()]
    values = prediction["next_samples"].values[0].tolist()
    composition = {component: float(value) for component, value in zip(components, values)}
    temperatures = [float(value) for value in prediction["temperature_series"].values[0].tolist()]
    measurement_interval_s = float(prediction["measurement_interval_s"].values[0])
    return {
        "component_concentrations_mg_ml": composition,
        "temperature_series": temperatures,
        "measurement_interval_s": measurement_interval_s,
    }


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
    temperature_bounds: Optional[List[float]] = None,
    measurement_interval_s: float = DEFAULT_MEASUREMENT_INTERVAL_S,
    prep_overrides: Optional[Dict[str, object]] = None,
    logger=None,
):
    ports = ports or DEFAULT_PORTS
    tiled_data = tiled_data or build_data_backend(tiled_config)
    silence_framework_logging()
    servers = {
        "prep": build_opentrons_server(
            host=host,
            port=ports["prep"],
            data=tiled_data,
            overrides={"stocks": [dict(stock) for stock in DEFAULT_STOCKS], **dict(prep_overrides or {})},
        )[0],
        "load": build_xarm_server(host=host, port=ports["load"], data=tiled_data)[0],
        "instrument": build_turbidity_server(host=host, port=ports["instrument"], data=tiled_data)[0],
        "agent": build_agent_server(
            host=host,
            port=ports["agent"],
            data=tiled_data,
            overrides={
                "component_bounds": dict(component_bounds or DEFAULT_COMPONENT_BOUNDS),
                "temperature_bounds": list(temperature_bounds or DEFAULT_TEMPERATURE_RANGE_C),
                "measurement_interval_s": float(measurement_interval_s),
            },
        )[0],
    }
    for name, server in servers.items():
        server.run_threaded(host=host, port=ports[name], debug=False, use_reloader=False, use_waitress=False, quiet=True)
        if logger is not None:
            log_server_initialized(logger, name, host, ports[name])
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
        "temperature_c": xr.DataArray([float(measurement["temperature_c"])], dims=("sample",)),
        "measurement_interval_s": xr.DataArray([float(measurement["measurement_interval_s"])], dims=("sample",)),
        "step_index": xr.DataArray([int(measurement["step_index"])], dims=("sample",)),
        "total_steps": xr.DataArray([int(measurement["total_steps"])], dims=("sample",)),
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
    prep_overrides: Optional[Dict[str, object]] = None,
    component_bounds: Optional[Dict[str, List[float]]] = None,
    temperature_bounds: Optional[List[float]] = None,
    measurement_interval_s: float = DEFAULT_MEASUREMENT_INTERVAL_S,
):
    ports = ports or DEFAULT_PORTS
    component_bounds = dict(component_bounds or DEFAULT_COMPONENT_BOUNDS)
    temperature_bounds = list(temperature_bounds or DEFAULT_TEMPERATURE_RANGE_C)
    logger = get_logger()
    start_local_servers(
        host=host,
        ports=ports,
        tiled_config=tiled_config,
        component_bounds=component_bounds,
        temperature_bounds=temperature_bounds,
        prep_overrides=prep_overrides,
        measurement_interval_s=measurement_interval_s,
        logger=logger,
    )
    clients = make_clients(host=host, ports=ports)
    log_setup(logger, DEFAULT_STOCKS, component_bounds, temperature_bounds, measurement_interval_s)

    requested = [
        {
            "component_concentrations_mg_ml": dict(target),
            "temperature_series": list(temperature_bounds),
            "measurement_interval_s": float(measurement_interval_s),
        }
        for target in (initial_targets or DEFAULT_TARGETS)
    ]
    history: List[Dict[str, object]] = []
    seen_requests = set()

    while len(history) < budget:
        if requested:
            experiment_request = dict(requested.pop(0))
        else:
            prediction_meta = clients["agent"].enqueue(task_name="predict", sample_uuid=f"sample-{len(history)+1:03d}")
            prediction_uuid = _unwrap_queue_result(prediction_meta, "predict")
            prediction = clients["agent"].retrieve_obj(uid=prediction_uuid)
            experiment_request = _prediction_to_request(prediction)
            log_agent_suggestion(
                logger,
                experiment_request["component_concentrations_mg_ml"],
                experiment_request["temperature_series"],
            )

        composition = dict(experiment_request["component_concentrations_mg_ml"])
        temperatures = [float(value) for value in experiment_request["temperature_series"]]
        interval_s = float(experiment_request.get("measurement_interval_s", measurement_interval_s))
        request_key = (
            tuple(sorted((component, round(float(value), 6)) for component, value in composition.items())),
            tuple(round(value, 6) for value in temperatures),
        )
        if request_key in seen_requests:
            break
        seen_requests.add(request_key)

        log_prepare_request(logger, composition)
        prepare_meta = clients["prep"].enqueue(
            task_name="prepare",
            target={"component_concentrations_mg_ml": composition, "total_volume_ul": total_volume_ul},
        )
        prepare_result = _unwrap_queue_result(prepare_meta, "prepare")
        prepared_sample = prepare_result[0]
        log_temperature_plan(logger, prepared_sample["sample_id"], temperatures, interval_s)

        transfer_meta = clients["load"].enqueue(task_name="transfer", sample=prepared_sample)
        transfer = _unwrap_queue_result(transfer_meta, "transfer")
        log_transfer(logger, prepared_sample["sample_id"], transfer["to_location"])

        temperature_steps: List[Dict[str, object]] = []
        measurements: List[Dict[str, object]] = []
        total_steps = len(temperatures)
        for step_index, temperature_c in enumerate(temperatures):
            log_temperature_setpoint(logger, prepared_sample["sample_id"], temperature_c, step_index, total_steps)
            temperature_meta = clients["prep"].enqueue(
                task_name="process_temperature_step",
                sample=prepared_sample,
                temperature_c=temperature_c,
                step_index=step_index,
                total_steps=total_steps,
                measurement_interval_s=interval_s,
            )
            temperature_step = _unwrap_queue_result(temperature_meta, "process_temperature_step")
            temperature_steps.append(temperature_step)

            log_measurement_triggered(logger, prepared_sample["sample_id"], temperature_c, interval_s)
            measurement_meta = clients["instrument"].enqueue(
                task_name="measure",
                transfer=transfer,
                temperature_step=temperature_step,
            )
            measurement = _unwrap_queue_result(measurement_meta, "measure")
            measurements.append(measurement)
            log_measurement_result(logger, measurement["sample_id"], measurement["label"], measurement["temperature_c"])

            dataset = measurement_to_dataset(measurement)
            db_uuid = clients["agent"].deposit_obj(dataset)
            append_meta = clients["agent"].enqueue(task_name="append", db_uuid=db_uuid, concat_dim="sample")
            _unwrap_queue_result(append_meta, "append")

        next_meta = clients["agent"].enqueue(task_name="predict", sample_uuid=prepared_sample["sample_id"])
        next_uuid = _unwrap_queue_result(next_meta, "predict")
        next_prediction = clients["agent"].retrieve_obj(uid=next_uuid)
        next_request = _prediction_to_request(next_prediction)
        log_agent_suggestion(
            logger,
            next_request["component_concentrations_mg_ml"],
            next_request["temperature_series"],
        )

        history.append(
            {
                "requested_component_concentrations_mg_ml": composition,
                "requested_temperature_series": temperatures,
                "measurement_interval_s": interval_s,
                "prepared_sample": prepared_sample,
                "transfer": transfer,
                "temperature_steps": temperature_steps,
                "measurements": measurements,
                "next_request": next_request,
            }
        )
        requested.append(next_request)

    return history


if __name__ == "__main__":
    run_protocol(tiled_config=local_tiled_config(), prep_overrides=local_prep_config())

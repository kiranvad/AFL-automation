from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.prepare.OT2HTTPDriver import OT2HTTPDriver

from tiled_data import store_preparation, store_temperature_processing

from common import (
    DEFAULT_MEASUREMENT_INTERVAL_S,
    DEFAULT_SAMPLE_PLATE,
    DEFAULT_SAMPLE_WELLS,
    DEFAULT_STOCKS,
    DEFAULT_TEMP_MODULE_SLOT,
    PreparedSample,
    SampleTarget,
    StockSolution,
    TemperatureProcessingRecord,
    make_sample_target,
)


class OpentronsExampleDriver(Driver):
    defaults = {
        "stocks": DEFAULT_STOCKS,
        "temp_module_slot": DEFAULT_TEMP_MODULE_SLOT,
        "temp_module_model": "temperatureModuleV2",
        "sample_plate": DEFAULT_SAMPLE_PLATE,
        "sample_wells": DEFAULT_SAMPLE_WELLS,
        "temperature_c": 8.0,
        "measurement_interval_s": DEFAULT_MEASUREMENT_INTERVAL_S,
        "diluent_name": "buffer",
        "ot2_use_hardware": False,
        "ot2_base_url": None,
        "ot2_robot_ip": None,
        "ot2_robot_port": "31950",
        "ot2_wait_for_temperature": True,
        "ot2_temperature_timeout": 120,
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(self, name="OpentronsExampleDriver", defaults=self.gather_defaults(), overrides=overrides)
        self._stocks = self._load_stocks(self.config["stocks"])
        self._prepared_samples: Dict[str, PreparedSample] = {}
        self._temperature_history: List[TemperatureProcessingRecord] = []
        self._next_well_index = 0
        self.data = data
        self._ot2_driver = self._build_ot2_driver()
        self._ot2_temp_module_id = None

    def _load_stocks(self, stock_configs: List[Dict[str, object]]) -> Dict[str, StockSolution]:
        loaded = {}
        for stock in stock_configs:
            stock_record = dict(stock)
            inferred_component = stock_record.get("component")
            if not inferred_component:
                stock_name = str(stock_record["name"])
                concentration = float(stock_record.get("concentration_mg_ml", 0.0))
                if stock_name == "buffer" or concentration == 0.0:
                    inferred_component = "buffer"
                elif "ycl3" in stock_name.lower() or concentration <= 10.0:
                    inferred_component = "YCl3"
                else:
                    inferred_component = "BSA"
            stock_record["component"] = inferred_component
            loaded[stock_record["name"]] = StockSolution(**stock_record)
        return loaded

    def _get_stock(self, name: str) -> StockSolution:
        if name not in self._stocks:
            raise ValueError(f"Unknown stock '{name}'")
        return self._stocks[name]

    def _get_component_stock(self, component: str) -> StockSolution:
        normalized_component = str(component)
        aliases = {
            "BSA": {"BSA", "bsa", "BSA_stock", "polymer", "polymer_stock"},
            "YCl3": {"YCl3", "ycl3", "YCl3_stock"},
        }
        accepted_names = aliases.get(normalized_component, {normalized_component, f"{normalized_component}_stock"})
        for stock in self._stocks.values():
            stock_component = str(stock.component)
            if stock_component in accepted_names or stock.name in accepted_names:
                return stock
        raise ValueError(f"No stock configured for component '{component}'")

    def _allocate_well(self) -> str:
        wells = self.config["sample_wells"]
        if self._next_well_index >= len(wells):
            raise RuntimeError("No sample wells remaining on the temperature module")
        well = wells[self._next_well_index]
        self._next_well_index += 1
        return well

    def _build_ot2_driver(self):
        if not bool(self.config.get("ot2_use_hardware")):
            return None
        base_url = self.config.get("ot2_base_url")
        robot_ip = self.config.get("ot2_robot_ip")
        robot_port = str(self.config.get("ot2_robot_port") or "31950")
        if not base_url:
            if not robot_ip:
                raise ValueError("ot2_use_hardware requires ot2_base_url or ot2_robot_ip")
            base_url = f"http://{robot_ip}:{robot_port}"
        overrides = {
            "robot_ip": robot_ip or base_url.removeprefix("http://").removeprefix("https://").split(":")[0],
            "robot_port": robot_port,
        }
        driver = OT2HTTPDriver(overrides=overrides)
        driver.base_url = base_url.rstrip("/")
        return driver

    def _ensure_temp_module_loaded(self):
        if self._ot2_driver is None:
            return None
        slot = str(self.config["temp_module_slot"])
        if self._ot2_temp_module_id is not None:
            return self._ot2_temp_module_id
        loaded_modules = self._ot2_driver.config.get("loaded_modules", {})
        if slot in loaded_modules:
            self._ot2_temp_module_id = loaded_modules[slot][0]
            return self._ot2_temp_module_id
        module_model = str(self.config["temp_module_model"])
        self._ot2_temp_module_id = self._ot2_driver.load_module(module_model, slot)
        return self._ot2_temp_module_id

    def _set_hardware_temperature(self, temperature_c: float):
        if self._ot2_driver is None:
            return {"status": "simulated"}
        module_id = self._ensure_temp_module_loaded()
        timeout = int(self.config.get("ot2_temperature_timeout") or 120)
        wait_until_complete = bool(self.config.get("ot2_wait_for_temperature", True))
        self._ot2_driver._execute_atomic_command(
            "temperatureModule/setTargetTemperature",
            params={"moduleId": module_id, "celsius": float(temperature_c)},
            wait_until_complete=wait_until_complete,
            timeout=timeout,
        )
        return {
            "status": "hardware",
            "module_id": module_id,
            "wait_until_complete": wait_until_complete,
            "timeout": timeout,
        }

    def _build_target(self, component_concentrations_mg_ml: Dict[str, float], total_volume_ul: float, destination: Optional[str] = None) -> SampleTarget:
        well = destination or self._allocate_well()
        return make_sample_target(
            index=len(self._prepared_samples) + 1,
            component_concentrations_mg_ml=component_concentrations_mg_ml,
            total_volume_ul=total_volume_ul,
            well=well,
            temperature_c=float(self.config["temperature_c"]),
        )

    def _plan(self, target: SampleTarget) -> PreparedSample:
        diluent = self._get_stock(self.config["diluent_name"])
        stock_volumes_ul: Dict[str, float] = {}
        stock_locations: Dict[str, str] = {}
        total_stock_volume_ul = 0.0

        for component, concentration_mg_ml in target.component_concentrations_mg_ml.items():
            concentration = float(concentration_mg_ml)
            if concentration < 0:
                raise ValueError(f"Target concentration for {component} must be non-negative")
            stock = self._get_component_stock(component)
            if concentration > stock.concentration_mg_ml:
                raise ValueError(f"Target concentration for {component} exceeds stock concentration")
            stock_volume_ul = 0.0
            if stock.concentration_mg_ml > 0:
                stock_volume_ul = target.total_volume_ul * concentration / stock.concentration_mg_ml
            if stock.available_volume_ul < stock_volume_ul:
                raise ValueError(f"Insufficient stock volume available for {component}")
            stock_volumes_ul[component] = round(stock_volume_ul, 6)
            stock_locations[component] = stock.location
            total_stock_volume_ul += stock_volume_ul

        diluent_volume_ul = target.total_volume_ul - total_stock_volume_ul
        if diluent_volume_ul < -1e-9:
            raise ValueError("Requested formulation is infeasible")
        if diluent.available_volume_ul < diluent_volume_ul:
            raise ValueError("Insufficient diluent volume available")

        return PreparedSample(
            sample_id=target.sample_id,
            component_concentrations_mg_ml=dict(target.component_concentrations_mg_ml),
            total_volume_ul=target.total_volume_ul,
            stock_volumes_ul=stock_volumes_ul,
            diluent_volume_ul=round(diluent_volume_ul, 6),
            source_location=target.destination,
            destination=target.destination,
            temperature_module_slot=self.config["temp_module_slot"],
            temperature_c=target.temperature_c,
            metadata={
                "stock_locations": stock_locations,
                "diluent_location": diluent.location,
                "sample_plate": self.config["sample_plate"],
                "container_type": "temperature_module_vial",
            },
        )

    @Driver.unqueued()
    def status(self):
        return {
            "prepared_samples": len(self._prepared_samples),
            "temperature_steps": len(self._temperature_history),
            "remaining_wells": len(self.config["sample_wells"]) - self._next_well_index,
            "stocks": {name: asdict(stock) for name, stock in self._stocks.items()},
        }

    @Driver.unqueued()
    def is_feasible(self, targets: List[Dict[str, object]]):
        realized = []
        for target in targets:
            component_concentrations = dict(target["component_concentrations_mg_ml"])
            total_volume_ul = float(target.get("total_volume_ul", 200.0))
            sample_target = self._build_target(component_concentrations, total_volume_ul, destination=target.get("destination"))
            plan = self._plan(sample_target)
            realized.append(
                {
                    "sample_id": plan.sample_id,
                    "component_concentrations_mg_ml": dict(plan.component_concentrations_mg_ml),
                    "total_volume_ul": plan.total_volume_ul,
                    "destination": plan.destination,
                }
            )
        return realized

    @Driver.queued()
    def prepare(self, target: Dict[str, object], dest: Optional[str] = None):
        component_concentrations = dict(target["component_concentrations_mg_ml"])
        total_volume_ul = float(target.get("total_volume_ul", 200.0))
        sample_target = self._build_target(component_concentrations, total_volume_ul, destination=dest)
        plan = self._plan(sample_target)

        diluent = self._get_stock(self.config["diluent_name"])
        self.set_sample(plan.sample_id, sample_uuid=plan.sample_id, sample_composition=dict(plan.component_concentrations_mg_ml))
        store_preparation(self.data, plan)
        for component, stock_volume_ul in plan.stock_volumes_ul.items():
            stock = self._get_component_stock(component)
            stock.available_volume_ul -= stock_volume_ul
        diluent.available_volume_ul -= plan.diluent_volume_ul
        self._prepared_samples[plan.sample_id] = plan
        return asdict(plan), plan.destination

    @Driver.queued()
    def process_temperature_step(
        self,
        sample: Dict[str, object],
        temperature_c: float,
        step_index: int,
        total_steps: int,
        measurement_interval_s: Optional[float] = None,
    ):
        sample_id = str(sample["sample_id"])
        if sample_id not in self._prepared_samples:
            raise ValueError(f"Unknown prepared sample '{sample_id}'")
        prepared_sample = self._prepared_samples[sample_id]
        interval_s = float(measurement_interval_s if measurement_interval_s is not None else self.config["measurement_interval_s"])
        hardware_result = self._set_hardware_temperature(float(temperature_c))
        prepared_sample.temperature_c = float(temperature_c)
        record = TemperatureProcessingRecord(
            sample_id=sample_id,
            temperature_c=float(temperature_c),
            measurement_interval_s=interval_s,
            step_index=int(step_index),
            total_steps=int(total_steps),
            temperature_module_slot=prepared_sample.temperature_module_slot,
            destination=prepared_sample.destination,
            metadata={
                "sample": asdict(prepared_sample),
                "module_action": "set_temperature",
                "temperature_control": hardware_result,
            },
        )
        store_temperature_processing(self.data, record)
        self._temperature_history.append(record)
        return asdict(record)

    @Driver.unqueued()
    def get_prepared_sample(self, sample_id: str):
        if sample_id not in self._prepared_samples:
            raise ValueError(f"Unknown prepared sample '{sample_id}'")
        return asdict(self._prepared_samples[sample_id])

    @Driver.unqueued()
    def list_prepared_samples(self):
        return [asdict(sample) for sample in self._prepared_samples.values()]

    @Driver.unqueued()
    def list_temperature_steps(self):
        return [asdict(record) for record in self._temperature_history]



def build_server(
    host: str = "127.0.0.1",
    port: int = 5051,
    overrides: Optional[Dict] = None,
    data=None,
):
    server = APIServer("OpentronsExample", data=data)
    server.add_standard_routes()
    server.create_queue(OpentronsExampleDriver(overrides=overrides, data=data))
    return server, host, port


if __name__ == "__main__":
    import time
    from tiled_data import build_data_backend
    from AFL.automation.APIServer.Client import Client
    from tiled_data import ExampleTiledConfig, build_data_backend
    import os 

    HOST = "127.0.0.1"
    PORT = 5051

    overrides = {
        "ot2_use_hardware": False,
        "stocks": [
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
        ],
    }


    tiled_config = ExampleTiledConfig(
        uri=os.environ.get("TILED_URI", "http://127.0.0.1:8000"),
        api_key=os.environ.get("TILED_API_KEY", "devkey"),
        use_fallback=False,
        autostart_if_missing=True,
    )
    data = build_data_backend(tiled_config)
    server, host, port = build_server(host=HOST, port=PORT, overrides=overrides, data=data)

    server.run_threaded(host=host, port=port, debug=False, use_reloader=False, quiet=True)
    time.sleep(1.0)

    client = Client(ip=HOST, port=str(PORT))
    client.login("ot2test")

    prepare_meta = client.enqueue(
        task_name="prepare",
        target={
            "component_concentrations_mg_ml": {
                "BSA": 20.0,
                "YCl3": 1.0,
            },
            "total_volume_ul": 200.0,
        },
        interactive=True,
    )

    prepared_sample, destination = prepare_meta["return_val"]
    print("Prepared sample:", prepared_sample)
    print("Destination:", destination)

    temp_meta = client.enqueue(
        task_name="process_temperature_step",
        sample={"sample_id": prepared_sample["sample_id"]},
        temperature_c=50.0,
        step_index=1,
        total_steps=1,
        interactive=True,
    )

    print("Temperature step:", temp_meta["return_val"])
    print("Status:", client.status())
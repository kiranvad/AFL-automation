from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver

from tiled_data import store_preparation

from common import (
    DEFAULT_SAMPLE_PLATE,
    DEFAULT_SAMPLE_WELLS,
    DEFAULT_STOCKS,
    DEFAULT_TEMP_MODULE_SLOT,
    PreparedSample,
    SampleTarget,
    StockSolution,
    make_sample_target,
)


class OpentronsExampleDriver(Driver):
    defaults = {
        "stocks": DEFAULT_STOCKS,
        "temp_module_slot": DEFAULT_TEMP_MODULE_SLOT,
        "sample_plate": DEFAULT_SAMPLE_PLATE,
        "sample_wells": DEFAULT_SAMPLE_WELLS,
        "temperature_c": 8.0,
        "diluent_name": "buffer",
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(self, name="OpentronsExampleDriver", defaults=self.gather_defaults(), overrides=overrides)
        self._stocks = self._load_stocks(self.config["stocks"])
        self._prepared_samples: Dict[str, PreparedSample] = {}
        self._next_well_index = 0
        self.data = data

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

    def _build_target(self, component_concentrations_mg_ml: Dict[str, float], total_volume_ul: float, destination: Optional[str] = None) -> SampleTarget:
        well = destination or self._allocate_well()
        return make_sample_target(
            index=len(self._prepared_samples) + 1,
            component_concentrations_mg_ml=component_concentrations_mg_ml,
            total_volume_ul=total_volume_ul,
            well=well,
            temperature_c=self.config["temperature_c"],
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
            },
        )

    @Driver.unqueued()
    def status(self):
        return {
            "prepared_samples": len(self._prepared_samples),
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

    @Driver.unqueued()
    def get_prepared_sample(self, sample_id: str):
        if sample_id not in self._prepared_samples:
            raise ValueError(f"Unknown prepared sample '{sample_id}'")
        return asdict(self._prepared_samples[sample_id])

    @Driver.unqueued()
    def list_prepared_samples(self):
        return [asdict(sample) for sample in self._prepared_samples.values()]



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
    server, host, port = build_server()
    server.run(host=host, port=port, debug=False, use_reloader=False)

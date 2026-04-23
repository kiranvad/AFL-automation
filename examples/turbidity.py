from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver

from common import DEFAULT_TURBIDITY_THRESHOLD, TurbidityMeasurement
from tiled_data import measurement_from_tiled_entry, store_measurement


class TurbidityExampleDriver(Driver):
    defaults = {
        "threshold_mg_ml": DEFAULT_TURBIDITY_THRESHOLD,
        "station_name": "turbidity_station",
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(self, name="TurbidityExampleDriver", defaults=self.gather_defaults(), overrides=overrides)
        self._measurements: List[TurbidityMeasurement] = []
        self.data = data

    def _score(self, concentration_mg_ml: float) -> float:
        threshold = float(self.config["threshold_mg_ml"])
        return round((concentration_mg_ml - threshold) / max(threshold, 1.0), 6)

    @Driver.unqueued()
    def status(self):
        return {
            "station_name": self.config["station_name"],
            "threshold_mg_ml": self.config["threshold_mg_ml"],
            "measurement_count": len(self._measurements),
        }

    @Driver.queued()
    def measure(self, transfer: Dict[str, object]):
        sample = transfer["metadata"]["sample"]
        component_concentrations = dict(sample.get("component_concentrations_mg_ml", {}))
        concentration = float(component_concentrations.get("BSA", sample.get("concentration_mg_ml", 0.0)))
        score = self._score(concentration)
        label = "turbid" if concentration >= float(self.config["threshold_mg_ml"]) else "clear"
        measurement = TurbidityMeasurement(
            sample_id=str(sample["sample_id"]),
            component_concentrations_mg_ml=component_concentrations,
            concentration_mg_ml=concentration,
            label=label,
            score=score,
            image_metadata={
                "station": self.config["station_name"],
                "synthetic_image_id": f"img-{sample['sample_id']}",
                "pixel_mean": round(0.5 + score, 6),
            },
            metadata={"transfer": transfer},
        )
        measurement_dict = asdict(measurement)
        store_measurement(self.data, measurement_dict)
        self._measurements.append(measurement)
        return measurement_dict

    @Driver.unqueued()
    def list_measurements(self):
        return [asdict(measurement) for measurement in self._measurements]

    @Driver.unqueued()
    def get_measurement(self, sample_id: str, **_kwargs):
        entry = self.data.tiled_client.latest(sample_uuid=sample_id, array_name="turbidity_image")
        return measurement_from_tiled_entry(entry)



def build_server(
    host: str = "127.0.0.1",
    port: int = 5053,
    overrides: Optional[Dict] = None,
    data=None,
):
    server = APIServer("TurbidityExample", data=data)
    server.add_standard_routes()
    server.create_queue(TurbidityExampleDriver(overrides=overrides, data=data))
    return server, host, port


if __name__ == "__main__":
    server, host, port = build_server()
    server.run(host=host, port=port, debug=False, use_reloader=False)

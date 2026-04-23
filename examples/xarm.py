from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver

from common import TransferRecord
from tiled_data import store_transfer


class XArmExampleDriver(Driver):
    defaults = {
        "carrier_name": "xarm5",
        "measurement_station": "turbidity_station",
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(self, name="XArmExampleDriver", defaults=self.gather_defaults(), overrides=overrides)
        self._transfers: List[TransferRecord] = []
        self.data = data


    @Driver.unqueued()
    def status(self):
        return {
            "carrier_name": self.config["carrier_name"],
            "measurement_station": self.config["measurement_station"],
            "transfer_count": len(self._transfers),
        }

    @Driver.queued()
    def transfer(self, sample: Dict[str, object], destination: Optional[str] = None):
        target = destination or self.config["measurement_station"]
        record = TransferRecord(
            sample_id=str(sample["sample_id"]),
            from_location=str(sample["destination"]),
            to_location=target,
            carrier=self.config["carrier_name"],
            metadata={"sample": sample},
        )
        self.set_sample(record.sample_id, sample_uuid=record.sample_id)
        store_transfer(self.data, record)
        self._transfers.append(record)
        return asdict(record)

    @Driver.unqueued()
    def list_transfers(self):
        return [asdict(record) for record in self._transfers]



def build_server(
    host: str = "127.0.0.1",
    port: int = 5052,
    overrides: Optional[Dict] = None,
    data=None,
):
    server = APIServer("XArmExample", data=data)
    server.add_standard_routes()
    server.create_queue(XArmExampleDriver(overrides=overrides, data=data))
    return server, host, port


if __name__ == "__main__":
    server, host, port = build_server()
    server.run(host=host, port=port, debug=False, use_reloader=False)

import xarray as xr

from examples.agent import AgentExampleDriver
from examples.bioformulations import measurement_to_dataset, run_protocol
from examples.opentrons import OpentronsExampleDriver
from examples.tiled_data import ExampleDataTiled
from examples.turbidity import TurbidityExampleDriver
from examples.xarm import XArmExampleDriver


def test_opentrons_prepare_plan():
    driver = OpentronsExampleDriver()
    prepared, destination = driver.prepare(
        target={"concentration_mg_ml": 50.0, "total_volume_ul": 200.0},
        dest="A1",
    )
    assert destination == "A1"
    assert prepared["stock_volume_ul"] == 50.0
    assert prepared["diluent_volume_ul"] == 150.0
    assert prepared["concentration_mg_ml"] == 50.0


def test_xarm_transfer_receipt():
    driver = XArmExampleDriver()
    receipt = driver.transfer(
        sample={"sample_id": "sample-001", "destination": "A1", "concentration_mg_ml": 50.0}
    )
    assert receipt["sample_id"] == "sample-001"
    assert receipt["to_location"] == "turbidity_station"
    assert receipt["status"] == "transferred"


def test_turbidity_label_threshold():
    data = ExampleDataTiled()
    driver = TurbidityExampleDriver(overrides={"threshold_mg_ml": 90.0}, data=data)
    clear = driver.measure(
        transfer={
            "metadata": {"sample": {"sample_id": "sample-001", "concentration_mg_ml": 50.0}},
        }
    )
    turbid = driver.measure(
        transfer={
            "metadata": {"sample": {"sample_id": "sample-002", "concentration_mg_ml": 120.0}},
        }
    )
    stored = driver.get_measurement(sample_id="sample-002")
    assert clear["label"] == "clear"
    assert turbid["label"] == "turbid"
    assert stored["label"] == "turbid"
    assert stored["tiled_array_name"] == "turbidity_image"


def test_agent_append_and_predict():
    driver = AgentExampleDriver(overrides={"initial_concentration_mg_ml": 40.0, "min_step_mg_ml": 10.0})
    dataset = xr.Dataset(
        {
            "concentration_mg_ml": xr.DataArray([60.0], dims=("sample",)),
            "score": xr.DataArray([-0.2], dims=("sample",)),
            "label": xr.DataArray(["clear"], dims=("sample",)),
        },
        coords={"sample": ["sample-001"]},
    )
    db_uuid = driver.deposit_obj(dataset)
    record = driver.append(db_uuid=db_uuid)
    assert record["label"] == "clear"
    prediction_uuid = driver.predict(sample_uuid="sample-001")
    prediction = driver.retrieve_obj(prediction_uuid)
    assert float(prediction["next_samples"].values[0][0]) >= 70.0


def test_measurement_to_dataset_shape():
    dataset = measurement_to_dataset(
        {
            "sample_id": "sample-001",
            "concentration_mg_ml": 80.0,
            "score": 0.1,
            "label": "clear",
            "tiled_array_name": "turbidity_image",
        }
    )
    assert dataset["concentration_mg_ml"].dims == ("sample",)
    assert dataset["label"].values[0] == "clear"
    assert dataset.attrs["sample_uuid"] == "sample-001"
    assert dataset.attrs["tiled_array_name"] == "turbidity_image"


def test_run_protocol_budget():
    history = run_protocol(budget=3, initial_targets=[20.0, 100.0], ports={"prep": 5151, "load": 5152, "instrument": 5153, "agent": 5154})
    assert len(history) == 3
    assert history[0]["measurement"]["label"] == "clear"
    assert history[1]["measurement"]["label"] == "turbid"
    assert "next_concentration_mg_ml" in history[-1]

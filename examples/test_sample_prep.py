from AFL.automation.prepare.OT2Prepare import OT2Prepare

import numpy as np
import time 
import json

# Create the driver instance
driver = OT2Prepare(
    overrides={
        "robot_ip": "192.168.1.50",
        "robot_port": "31950",
    }
)
# Load standard labware (e.g., a 96-well plate)
# Load custom labware from JSON
with open('./custom_labware/ice_slurry_holder.json', 'r') as f:
    custom_labware_def = json.load(f)
driver.load_labware(
    name='ice_slurry_holder',
    slot='1',
    labware_json = custom_labware_def
)
# Load heater shaker module
heater_shaker_id = driver.load_module("heaterShakerModuleV1", slot="4")

driver.open_labware_latch(module_id=heater_shaker_id)
driver.load_labware(
    name="nest_96_wellplate_2ml_deep",
    slot="4",
    module=heater_shaker_id,
)
driver.close_labware_latch(module_id=heater_shaker_id)
driver.reset_stocks()

driver.add_stock({
    "name": "stock_BSA",
    "location": "1A1",
    "concentrations": {"BSA": "200 mg/ml"},
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
    "solutes": ["BSA"],
})

driver.add_stock({
    "name": "stock_YCl3",
    "location": "1A2",
    "molarities": {"YCl3": "1 mol/L"},
    "volumes": {"H2O": "10 ml"},
    "total_volume": "10 ml",
    "solutes": ["YCl3"],
})

driver.add_stock({
    "name": "stock_H2O",
    "location": "1A3",
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
})

target = {
    "name": "bsa_ycl3_sample",
    "concentrations": {"BSA": "175 mg/ml"},
    "molarities": {"YCl3": "9 mmol/L"},
    "volumes": {"H2O": "1 ml"},
    "total_volume": "1 ml",
    "solutes": ["BSA", "YCl3"],
    "location": "1B1",
}

feasible = driver.is_feasible(target)[0]
print("Feasible solution:", feasible)

def wait_for_temperature(driver, target_c, tolerance_c=1.0, timeout_s=600, poll_s=2):
    start = time.time()
    while time.time() - start < timeout_s:
        current_temp, target_temp = driver.get_shaker_temp()
        print(f"Current: {current_temp} C, Target: {target_temp} C")
        if current_temp is not None and abs(current_temp - target_c) <= tolerance_c:
            return
        time.sleep(poll_s)
    raise TimeoutError(f"Heater-shaker did not reach {target_c} C within {timeout_s} s")


result, dest = driver.prepare(target, dest="4A1")
print("Prepared at:", dest)
print("Planned mass transfers:", result["planned_mass_transfers"])
print("Executed transfers:", result["executed_transfers"])

# Gently mix the prepared sample in the heater-shaker plate
driver.set_shake(300, module_id=heater_shaker_id)
time.sleep(5)
driver.stop_shake(module_id=heater_shaker_id)

# Step through temperatures
for temp_c in [30, 60, 80]:
    print(f"Setting heater-shaker to {temp_c} C")
    driver.set_shaker_temp(temp_c, module_id=heater_shaker_id)
    wait_for_temperature(driver, temp_c, tolerance_c=1.0, timeout_s=900, poll_s=5)

    # Optional brief gentle mix at each temperature
    driver.set_shake(300, module_id=heater_shaker_id)
    time.sleep(5)
    driver.stop_shake(module_id=heater_shaker_id)

driver.stop_shaker_heat(module_id=heater_shaker_id)


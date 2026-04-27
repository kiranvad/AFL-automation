from AFL.automation.prepare.OT2Prepare import OT2Prepare
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Client import Client

import numpy as np
import time 

# Create the driver instance
driver = OT2Prepare()

# Create the server
server = APIServer('OT2PrepareServer')

# Add your driver to the queue and run
server.add_standard_routes()
server.create_queue(driver)
thread = server.run_threaded(start_thread=True, host='127.0.0.1', port=5002)
ot2_client = Client('http://localhost:5002')

# specify stock solutions
ot2_client.enqueue(task_name='reset_stocks', interactive=True)

stocks = [
    {'name': 'stock_BSA', 'masses': {'BSA': '4g', 'H2O': '16g'}, 'location': '1A1'},
    {'name': 'stock_YCl3', 'masses': {'YCl3': '1.953 g', 'H2O': '18.047 g'}, 'location': '1A2'},
    {'name': 'stock_H2O', 'masses': {'H2O': '20g'}, 'location': '1A3'},
]

for stock in stocks:
    ot2_client.enqueue(task_name='add_stock', solution=stock, interactive=True)

# specify target formulation
target = {
    'name': 'by_volume',
    'volumes': {
        'stock_BSA': '100 ul',
        'stock_YCl3': '200 ul',
        'stock_H2O': '700 ul',
    },
    'total_volume': '1000 ul',
}

destination = '1B1'

stock_locations = {
    stock['name']: stock['location']
    for stock in stocks
}

print(f"Preparing {target['name']} in {destination}...")

for stock_name, volume_text in target['volumes'].items():
    source = stock_locations[stock_name]
    volume_ul = float(volume_text.replace('ul', '').strip())

    transfer_result = ot2_client.enqueue(
        task_name='transfer',
        source=source,
        dest=destination,
        volume=volume_ul,
        interactive=True,
    )
    print(f"{stock_name}: {volume_ul} uL transferred from {source} -> {destination}")

# set a specific temperature on the heater shaker module
driver.load_module("heaterShakerModuleV1", slot="1")
driver.set_shaker_temp(4)  # Set to 4°C
current_temp, target_temp = driver.get_shaker_temp()
print(f"Current: {current_temp}°C, Target: {target_temp}°C")
time.sleep(10)  # Wait 10 seconds
current_temp, target_temp = driver.get_shaker_temp()
print(f"After wait - Current: {current_temp}°C, Target: {target_temp}°C")
driver.stop_shaker_heat()
print("Heating stopped")
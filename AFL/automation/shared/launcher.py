import os,sys,subprocess,importlib
import argparse
import tempfile
from pathlib import Path
import requests
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find AFL.automation on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.data.DataTiled import DataTiled

from AFL.automation.shared.PersistentConfig import PersistentConfig

try:
    main_module_name = _OVERRIDE_MAIN_MODULE_NAME
except NameError:
    import __main__
    main_module_fullpath = os.path.abspath(__main__.__file__)
    main_module_name = os.path.basename(main_module_fullpath).replace('.py','')
try:
    driver_module = importlib.import_module(main_module_name,'')
except ModuleNotFoundError:
    # driver_module = sys.modules[__name__]
    driver_module = __main__
driver_name = driver_module.__name__.split('.')[-1]
try:
    main_module_name = driver_module._OVERRIDE_MAIN_MODULE_NAME
    print(f'found override {main_module_name}')
except AttributeError:
    pass
driver_cls = getattr(driver_module,main_module_name)

CONFIG_PATH = os.path.join(os.path.expanduser('~'),'.afl','config.json')
AFL_LAUNCH_DEFAULTS = {
        'owner_email': '',
        'system_serial': 'Default',
        'tiled_server' : '',
        'tiled_api_key': '',
        'bind_address': '0.0.0.0',
        'ports': {},
        'driver_custom_configs': {},
        'ca_status_enabled': False,
        'ca_status_ports': {}
}

preparser = argparse.ArgumentParser(add_help=False)
preparser.add_argument('--defaults', action='store_true')
pre_args, _ = preparser.parse_known_args()

if pre_args.defaults:
        AFL_GLOBAL_CONFIG = dict(AFL_LAUNCH_DEFAULTS)
else:
        AFL_GLOBAL_CONFIG = PersistentConfig(
                CONFIG_PATH,
                defaults = AFL_LAUNCH_DEFAULTS,
                max_history=100,
        )
print(AFL_GLOBAL_CONFIG['ca_status_enabled'])
if not pre_args.defaults:
        try:
                _DEFAULT_CUSTOM_CONFIG = driver_module._DEFAULT_CUSTOM_CONFIG
                # if this driver has not provided a default custom config, we simply throw a NameError
                # and move on
                if main_module_name not in AFL_GLOBAL_CONFIG['driver_custom_configs'].keys():
                        # if there is already global config for this driver, do nothing, otherwise...
                        dccs = AFL_GLOBAL_CONFIG['driver_custom_configs']
                        dccs[main_module_name]  = _DEFAULT_CUSTOM_CONFIG
                        AFL_GLOBAL_CONFIG['driver_custom_configs'] = dccs                
                        print(f'added previously missing custom config for {driver_name} to local file')
        except (AttributeError,NameError):
                pass

        try:
                _DEFAULT_PORT = driver_module._DEFAULT_PORT
                # if this driver has not provided a default custom config, we simply throw a NameError
                # and move on
                if main_module_name not in AFL_GLOBAL_CONFIG['ports'].keys():
                        # if there is already global config for this driver, do nothing, otherwise...
                        dports = AFL_GLOBAL_CONFIG['ports']
                        dports[main_module_name]  = _DEFAULT_PORT
                        AFL_GLOBAL_CONFIG['ports'] = dports              
                        print(f'added previously missing custom port for {main_module_name} to local file')
        except (AttributeError,NameError):
                pass
if 'AFL_SYSTEM_SERIAL' not in os.environ.keys():
        os.environ['AFL_SYSTEM_SERIAL'] = AFL_LAUNCH_DEFAULTS['system_serial'] if pre_args.defaults else AFL_GLOBAL_CONFIG['system_serial']

if pre_args.defaults:
        server_port = getattr(driver_module, '_DEFAULT_PORT', 5000)
elif main_module_name in AFL_GLOBAL_CONFIG['ports'].keys():
        server_port = AFL_GLOBAL_CONFIG['ports'][main_module_name]
        print(f'Found configured non-default port {server_port}, starting there')
else:
        server_port=5000

if pre_args.defaults:
        ca_status_port = 5064
elif main_module_name in AFL_GLOBAL_CONFIG.get('ca_status_ports', {}):
        ca_status_port = AFL_GLOBAL_CONFIG['ca_status_ports'][main_module_name]
else:
        ca_status_port = 5064

if pre_args.defaults:
        if Path(CONFIG_PATH).exists():
                tiled_config = PersistentConfig(CONFIG_PATH, defaults=AFL_LAUNCH_DEFAULTS, write=False, max_history=100)
        else:
                tiled_config = AFL_LAUNCH_DEFAULTS

        tiled_server = tiled_config.get('tiled_server', '')
        if len(tiled_server) > 0:
                try:
                        requests.get(tiled_server, timeout=2)
                        data = DataTiled(tiled_server,
                                api_key = tiled_config.get('tiled_api_key', ''),
                                backup_path= os.path.join(os.path.expanduser('~'),'.afl','json-backup'),)
                except Exception as exc:
                        print(f'Warning: could not attach tiled data server at {tiled_server}: {exc}. Proceeding without tiled data server.')
                        data = None
        else:
                print('Warning: no tiled server configured in global config. Proceeding without tiled data server.')
                data = None
elif len(AFL_GLOBAL_CONFIG['tiled_server'])>0:
        data = DataTiled(AFL_GLOBAL_CONFIG['tiled_server'],
                api_key = AFL_GLOBAL_CONFIG['tiled_api_key'],
                backup_path= os.path.join(os.path.expanduser('~'),'.afl','json-backup'),)
else:
        data = None

def _instantiate_driver_with_clean_defaults(driver_factory):
        previous_afl_home = os.environ.get('AFL_HOME')
        isolated_afl_home = tempfile.mkdtemp(prefix=f'afl-defaults-{main_module_name}-')
        os.environ['AFL_HOME'] = isolated_afl_home
        try:
                return driver_factory()
        finally:
                if previous_afl_home is None:
                        os.environ.pop('AFL_HOME', None)
                else:
                        os.environ['AFL_HOME'] = previous_afl_home


def _reconstitute_objects(obj_dict,data=None):
        if not isinstance(obj_dict,dict):
            if isinstance(obj_dict,list):
                rlist = []
                for itm in obj_dict:
                    rlist.append(_reconstitute_objects(itm,data=data))
                return rlist
            else:
                return obj_dict
        if '_classname' not in obj_dict.keys():
                return obj_dict
        class_to_make = obj_dict.pop('_classname')
        if '_args' in obj_dict.keys():
                _args = obj_dict.pop('_args')
        else:
                _args = []
        args = []
        for item in _args:
                args.append(_reconstitute_objects(item,data=data))

        kwargs = {}
        if '_add_data' in obj_dict.keys():
               data_name = obj_dict.pop('_add_data')
               kwargs[data_name] = data
        for k,v in obj_dict.items():
                kwargs[k] = _reconstitute_objects(v,data=data)
        class_module_name = '.'.join(class_to_make.split('.')[:-1])
        class_module = importlib.import_module(class_module_name,'')
        cls_name = class_to_make.split('.')[-1]
        cls_obj = getattr(class_module, cls_name)
        return cls_obj(*args,**kwargs)

'''
        example input for driver_custom_configs:

        'PneumaticPressureLoader':
                '_classname': 'AFL.automation.loading.PneumaticPressureLoader.PneumaticPressureLoader',
                'p_ctrl': { '_classname': 'AFL.automation.loading.DigitalOutPressureController.DigitalOutPressureController',
                            'dig_out': {
                                 '_classname': 'AFL.automation.loading.LabJackDigitalOut',
                                 'port': 'DIO1'}}}


'''


parser = argparse.ArgumentParser(prog = f'AFL // {main_module_name}',
                                description = f'AFL APIServer launcher for {main_module_name}')
parser.add_argument('--no-waitress', action='store_true',
                    help='Disable the waitress WSGI server')
parser.add_argument('--defaults', action='store_true',
                    help='Launch with built-in defaults instead of driver/server settings from ~/.afl/config.json')

parser.add_argument('-i', '--interactive', action='store_true',
                    help='Start in interactive mode')
args = parser.parse_args()

if args.defaults:
        if hasattr(driver_module, '_DEFAULT_CUSTOM_CONFIG'):
                print(f'launching from module default custom config for {main_module_name}')
                driver = _instantiate_driver_with_clean_defaults(
                        lambda: _reconstitute_objects(driver_module._DEFAULT_CUSTOM_CONFIG,data=data)
                )
        else:
                driver = _instantiate_driver_with_clean_defaults(driver_cls)
elif main_module_name in AFL_GLOBAL_CONFIG['driver_custom_configs']:
        print(f'launching from custom config for {main_module_name}')
        driver = _reconstitute_objects(AFL_GLOBAL_CONFIG['driver_custom_configs'][main_module_name],data=data)
else:
        driver = driver_cls()
server = APIServer(main_module_name,data=data,contact='' if args.defaults else AFL_GLOBAL_CONFIG['owner_email'])
server.add_standard_routes()

# optionally publish queue status over CA
start_ca = False if args.defaults else AFL_GLOBAL_CONFIG.get('ca_status_enabled', False)
server.create_queue(
        driver,
        start_ca=start_ca,
        ca_prefix=f"AFL:{(AFL_LAUNCH_DEFAULTS['system_serial'] if args.defaults else AFL_GLOBAL_CONFIG['system_serial'])}:{main_module_name}:",
        ca_port=ca_status_port,
)
#server.add_unqueued_routes()
server.init_logging(toaddrs='' if args.defaults else AFL_GLOBAL_CONFIG['owner_email'])

#process = subprocess.Popen(['/bin/bash','-c',f'chromium-browser --start-fullscreen http://localhost:{server_port}'])#, shell=True, stdout=subprocess.PIPE)
if args.interactive:
        server.run_threaded(host=AFL_LAUNCH_DEFAULTS['bind_address'] if args.defaults else AFL_GLOBAL_CONFIG['bind_address'],
                            port=server_port,
                            use_waitress=None if not args.no_waitress else False)
        import code,time
        time.sleep(1) # this is mostly cosmetic, to let the server spin up.
        code.interact(local=globals(), banner = 'AFL APIServer started.  Access driver in "driver" global object, APIServer in "server".  Exit with ctrl-D or exit().  Have a lot of fun...')

else:
        server.run(host=AFL_LAUNCH_DEFAULTS['bind_address'] if args.defaults else AFL_GLOBAL_CONFIG['bind_address'],
                   port=server_port,
                   use_waitress=None if not args.no_waitress else False)

#process.wait()

#server._stop()
#server.join()

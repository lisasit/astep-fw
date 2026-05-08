import sys
sys.path.append('../astropix-python')

# from constellation.ASTEP import ASTEP
import argparse
import threading
import time
from constellation.core.controller import ScriptableController
from constellation.core.controller_configuration import load_config
from constellation.core.protocol.cscp1 import SatelliteState
import os
from tqdm import tqdm
from itertools import product
import toml

def main(args):
    cfg = load_config(args.config)
    group_name = "astropix"
    n_satellites = 4
    ctrl = ScriptableController(group_name)
    constellation = ctrl.constellation

    # Wait until all satellites are connected
    # while len(constellation.satellites) < n_satellites:
    #     print("Waiting for satellites...")
    #     time.sleep(0.5)
    ctrl.await_satellites(["ASTEP.astropix"])

    constellation.initialize(cfg)
    ctrl.await_state(SatelliteState.INIT)
    time.sleep(2)
    constellation.launch()
    ctrl.await_state(SatelliteState.ORBIT)

    ######################
    ## This is the only place where changes need to be made for different parameter scans
    ###################

    chip_configs = [["singlechip_v4_allmasked_test"]]
    # for trim in range(8):
    #     for vpdac in [5]:
    #         chip_configs.append([f"singlechip_v4_allmasked_trim{trim}_vpdac_{vpdac}"])


    # parameters to iterate over
    parameters = {
        # 'injection_row' : range(35),
        # 'injection_col' : range(3, 35),
        'threshold' : [1420],#[1150 + i*10 for i in range((1600 - 1150)//10 + 1)],
        'injection_voltage' : [400],
        'chip_configs' : chip_configs
    }

    # time to stay at each parameter
    wait_time = 2#5*60

    # directory for the output files
    output_directory_format = '/home/octouser/astropix/lab_scans/v4_measurements/trimming1/raw_data'

    # output files will be located in this directory with names
    # key1_value1_key2_value2_ ... _date_and_time.bin
    # key and value pairs will be taken from the parameters dictionary and ordered alphabetically

    outfile_prefix_format = '_'.join(f'{key}_{{{key}}}' for key in sorted(parameters.keys()))
    # outfile_prefix_format = 'bias200'

    ###########################################
    ## End of place to edit parameters
    ###########################################

    parameter_values = [parameters[key] for key in parameters]
    combinations = list(product(*parameter_values))
    combinations = [dict(zip(parameters.keys(), combination)) for combination in combinations]
    total_time = wait_time * len(combinations)
    print(f'The scans will take {total_time} s = {total_time/60} min = {total_time/60/60} h')

    print('Checking existing files...')
    total_combinations = len(combinations)
    dirs_to_check = [output_directory_format.format(**combination) for combination in combinations]
    # for dir_to_check in tqdm(dirs_to_check):
        # if not os.path.exists(dir_to_check):
        #     continue
        # toml_filenames = [filename for filename in os.listdir(dir_to_check) if filename.endswith('.toml')]
        # for filename in toml_filenames:
        #     old_cfg =load_config(dir_to_check + '/' + filename)
        #     try:
        #         combination = {key : old_cfg[key] for key in parameters}
        #         combinations.remove(combination)
        #     except (KeyError, ValueError):
        #         pass

    print(f'{total_combinations - len(combinations)} files exist')
    total_time = wait_time * len(combinations)
    print(f'New estimated time {total_time} s = {total_time/60} min = {total_time/60/60} h')
    # print('waiting for you to ramp up the HV')
    # time.sleep(30)

    info_format = 'Starting run with ' + ' '.join(f'{key} = {{{key}}},' for key in sorted(parameters.keys()))
    for combination in combinations:
        print(info_format.format(**combination))
        recfg = combination.copy()
        recfg['outdir'] = output_directory_format.format(**combination)
        recfg['outfile_prefix'] = outfile_prefix_format.format(**combination)

        os.makedirs(recfg['outdir'], exist_ok=True)
        constellation.ASTEP.reconfigure(recfg)
        time.sleep(0.5)
        # cfg['satellites']['ASTEP'].update(recfg)

        # Wait until ll states are back in the ORBIT state
        ctrl.await_state(SatelliteState.ORBIT)

        time_config=time.strftime("%Y%m%d-%H%M%S")
        # tomlpathout = cfg['satellites']['ASTEP']['outdir'] + '/AstroPix_Constellation_' + time_config + '.toml'
        # with open(tomlpathout, 'w') as toml_file:
            # toml_file.write(f'[satellites.{self.name}]\n')
            # toml.dump(cfg, toml_file)
        constellation.start(time_config)
        ctrl.await_state(SatelliteState.RUN)

        # Run for wait_time
        time.sleep(wait_time)

        # Stop the run and await ORBIT state of all satellites
        constellation.stop()
        ctrl.await_state(SatelliteState.ORBIT)
    constellation.land()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='ASTEP Driver Code')
    parser.add_argument('-c', '--config', required=True,
                    help='TOML configuration file describing the settings for the run')

    args = parser.parse_args()
    main(args)

import sys
sys.path.append('../astropix-python')

from constellation.ASTEP import ASTEP
import argparse
import threading
import time
from constellation.core.configuration import load_config
from constellation.core.controller import ScriptableController
from constellation.core.message.cscp1 import SatelliteState
import os
from tqdm import tqdm
from itertools import product

def main(args):
    cfg = load_config(args.config)
    group_name = "astropix"
    n_satellites = 1
    ctrl = ScriptableController(group_name)
    constellation = ctrl.constellation

    # Wait until all satellites are connected
    while len(constellation.satellites) < n_satellites:
        print("Waiting for satellites...")
        time.sleep(0.5)

    constellation.initialize(cfg)
    ctrl.await_state(SatelliteState.INIT)
    # time.sleep(0.1)
    constellation.launch()
    ctrl.await_state(SatelliteState.ORBIT)

    ######################
    ## This is the only place where changes need to be made for different parameter scans
    ###################

    # parameters to iterate over
    parameters = {
        'injection_row' : [8],
        'injection_col' : [13],
        'injection_voltage' : [0, 400, 600, 800],
        'threshold' : [900 + i*10 for i in range((1600 - 900)//10 + 1)]
    }

    # time to stay at each parameter
    wait_time = 1

    # directory for the output files
    output_directory_format = '/media/teleuser/4TB/astropix/threshold_scans_astep_test/vinj{injection_voltage}/{injection_row}_{injection_col}/raw_data'

    # output files will be located in this directory with names
    # key1_value1_key2_value2_ ... _date_and_time.bin
    # key and value pairs will be taken from the parameters dictionary and ordered alphabetically

    outfile_prefix_format = '_'.join(f'{key}_{{{key}}}' for key in sorted(parameters.keys()))

    ###########################################
    ## End of place to edit parameters
    ###########################################

    parameter_values = [parameters[key] for key in parameters]
    combinations = list(product(*parameter_values))
    combinations = [dict(zip(parameters.keys(), combination)) for combination in combinations]
    total_time = wait_time * len(combinations)
    print(f'The scans will take {total_time} s = {total_time/60} min = {total_time/60/60} h')

    completed_runs = [[[] for i in range(35)] for j in range(35)]
    print('Checking existing files...')
    existing_files = 0
    new_combinations = []
    for combination in combinations:
        dir_to_check = output_directory_format.format(**combination)
        if not os.path.exists(dir_to_check):
            new_combinations = combinations
            continue
        filenames = [filename for filename in os.listdir(dir_to_check) if '.bin' in filename and outfile_prefix_format.format(combination) in filename]
        if len(filenames) == 0:
            new_combinations.append(combination)

    print(f'{len(combinations) - len(new_combinations)} files exist')
    combinations = new_combinations
    total_time = wait_time * len(combinations)
    print(f'New estimated time {total_time} s = {total_time/60} min = {total_time/60/60} h')

    # return
    # print('waiting for you to ramp up the HV')
    # time.sleep(30)

    info_format = 'Starring run with ' + ' '.join(f'{key} = {{{key}}},' for key in sorted(parameters.keys()))
    for combination in combinations:
        print(info_format.format(**combination))
        recfg = combination.copy()
        recfg['outdir'] = output_directory_format.format(**combination)
        refg['outfile_prefix'] = outfile_prefix_format.format(**combination)

        os.makedirs(recfg['outdir'], exist_ok=True)
        constellation.ASTEP.reconfigure(recfg)
        time.sleep(0.5)

        # Wait until ll states are back in the ORBIT state
        ctrl.await_state(SatelliteState.ORBIT)


        constellation.start(refg['outfile_prefix'])
        ctrl.await_state(SatelliteState.RUN)

        # Run for wait_time
        time.sleep(wait_time)

        # Stop the run and await ORBIT state of all satellites
        constellation.stop()
        ctrl.await_state(SatelliteState.ORBIT)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='ASTEP Driver Code')
    parser.add_argument('-c', '--config', required=True,
                    help='TOML configuration file describing the settings for the run')

    args = parser.parse_args()
    main(args)

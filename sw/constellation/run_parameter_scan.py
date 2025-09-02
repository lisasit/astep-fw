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
import toml

def parse_filename(filename):
    parts = filename.split('_')
    result_dict = {}
    i = 0
    current_key = ''
    while i <= len(parts) - 2:
        if not parts[i][0].isdigit():
            if current_key != '':
                current_key += '_'
            current_key += parts[i]
        else:
            result_dict[current_key] = parts[i]
            current_key = ''
        i += 1
    return result_dict

def main(args):
    cfg = load_config(args.config)
    group_name = "astropix"
    n_satellites = 1
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

    # parameters to iterate over
    parameters = {
        'injection_row' : [0, 8],
        'injection_col' : [10, 13],
        'threshold' : [1000],#[1100 + i*10 for i in range((1700-1100)//10 + 1)],
        'injection_voltage' : [400, 600, 800]
    }

    # time to stay at each parameter
    wait_time = 1

    # directory for the output files
    output_directory_format = '/media/teleuser/4TB/astropix/astep_testing_config/raw_data'

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
    for combination in tqdm(combinations):
        dir_to_check = output_directory_format.format(**combination)
        if not os.path.exists(dir_to_check):
            new_combinations = combinations
            continue
        prefix = outfile_prefix_format.format(**combination)
        filenames = [filename for filename in os.listdir(dir_to_check) if '.bin' in filename and prefix in filename]
        if len(filenames) == 0:
            new_combinations.append(combination)

    print(f'{len(combinations) - len(new_combinations)} files exist')
    combinations = new_combinations
    total_time = wait_time * len(combinations)
    print(f'New estimated time {total_time} s = {total_time/60} min = {total_time/60/60} h')

    # return
    # print('waiting for you to ramp up the HV')
    # time.sleep(30)

    info_format = 'Starting run with ' + ' '.join(f'{key} = {{{key}}},' for key in sorted(parameters.keys()))
    for combination in combinations:
        print(info_format.format(**combination))
        recfg = combination.copy()
        recfg['outdir'] = output_directory_format.format(**combination)
        recfg['outfile_prefix'] = outfile_prefix_format.format(**combination)
        print(recfg)

        os.makedirs(recfg['outdir'], exist_ok=True)
        constellation.ASTEP.reconfigure(recfg)
        time.sleep(0.5)
        cfg.update(recfg)


        # Wait until ll states are back in the ORBIT state
        ctrl.await_state(SatelliteState.ORBIT)

        time_config=time.strftime("%Y%m%d-%H%M%S")
        tomlpathout = cfg['outdir'] + '/AstroPix_Constellation_' + time_config + '.toml'
        with open(tomlpathout, 'w') as toml_file:
            # toml_file.write(f'[satellites.{self.name}]\n')
            toml.dump(cfg, toml_file)
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

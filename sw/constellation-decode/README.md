# What this is
This is a satellite for working with the Constellation software [documentation](https://constellation.pages.desy.de/index.html)

# How to install and run Constellation
1. For this satellite to work you need to install the python version of Constellation [instruction](https://constellation.pages.desy.de/operator_guide/get_started/install_from_pypi.html)
```<console>
pip install "ConstellationDAQ[cli,influx]"
```

2. You also may want to use the GUI controller called MissionControl and/or the GUI logger called Observatory. For this to work you need the C++ version of Constellation [instruction](https://constellation.pages.desy.de/operator_guide/get_started/install_from_flathub.html)
  Here is what to do in Ubuntu, for other OS please check out the link above
```<console>
sudo apt install flatpak
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub de.desy.constellation
```
Then you need to reboot the PC and after that you can run MissionControl and Observatory from the desktop environment or from the terminal like
```<console>
MissionControl
```

You can connect to the required group directly:
```<console>
MissionControl -g astropix
```
Otherwise you will be prompted to enter the group name when you start MissionControl.


# How to install and run this satellite

Nothing special is needed to install this satellite, just the normal installation of astep-fw

To run the satellite go to the `sw` directory and run
```
python constellation/__main__.py -g astropix
```
Here, `astropix` is the same group name that your MissionControl will connect to. You can also name the satellite by adding `-n MyFirstSatellite` to the line above.

You can change the log level by passing `-l [INFO, DEBUG, TRACE, WARNING, STATUS, CRITICAL]`

# Configuration file
A TOML configuration file is used to configure the satellite. Its options include some of the command line arguments of the `main.py` program and some others. The file structure is:
```<toml>
[satellites.ASTEP] # The block will be used for all satellites of type ASTEP
# could also be [satellites.ASTEP.MyFirstSatellite] for using only for the satellite with name MyFirstSatellite
parameter = value
```
The list of available configuration options:
| Parameter name | Type | Default value | What does it do | Analog in `main.py` arguments |
|-------------|------|---------------|-----------------|-------------------------------|
| `setup_type` | `"gecco"/"cmod"` | required parameter | Type of the setup | -- |
|`chip_version`| int | required parameter | Version of the chip | -- |
|`chip_configs` | list of string | required parameter | Names of the `.yml` files (without path and without `.yml` for configuring each row of chips | `-y` `--yaml` |
|`config_directory`| string | `./scripts/config` | Path to the directory with the config files from the previous line | -- |
|`outfile_prefix`| string | `""` | Adds a prefix to the output binary files with data | `-o` `--outputPrefix` |
|`outdir` | string | `"../AstroPix"` | Directory for saving output sata files. Will be created if it doesn't exist | -- |
|`use_shift_register` | bool | `False` | Use shift register (if True) or SPI (if False) for configuring the chip(s) | -- |
|`chips_per_row` | list of int (or int if each row has the same number of chips) | `[1]` | How many chips each row has | `-c-` `--chipsPerRow` | 
|`autoread` | bool | `True` | Enable the autoread features of the chip | negation of `-na` `--noAutoread` |
|`injection_layer` | int | `0` | Layer, where the injection should be enabled (will work only if the row and column are provided) | [0] of `-i` `--inject` |
|`injection_chip` | int | `0` | Chip, where the injection should be enabled (will work only if the row and column are provided) | [1] of `-i` `--inject` |
|`injection_row` | int | `None` | Row, where the injection should be enabled (will work only if the column is also provided) | [2] of `-i` `--inject` |
|`injection_col` | int | `None` | Column, where the injection should be enabled (will work only if the row is also provided) | [3] of `-i` `--inject` |
|`injection_voltage` | int [mV] | `None` | njection voltage in mV |`-v` `--vinj` |
|`injection_period` | int | `100` | Injection preiod (units TBD) | -- |
|`injection_clkdiv` | int | `300` | Injection clkdiv (unknown how it corresponds to frequency) | -- |
|`injection_initdelay` | int | `100` | Injection initial delay (units TBD) | -- |
|`injection_cycle` | int | `0` | Number of injection cycles (`0` means constant injection) | -- |
|`injection_pulsesperset` | int | `1` | Number of pulses per injection cycle (probably) | -- |
|`injection_onchip` | bool | `True` | If chip's internal circuitry is used for injection of a separate injection board | -- |
|`analog_layer` | int | `0`| Layer, where analog readout should be enabled | [0] of `-a`--analog` |
|`analog_chip` | int | `0`| Chip, where analog readout should be enabled | [1] of `-a`--analog` |
|`analog_col` | int | `0`| Column, where analog readout should be enabled (row is always 0) | [2] of `-a`--analog` |
|`threshold` | int [mV] | `1000` | Threshold for pixels with NMOS amplifiers. Is set from 0 and not from the baseline, so threshold of 100 set with `main.py` would be 1100 with this method | `-t` `--threshold` + 1000 mV |
|`threshold_pmos` | int [mV] | `1100` | Threshold for pixels with PMOS amplifiers. Is set from 0 and not from the baseline | -- |
|`spi_clkdiv` | int | `20` | SPI clock divider | -- |

You can choose which configuration file to use when initializing the satellite in MissionControl
|`nbytes_to_read_out` | int | `None` | How many bytes per FPGA readout to read (1 - 4098). If None, everything that is there is read out | `-r` `--readout`|

# Running automated parameter scans

`run_parameter_scan.py` allows to run automated parameter scans using a `ScriptableController` class from Constellation. Before running, modify the part of the `run_parameter_scan.py` script according to the goals of the scan. 
## Configuring the scan
The part where edits need to be made is marked with comments. Here it is with some instructions:
```<python>
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
```

- `parameters` dict contains values of all parameters that you want to run for. A run will be started for all possible combinations of the parameters. The keys in the dictionary should match the keys for the TOML configuration file defined above
- `wait_time` is the duration of each run in seconds
- `output_directory_format` is the format string specifying where to save the results of the scans. It can contain parameter names in curly brackets, which will then be substituted with the values of the parameters. For example, if `output_directory_format` is `my_scan/{injection_row}_{injection_col}`, the results for scans with injections into row 8 column 13 will be saved into `my_scan/8_13`
- `outfile_prefix_format` is the format string for the prefix for the output files. By default it will be constructed as `key1_value1_key2_value2 ...` with keys sorted alphabetically, but feel free to change it. For example, for a combination of parameters
  ```<python>
    {
        'injection_row' : 8,
        'injection_col' : 13,
        'injection_voltage' : 400,
        'threshold' : 1250
    }
  ```
  the files will have a prefix `injection_col_13_injection_row_8_injection_voltage_400_threshold_1250`

## Running the scan
In one terminal tab start the ASTEP satellite from the `sw` directory with 
```
python constellation/__main__.py -g astropix
```
In another tab start the parameter scan script from the `sw` directory with 
```
python constellation/run_parameter_scan.py -c /path/to/TOML/config
```
Here you need to provide a TOML config with all required parameter for the initial configuration. Only the parameters for the scan will be reconfigured during the run, the rest will stay as they were in this initial config file
  

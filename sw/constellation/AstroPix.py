"""
SPDX-FileCopyrightText: 2024 DESY and the Constellation authors
SPDX-License-Identifier: EUPL-1.2

Provides the class for the AstroPix example satellite
"""

# import random
# import time
# from typing import Any

# from constellation.core.cmdp import MetricsType
# from constellation.core.commandmanager import cscp_requestable
from constellation.core.configuration import Configuration

# from constellation.core.cscp import CSCPMessage
# from constellation.core.fsm import SatelliteState
# from constellation.core.monitoring import schedule_metric
from constellation.core.satellite import Satellite
# TODO imports are missing for sure
from astep import astepRun
# from core.nexysio import Nexysio
import numpy as np
import time
import os
import asyncio
# import binascii
# import pandas as pd
import json

class AstroPix(Satellite):
    """Satellite for controlling an AstroPix chip"""

    def do_initializing(self, config: Configuration):
        self.outfile_prefix = config.setdefault("outfile_prefix", "")
        self.outdir = config.setdefault("outdir", "../AstroPix")
        # Ensures output directory exists
        if os.path.exists(self.outdir) == False:
            os.mkdir(self.outdir)
        # should be gecco or cmod
        self.setup_type = config["setup_type"]
        self.use_shift_register = config.setdefault("use_shift_register", False)
        self.chips_per_row = config.setdefault("chips_per_row", [1])
        self.autoread = config.setdefault("autoread", True)

        self.chip_configs = config["chip_configs"]
        if len(self.chip_configs) > len(self.chips_per_row):
            self.chips_per_row = [self.chips_per_row[0]]*len(self.chip_configs)
            if len(self.chips_per_row) > 1:
                self.log.warning(f"Number of chips per row not provided for every layer - default to {self.chips_per_row[0]} for all {len(self.chip_configs)} layers")
        elif len(self.chip_configs) < len(self.chips_per_row):
            raise ValueError("You need to provide one yaml configuration file for every chipsPerRow argument")

        self.chip_version = config["chip_version"]
        self.injection_row = config.setdefault("injection_row", None)
        self.injection_col = config.setdefault("injection_col", None)
        self.injection_layer = config.setdefault("injection_layer", 0)
        self.injection_chip = config.setdefault("injection_chip", 0)
        self.inject = True if self.injection_row is not None and self.injection_col is not None else False
        self.injection_voltage = config.setdefault("injection_voltage", None)
        self.injection_period = config.setdefault("injection_period", 100)
        self.injection_clkdiv = config.setdefault("injection_clkdiv", 300)
        self.injection_initdelay = config.setdefault("injection_initdelay", 100)
        self.injection_cycle = config.setdefault("injection_cycle", 0)
        self.injection_pulsesperset = config.setdefault("injection_pulsesperset", 1)
        self.analog_layer = config.setdefault("analog_layer", 0)
        self.analog_chip = config.setdefault("analog_chip", 0)
        self.analog_col = config.setdefault("analog_col", 0)
        self.threshold = config.setdefault("threshold", None)
        self.injection_onchip = config.setdefault("injection_onchip", True)
        self.newfilter = config.setdefault("newfilter", False)
        self.warmup = config.setdefault("warmup", True)
        self.threshold_pmos = config.setdefault("threshold_pmos", 1100)
        if hasattr(self, 'astro'):
            self.astro.close_connection()
        self.astro = astepRun(chipversion=self.chip_version, SR=self.use_shift_register)
        if self.setup_type == "gecco":
            asyncio.run(self.astro.open_fpga(cmod=False, uart=False))
        elif setup_type == "cmod":
            asyncio.run(self.astro.open_fpga(cmod=True, uart=True))
        else:
            raise ValueError(f"Unknown setup type {self.setup_type}, should be 'gecco' or 'cmod'")

        self.log.debug(f'Configuration:\n {json.dumps(config.get_dict(), indent=1)}')

    def do_launching(self) -> str:
        asyncio.run(self.astro.setup_clocks())
        asyncio.run(self.astro.enable_spi())
        asyncio.run(self.astro.asic_init(yaml=self.chip_configs, chipsPerRow=self.chips_per_row))

        if self.setup_type == "gecco":
            asyncio.run(self.astro.init_voltages(dacvals = (8, [self.threshold_pmos/1000, 0, 1.1, 1, 0, 0, 1, self.threshold/1000])))

        if self.inject:
            asyncio.run(self.astro.enable_injection(layer=self.injection_layer, chip=self.injection_chip, row=self.injection_row, col=self.injection_col))
            asyncio.run(self.astro.enable_pixel(layer=self.injection_layer, chip=self.injection_chip, row=self.injection_row, col=self.injection_col))


            is_mV_injection = True
            if self.setup_type != "gecco":
                if self.injection_voltage is None:
                    # Priority to TOML config, defaults to yaml - already in vdac units
                    try:
                        self.injection_voltage = self.astro.boardDriver.getAsic(row=self.injection_layer).asic_config[f'config_{self.injection_chip}']['vdacs']['vinj'][1]
                        is_mV_injection = False
                    except (KeyError, IndexError):
                        self.log.error(f"Injection arguments layer={self.injection_layer}, chip={self.injection_chip} invalid. Cannot initialize injection")
                        self.inject = None

            if self.injection_voltage is not None:
                asyncio.run(self.astro.init_injection(layer=self.injection_layer, chip=self.injection_chip, inj_voltage=self.injection_voltage, onchip=self.injection_onchip, inj_period=self.injection_period, clkdiv=self.injection_clkdiv, initdelay=self.injection_initdelay, cycle=self.injection_cycle, pulseperset=self.injection_pulsesperset, is_mV=is_mV_injection))

        asyncio.run(self.astro.enable_analog(layer=self.analog_layer, chip=self.analog_chip, col=self.analog_chip))

        for layer in range(len(self.chip_configs)):
            asyncio.run(self.astro.asic_configure(layer))
            asyncio.run(self.astro.setup_readout(layer, autoread=not(self.autoread)))
        return f"AstroPix is configured"

    def do_reconfigure(self, partial_config) -> str:

        # parameters that are not possible to configure

        if "setup_type" in partial_config.get_keys():
            raise ValueError("Changing the setup type (gecco/cmod) is not possible, restart the satellite")

        if "use_shift_register" in partial_config.get_keys():
            raise ValueError("Changing the way of configuring the chip (SPI/shift register) is not possible, restart the satellite")

        if "chips_per_row" in partial_config.get_keys():
            raise ValueError("Changing the number of chips per row is not possible, restart the satellite")

        if "chip_version" in partial_config.get_keys():
            raise ValueError("Reconfiguring chip version is not possible")

        if "injection_onchip" in partial_config.get_keys():
            raise ValueError("Reconfiguring the source of injection (on chip/through the injection board) is not possible")

        # parameters that just need to be redefined without calling any functions

        if "outfile_prefix" in partial_config.get_keys():
            self.outfile_prefix = partial_config["outfile_prefix"]
            self.log.info(f"New prefix for the output files: {self.outfile_prefix}")

        if "outdir" in partial_config.get_keys():
            self.outdir = partial_config["outdir"]
            if os.path.exists(self.outdir) == False:
                os.mkdir(self.outdir)
            self.log.info(f"New directory for the output files: {self.outdir}")

        if "autoread" in partial_config.get_keys():
            self.autoread = partial_config["autoread"]
            self.log.info(f"Now {'reading' if self.autoread else 'not reading'} the chip data")

        # injection parameters

        if "injection_row" in partial_config.get_keys() or "injection_col" in partial_config.get_keys():
            if "injection_row" in partial_config.get_keys():
                self.injection_row = partial_config["injection_row"]
            if "injection_col" in partial_config.get_keys():
                self.injection_col = partial_config["injection_col"]
            new_inject = True if self.injection_row is not None and self.injection_col is not None else False
            self.log.info(f"New injection pixel is {new_inject} (old: {self.inject})")
            if self.inject is not None:
                self.astro.disable_pixel(self.inject[1], self.inject[0])
            self.inject = new_inject
            if self.inject is not None:
                self.astro.injection_row = self.injection_row
                self.astro.injection_col = self.injection_col
                self.astro.enable_pixel(self.inject[1], self.inject[0])
                self.astro.enable_injection(self.inject[1], self.inject[0])
            call_asic_init = True

        call_init_injection = False
        if "injection_voltage" in partial_config.get_keys():
            self.injection_voltage = partial_config["injection_voltage"]
            call_init_injection = True
            self.log.info(f"New injection voltage: {self.injection_voltage}")

        if "injection_period" in partial_config.get_keys():
            self.injection_period = partial_config["injection_period"]
            call_init_injection = True
            self.log.info(f"New injection period: {self.injection_period}")

        if "injection_clkdiv" in partial_config.get_keys():
            self.injection_clkdiv = partial_config["injection_clkdiv"]
            call_init_injection = True
            self.log.info(f"New injection clkdiv: {self.injection_clkdiv}")

        if "injection_initdelay" in partial_config.get_keys():
            self.injection_initdelay = partial_config["injection_initdelay"]
            call_init_injection = True
            self.log.info(f"New injection initdelay: {self.injection_initdelay}")

        if "injection_cycle" in partial_config.get_keys():
            self.injection_cycle = partial_config["injection_cycle"]
            call_init_injection = True
            self.log.info(f"New injection cycle: {self.injection_cycle}")

        if "injection_pulsesperset" in partial_config.get_keys():
            self.injection_pulsesperset = partial_config["injection_pulsesperset"]
            call_init_injection = True
            self.log.info(f"New injection pulsesperset: {self.injection_pulsesperset}")

        if call_init_injection:
            self.astro.init_injection(inj_voltage=self.injection_voltage, onchip=self.injection_onchip, inj_period=self.injection_period, clkdiv=self.injection_clkdiv, initdelay=self.injection_initdelay, cycle=self.injection_cycle, pulseperset=self.injection_pulsesperset)

        call_asic_init = False

        if "chip_configs" in partial_config.get_keys():
            self.chip_config = partial_config["chip_configs"]
            call_asic_init = True
            self.log.info(f"New config(s) for the chip(s): {self.chip_configs}")

        if "analog" in partial_config.get_keys():
            self.analog = partial_config["analog"]
            call_asic_init = True
            self.astro.asic.enable_ampout_col(self.analog)
            self.log.info(f"New analog output column: {self.analog}")





        call_init_voltages = False
        if "threshold" in partial_config.get_keys():
            self.threshold = partial_config["threshold"]
            call_init_voltages = True
            self.log.info(f"New threshold: {self.threshold}")

        if "threshold_pmos" in partial_config.get_keys():
            self.threshold_pmos = partial_config["threshold_pmos"]
            call_init_voltages = True
            self.log.info(f"New threshold_pmos: {self.threshold_pmos}")

        if call_init_voltages:
            self.astro.init_voltages(vthreshold=self.threshold, dacvals=(8, [self.threshold_pmos/1000, 0, 1.1, 1, 0, 0, 1, self.threshold/1000]))



        # if call_asic_init:
        self.log.info(f"Reinitializing the chip")
        self.astro.asic_update()
        self.finalize_config()
        return "AstroPix is reinitialized"

    def do_landing(self) -> str:
        return "No way to control anything from here, consider AstroPix landed"

    def do_starting(self, run_identifier: str):
        if self.inject is not None:
            asyncio.run(self.astro.start_injection())
            return f"Injections into pixel {self.inject} started"
        return f"Chip ready for taking data"

    def do_stopping(self):
        return "Nothing is done, AstroPix is unstoppable"

    def do_run(self, payload: any) -> str:
        while not self._state_thread_evt.is_set():
            if not self.autoread:
                continue
            buff, readout = asyncio.run(self.astro.get_readout())
            if readout: #if there is data contained in the readout stream
                self.bitfile.write(buff.to_bytes(2, byteorder='big'))
                self.bitfile.write(readout[:buff])
        return "Finished data acquisition"

    def finalize_config(self):
        # Save final configuration to output file
        time_config=time.strftime("%Y%m%d-%H%M%S")
        # ymlpathout = self.outdir +"/"+self.chip_config+"_"+time_config+".yml"
        # try:
        #     self.astro.write_conf_to_yaml(ymlpathout)
        # except FileNotFoundError:
        #     ypath = self.chip_config.split('/')
        #     ymlpathout = self.outdir + "/" + ypath[1] + "_" + time_config + ".yml"
        #     self.astro.write_conf_to_yaml(ymlpathout)
        # self.log.info(f'Configuration saved to file {ymlpathout}')

        # Prepare text files/logs
        fname = "" if not self.outfile_prefix else self.outfile_prefix + "_"
        bitpath = self.outdir + '/' + fname + time_config + '.bin'
        # textfiles are always saved so we open it up
        if hasattr(self, 'bitfile'):
            self.bitfile.close()
        self.bitfile = open(bitpath, 'wb')
        self.log.info(f'Bitfile with data: {bitpath}')

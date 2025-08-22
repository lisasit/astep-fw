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
import drivers.boards
# from core.nexysio import Nexysio
import numpy as np
import time
import os
import asyncio
# import binascii
# import pandas as pd
import json

class ASTEP(Satellite):
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

        pathdelim = os.path.sep
        self.config_directory = config.setdefault("config_directory", f"{os.getcwd()}{pathdelim}scripts{pathdelim}config")
        self.chip_configs = config["chip_configs"]
        self.chip_configs = [self.config_directory + pathdelim + config + '.yml' for config in self.chip_configs]
        if len(self.chip_configs) > len(self.chips_per_row):
            self.chips_per_row = [self.chips_per_row[0]]*len(self.chip_configs)
            if len(self.chips_per_row) > 1:
                self.log.warning(f"Number of chips per row not provided for every layer - default to {self.chips_per_row[0]} for all {len(self.chip_configs)} layers")
        elif len(self.chip_configs) < len(self.chips_per_row):
            raise ValueError("You need to provide one yaml configuration file for every chipsPerRow argument")

        self.nlayers = len(self.chip_configs)

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

        self.spi_clkdiv = config.setdefault("spi_clkdiv", 20)

        self.nbytes_to_read_out = config.setdefault("nbytes_to_read_out", None)


        self.astro = astepRun(chipversion=self.chip_version, SR=self.use_shift_register)
        if self.setup_type == "gecco":
            self.boardDriver = drivers.boards.getGeccoFTDIDriver()
            # asyncio.run(self.astro.open_fpga(cmod=False, uart=False))
        elif setup_type == "cmod":
            self.boardDriver = drivers.boards.getCMODUartDriver("COM6")
            # asyncio.run(self.astro.open_fpga(cmod=True, uart=True))
        else:
            raise ValueError(f"Unknown setup type {self.setup_type}, should be 'gecco' or 'cmod'")

        asyncio.run(self.boardDriver.open())
        fwid = asyncio.run(self.boardDriver.readFirmwareID())
        self.log.info(f'FW ID: {fwid}')

        self.log.debug(f'Configuration:\n {json.dumps(config.get_dict(), indent=1)}')

    def board_driver_print_status(self, time=0., buff=0):
        status = [asyncio.run(self.boardDriver.getLayerStatus(layer)) for layer in range(self.nlayers)]
        ctrl = [asyncio.run(self.boardDriver.getLayerControl(layer)) for layer in range(self.nlayers)]
        wrongl = [asyncio.run(self.boardDriver.getLayerWrongLength(layer)) for layer in range(self.nlayers)]
        log_string = "[{time:04.2} s] buff={0:04d}".format(buff, time=time)
        for i in range(self.nlayers):
            log_string += " {0} = {1:02b}-{2:06b}-{3:04d}".format(i, status[i], ctrl[i], wrongl[i])
        self.log.info(log_string)

    def board_driver_buffer_flush(self):
        """This method flushes data from SPI lanes then from FPGA buffer, and resets counters"""
        self.log.info("Flush chips before data collection")
        asyncio.run(self.boardDriver.holdLayers(hold=False, flush=True))
        for layer in range(self.nlayers):
            interrupt_counter = 0
            interrupt = asyncio.run(self.boardDriver.getLayerStatus(layer))
            while interrupt & 1 == 0 and interrupt_counter < 20:
                self.log.info("interrupt low")
                asyncio.run(self.boardDriver.layersSelectSPI(flush=True))
                asyncio.run(self.boardDriver.writeLayerBytes(layer = layer, bytes = [0x00] * 128, flush=True))
                asyncio.run(self.boardDriver.layersDeselectSPI(flush=True))
                # Let's not bother emptying the FPGA buffer, at this point it can overflow, and this data is trashed anyways since disableMISO in probably True
                interrupt_counter += 1
                interrupt = asyncio.run(self.boardDriver.getLayerStatus(layer))
        # Reassert hold to be safe
        asyncio.run(self.boardDriver.holdLayers(hold=True, flush=True))
        # Now all interrupts are high, empty FPGA buffer
        self.log.info("Flush FPGA buffer before data collection")
        asyncio.run(self.boardDriver.readoutReadBytes(4098))
        asyncio.run(self.boardDriver.resetLayerStatCounters(layer))

    def do_launching(self) -> str:
        asyncio.run(self.boardDriver.enableSensorClocks(flush = True))
        asyncio.run(self.boardDriver.layersConfigFPGATimestampFrequency(targetFrequencyHz = 1000000, flush = True))
        asyncio.run(self.boardDriver.layersConfigFPGATimestamp(enable = True, force = False, source_match_counter = True, source_external = False, flush = True))
        asyncio.run(self.boardDriver.configureLayerSPIDivider(self.spi_clkdiv, flush = True))
        asyncio.run(self.boardDriver.rfg.write_layers_cfg_nodata_continue(value=8, flush=True))

        if self.setup_type == "gecco":
            voltage_board = self.boardDriver.geccoGetVoltageBoard()
            self.log.debug(f'dacvalues = {voltage_board.dacvalues}')
            voltage_board.dacvalues = (8, [self.threshold_pmos/1000, 0, 1.1, 1, 0, 0, 1, self.threshold/1000])
            self.log.debug(f'dacvalues = {voltage_board.dacvalues}')
            voltage_board.vcal = 1.0
            voltage_board.vsupply = 2.7
            asyncio.run(voltage_board.update())
            self.log.info('Voltage board initialized')

        try:
            for layer, (nchips, config) in enumerate(zip(self.chips_per_row, self.chip_configs)):
                self.log.debug(f'Setting up layer {layer} chips per row {nchips} config {config}')
                self.boardDriver.setupASIC(version = self.chip_version, row = layer, chipsPerRow = nchips , configFile = config )
        except FileNotFoundError as e :
            self.log.error(f'Config File {config} was not found, pass the name of a config file from the scripts/config folder')
            raise e
        self.log.info(f'{len(self.boardDriver.asics)} ASIC driver(s) instanciated')

        if self.inject:
            try:
                self.boardDriver.asics[self.injection_layer].enable_inj_col(self.injection_chip, self.injection_col, inplace=False)
                self.boardDriver.asics[self.injection_layer].enable_inj_row(self.injection_chip, self.injection_row, inplace=False)
                self.boardDriver.asics[self.injection_layer].enable_pixel(chip=self.injection_chip, col=self.injection_col, row=self.injection_row, inplace=False)
                # Priority to command line, defaults to yaml - already in vdac units
                if self.injection_voltage is not None:
                    self.boardDriver.asics[self.injection_layer].asic_config[f"config_{self.injection_chip}"]["vdacs"]["vinj"][1] = int(self.injection_voltage/1000*1024/1.8)#1.8 V coded on 10 bits
                injector = self.boardDriver.getInjector()
                injector.setPattern(self.injection_period, self.injection_clkdiv, self.injection_initdelay, self.injection_cycle, self.injection_pulsesperset)#Default set of parameters
                asyncio.run(self.boardDriver.ioSetInjectionToChip(enable = True, flush = True)) # Routes injection pattern to on-chip injector
            except (KeyError, IndexError):
                self.log.error(f"Injection arguments layer={self.injection_layer}, chip={self.injection_chip} invalid. Cannot initialize injection.")
                self.inject = None

        self.boardDriver.asics[self.analog_layer].enable_ampout_col(self.analog_chip, self.analog_col, inplace=False)

        self.board_driver_print_status()

        for layer in range(self.nlayers):
            asyncio.run(self.boardDriver.zeroLayerWrongLength(layer, flush=True))

        asyncio.run(self.boardDriver.disableLayersReadout(flush=True))#Hold, disableMISO, disableAutoread, CS=inactive
        asyncio.run(self.boardDriver.resetLayersFull())#Toggle RST

        # Set chip IDs
        asyncio.run(self.boardDriver.layersSelectSPI(flush=True))#Set chipSelect
        for layer in range(self.nlayers):
            asyncio.run(self.boardDriver.asics[layer].writeSPIRoutingFrame(0))
            asyncio.run(self.boardDriver.layersDeselectSPI(flush=True))#Unset chipSelect

            for ichip in range(self.chips_per_row[layer]):
                asyncio.run(self.boardDriver.layersSelectSPI(flush=True))#Set chipSelect
                payload = self.boardDriver.asics[layer].createSPIConfigFrame(load=True, n_load=10, broadcast=False, targetChip=ichip)
                asyncio.run(self.boardDriver.asics[layer].writeSPI(payload))
                asyncio.run(self.boardDriver.layersDeselectSPI(flush=True))#Unset chipSelect
        # Flush old data
        #await boardDriver.layersSelectSPI(flush=True)#Set chipSelect
        self.board_driver_buffer_flush()#Exit with hold active and manages chipselect itself
        self.finalize_config()
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
            asyncio.run(self.boardDriver.getInjector().start())
            return f"Injections into layer {self.injection_layer}, chip {self.injection_chip}, row {self.injection_row} col {self.injection_col} started"
        asyncio.run(self.boardDriver.enableLayersReadout(range(self.nlayers), autoread=self.autoread, flush=True))
        return f"Chip ready for taking data"

    def do_stopping(self):
        return "Nothing is done, AstroPix is unstoppable"

    def do_run(self, payload: any) -> str:
        while not self._state_thread_evt.is_set():
            if not self.autoread:
                for layer in range(self.nlayers):
                    asyncio.run(self.boardDriver.writeLayerBytes(layer = layer, bytes = [0x00] * 255, flush=True))
            buffer_size = asyncio.run(self.boardDriver.readoutGetBufferSize())
            counts = self.nbytes_to_read_out if self.nbytes_to_read_out is not None else buffer_size
            readout = asyncio.run(self.boardDriver.readoutReadBytes(counts))
            if buffer_size > 0: #if there is data contained in the readout stream
                self.bitfile.write(buffer_size.to_bytes(2, byteorder='big'))
                self.bitfile.write(readout)
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

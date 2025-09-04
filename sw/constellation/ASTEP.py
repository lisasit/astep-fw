"""
SPDX-FileCopyrightText: 2024 DESY and the Constellation authors
SPDX-License-Identifier: EUPL-1.2

Provides the class for the AstroPix example satellite
"""

from constellation.core.configuration import Configuration

from constellation.core.satellite import Satellite
# TODO imports are missing for sure
from astep import astepRun
import drivers.boards
import numpy as np
import time
import os
import asyncio
import json
import asyncio
import toml
import yaml

class ASTEP(Satellite):
    """Satellite for controlling an AstroPix chip"""

    def async_run(func):
        def internal_func(self, *args, **kwargs):
            async def async_func(self, *args, **kwargs):
                await self.lock.acquire()
                await func(self, *args, **kwargs)
                self.lock.release()
            asyncio.run(async_func(self, *args, **kwargs))
        return internal_func

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

        self.config_directory = config.setdefault("config_directory", f"{os.getcwd()}{os.path.sep}scripts{os.path.sep}config")
        self.chip_configs = config["chip_configs"]

        self.find_chip_configs()

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
        self.threshold = config.setdefault("threshold", 1000)
        self.injection_onchip = config.setdefault("injection_onchip", True)
        self.threshold_pmos = config.setdefault("threshold_pmos", 1100)

        self.spi_clkdiv = config.setdefault("spi_clkdiv", 20)

        self.nbytes_to_read_out = config.setdefault("nbytes_to_read_out", None)

        self.lock = asyncio.Lock()
        self.log.debug(f'Configuration:\n {json.dumps(config.get_dict(), indent=1)}')
        self.open_board_driver()
        self.log.info(f'Board driver successfully opened')
        self.run_identifier = None

    def find_chip_configs(self):
        self.chip_config_paths = [self.config_directory + os.path.sep + config + '.yml' for config in self.chip_configs]
        if len(self.chip_config_paths) > len(self.chips_per_row):
            self.chips_per_row = [self.chips_per_row[0]]*len(self.chip_config_paths)
            if len(self.chips_per_row) > 1:
                self.log.warning(f"Number of chips per row not provided for every layer - default to {self.chips_per_row[0]} for all {len(self.chip_config_paths)} layers")
        elif len(self.chip_config_paths) < len(self.chips_per_row):
            raise ValueError("You need to provide one yaml configuration file for every chipsPerRow argument")

    @async_run
    async def open_board_driver(self):
        if not hasattr(self, 'boardDriver'):
            if self.setup_type == "gecco":
                self.boardDriver = drivers.boards.getGeccoFTDIDriver()
                # asyncio.run(self.astro.open_fpga(cmod=False, uart=False))
            elif setup_type == "cmod":
                self.boardDriver = drivers.boards.getCMODUartDriver("COM6")
                # asyncio.run(self.astro.open_fpga(cmod=True, uart=True))
            else:
                raise ValueError(f"Unknown setup type {self.setup_type}, should be 'gecco' or 'cmod'")

            await self.boardDriver.open()
        fwid = await self.boardDriver.readFirmwareID()
        self.log.info(f'FW ID: {fwid}')

    async def board_driver_print_status(self, time=0., buff=0):
        status = [await self.boardDriver.getLayerStatus(layer) for layer in range(self.nlayers)]
        ctrl = [await self.boardDriver.getLayerControl(layer) for layer in range(self.nlayers)]
        wrongl = [await self.boardDriver.getLayerWrongLength(layer) for layer in range(self.nlayers)]
        log_string = "[{time:04.2} s] buff={0:04d}".format(buff, time=time)
        for i in range(self.nlayers):
            log_string += " {0} = {1:02b}-{2:06b}-{3:04d}".format(i, status[i], ctrl[i], wrongl[i])
        self.log.info(log_string)

    async def board_driver_buffer_flush(self):
        """This method flushes data from SPI lanes then from FPGA buffer, and resets counters"""
        self.log.info("Flush chips before data collection")
        await self.boardDriver.holdLayers(hold=False, flush=True)
        for layer in range(self.nlayers):
            interrupt_counter = 0
            interrupt = await self.boardDriver.getLayerStatus(layer)
            while interrupt & 1 == 0 and interrupt_counter < 20:
                self.log.info("interrupt low")
                await self.boardDriver.layersSelectSPI(flush=True)
                await self.boardDriver.writeLayerBytes(layer = layer, bytes = [0x00] * 128, flush=True)
                await self.boardDriver.layersDeselectSPI(flush=True)
                # Let's not bother emptying the FPGA buffer, at this point it can overflow, and this data is trashed anyways since disableMISO in probably True
                interrupt_counter += 1
                interrupt = await self.boardDriver.getLayerStatus(layer)
        # Reassert hold to be safe
        await self.boardDriver.holdLayers(hold=True, flush=True)
        # Now all interrupts are high, empty FPGA buffer
        self.log.info("Flush FPGA buffer before data collection")
        await self.boardDriver.readoutReadBytes(4098)
        await self.boardDriver.resetLayerStatCounters(layer)

    async def setup_injection(self):
        if self.inject:
            try:
                self.boardDriver.asics[self.injection_layer].enable_inj_col(self.injection_chip, self.injection_col, inplace=False)
                self.boardDriver.asics[self.injection_layer].enable_inj_row(self.injection_chip, self.injection_row, inplace=False)
                self.boardDriver.asics[self.injection_layer].enable_pixel(chip=self.injection_chip, col=self.injection_col, row=self.injection_row, inplace=False)
                # Priority to command line, defaults to yaml - already in vdac units
                if self.injection_voltage is not None:
                    self.boardDriver.asics[self.injection_layer].asic_config[f"config_{self.injection_chip}"]["vdacs"]["vinj"][1] = int(self.injection_voltage/1000*1024/1.8)#1.8 V coded on 10 bits

                injector = self.boardDriver.getInjector()
                injector.period = self.injection_period
                injector.clkdiv = self.injection_clkdiv
                injector.initdelay = self.injection_initdelay
                injector.cycle = self.injection_cycle
                injector.pulsesperset = self.injection_pulsesperset
                await self.boardDriver.ioSetInjectionToChip(enable = True, flush = True) # Routes injection pattern to on-chip injector
            except (KeyError, IndexError):
                self.log.error(f"Injection arguments layer={self.injection_layer}, chip={self.injection_chip} invalid. Cannot initialize injection.")
                self.inject = False

    async def setup_voltages(self):
        if self.setup_type == "gecco":
            voltage_board = self.boardDriver.geccoGetVoltageBoard()
            self.log.debug(f'dacvalues = {voltage_board.dacvalues}')
            voltage_board.dacvalues = (8, [self.threshold_pmos/1000, 0, 1.1, 1, 0, 0, 1, self.threshold/1000])
            self.log.debug(f'dacvalues = {voltage_board.dacvalues}')
            voltage_board.vcal = .989
            voltage_board.vsupply = 2.7
            await voltage_board.update()
            self.log.info('Voltage board initialized')

    def setup_asics(self):
        try:
            for layer, (nchips, config) in enumerate(zip(self.chips_per_row, self.chip_config_paths)):
                self.log.debug(f'Setting up layer {layer} chips per row {nchips} config {config}')
                self.boardDriver.asics.clear()
                self.boardDriver.setupASIC(version = self.chip_version, row = layer, chipsPerRow = nchips , configFile = config )
        except FileNotFoundError as e :
            self.log.error(f'Config File {config} was not found, pass the name of a config file from the scripts/config folder')
            raise e
        self.log.info(f'{len(self.boardDriver.asics)} ASIC driver(s) instanciated')

    async def write_configuration(self):
        await self.board_driver_print_status()

        for layer in range(self.nlayers):
            await self.boardDriver.zeroLayerWrongLength(layer, flush=True)

        await self.boardDriver.disableLayersReadout(flush=True)#Hold, disableMISO, disableAutoread, CS=inactive
        await self.boardDriver.resetLayersFull()#Toggle RST

        if self.use_shift_register:
            for layer in range(self.nlayers):
                await self.boardDriver.asics[layer].writeConfigSR()
        else:
            # Set chip IDs
            await self.boardDriver.layersSelectSPI(flush=True)#Set chipSelect
            for layer in range(self.nlayers):
                await self.boardDriver.asics[layer].writeSPIRoutingFrame(0)
                await self.boardDriver.layersDeselectSPI(flush=True)#Unset chipSelect

                for ichip in range(self.chips_per_row[layer]):
                    await self.boardDriver.layersSelectSPI(flush=True)#Set chipSelect
                    payload = self.boardDriver.asics[layer].createSPIConfigFrame(load=True, n_load=10, broadcast=False, targetChip=ichip)
                    await self.boardDriver.asics[layer].writeSPI(payload)
                    await self.boardDriver.layersDeselectSPI(flush=True)#Unset chipSelect
        # Flush old data
        await self.board_driver_buffer_flush()#Exit with hold active and manages chipselect itself
        # from benchtest
        for layer in range(self.nlayers):
            await self.boardDriver.setLayerConfig(layer = layer , reset = False , autoread  = self.autoread, hold=False, flush = True )

    async def setup_clocks(self):
        await self.boardDriver.enableSensorClocks(flush = True)
        await self.boardDriver.layersConfigFPGATimestampFrequency(targetFrequencyHz = 1000000, flush = True)
        await self.boardDriver.layersConfigFPGATimestamp(enable = True, force = False, source_match_counter = True, source_external = False, flush = True)
        await self.boardDriver.configureLayerSPIDivider(self.spi_clkdiv, flush = True)
        await self.boardDriver.rfg.write_layers_cfg_nodata_continue(value=8, flush=True)

    @async_run
    async def do_launching(self) -> str:
        await self.setup_clocks()

        await self.setup_voltages()

        self.setup_asics()

        await self.setup_injection()

        self.boardDriver.asics[self.analog_layer].enable_ampout_col(self.analog_chip, self.analog_col, inplace=False)

        await self.write_configuration()
        return f"AstroPix is configured"

    @async_run
    async def do_reconfigure(self, partial_config) -> str:
        # When functions are called, the order is the same as in the do_launching method

        # parameters that are not possible to reconfigure

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

        # clock-related parameters
        call_setup_clocks = False
        if "spi_clkdiv" in partial_config.get_keys():
            self.spi_clkdiv = partial_config["spi_clkdiv"]
            call_setup_clocks = True

        if call_setup_clocks:
            await self.setup_clocks()

        # voltage board parameters

        call_setup_voltages = False
        if "threshold" in partial_config.get_keys():
            self.threshold = partial_config["threshold"]
            call_setup_voltages = True
            self.log.info(f"New threshold: {self.threshold}")

        if "threshold_pmos" in partial_config.get_keys():
            self.threshold_pmos = partial_config["threshold_pmos"]
            call_setup_voltages = True
            self.log.info(f"New threshold_pmos: {self.threshold_pmos}")

        if call_setup_voltages:
            await self.setup_voltages()

        # new chip configs
        call_setup_asics = False
        if "chip_configs" in partial_config.get_keys():
            self.chip_configs = partial_config["chip_configs"]
            self.log.info(f"New config(s) for the chip(s): {self.chip_configs}")
            call_setup_asics = True
        if "config_directory" in partial_config.get_keys():
            self.config_directory = partial_config["config_directory"]
            self.log.info(f"New directory with the configs: {self.config_directory}")
            call_setup_asics = True
        if call_setup_asics or call_setup_clocks:
            self.find_chip_configs()
            self.setup_asics()

        # injection parameters

        call_setup_injection = False
        if "injection_row" in partial_config.get_keys():
            self.injection_row = partial_config["injection_row"]
            call_setup_injection = True

        if "injection_col" in partial_config.get_keys():
            self.injection_col = partial_config["injection_col"]
            call_setup_injection = True

        if "injection_chip" in partial_config.get_keys():
            self.injection_chip = partial_config["injection_chip"]
            call_setup_injection = True

        if "injection_layer" in partial_config.get_keys():
            self.injection_layer = partial_config["injection_layer"]
            call_setup_injection = True

        if "injection_voltage" in partial_config.get_keys():
            self.injection_voltage = partial_config["injection_voltage"]
            call_setup_injection = True
            self.log.info(f"New injection voltage: {self.injection_voltage}")

        if "injection_period" in partial_config.get_keys():
            self.injection_period = partial_config["injection_period"]
            call_setup_injection = True
            self.log.info(f"New injection period: {self.injection_period}")

        if "injection_clkdiv" in partial_config.get_keys():
            self.injection_clkdiv = partial_config["injection_clkdiv"]
            call_setup_injection = True
            self.log.info(f"New injection clkdiv: {self.injection_clkdiv}")

        if "injection_initdelay" in partial_config.get_keys():
            self.injection_initdelay = partial_config["injection_initdelay"]
            call_setup_injection = True
            self.log.info(f"New injection initdelay: {self.injection_initdelay}")

        if "injection_cycle" in partial_config.get_keys():
            self.injection_cycle = partial_config["injection_cycle"]
            call_setup_injection = True
            self.log.info(f"New injection cycle: {self.injection_cycle}")

        if "injection_pulsesperset" in partial_config.get_keys():
            self.injection_pulsesperset = partial_config["injection_pulsesperset"]
            call_setup_injection = True
            self.log.info(f"New injection pulsesperset: {self.injection_pulsesperset}")

        if call_setup_injection or call_setup_clocks:
            # if injection was going on previously and the chip was not reconfigured, we need to disable the pixel that we were injecting into
            if self.inject and not call_setup_asics:
                self.boardDriver.asics[self.injection_layer].disable_pixel(row=self.injection_row, col=self.injection_col, chip=self.injection_chip)
            self.inject = True if self.injection_row is not None and self.injection_col is not None else False
            self.log.info(f"Injection into layer {self.injection_layer}, chip {self.injection_chip}, row {self.injection_row}, col {self.injection_col}")
            await self.setup_injection()

        # analog output

        call_enable_ampout = False
        if "analog_layer" in partial_config.get_keys():
            self.analog_layer = partial_config["analog_layer"]
            call_enable_ampout = True

        if "analog_chip" in partial_config.get_keys():
            self.analog_chip = partial_config["analog_chip"]
            call_enable_ampout = True

        if "analog_col" in partial_config.get_keys():
            self.analog_col = partial_config["analog_col"]
            call_enable_ampout = True

        if call_enable_ampout or call_setup_clocks:
            self.boardDriver.asics[self.analog_layer].enable_ampout_col(self.analog_chip, self.analog_col, inplace=False)
            self.log.info(f"New analog output layer {self.analog_layer}, chip {self.analog_chip}, column {self.analog_col}")

        # if call_asic_init:
        self.log.info(f"Reinitializing the chip")
        await self.write_configuration()
        return "AstroPix is reinitialized"

    def do_landing(self) -> str:
        return "No way to control anything from here, consider AstroPix landed"

    @async_run
    async def do_starting(self, run_identifier: str):
        self.run_identifier = run_identifier
        self.create_files_for_run()
        if self.inject:
            await self.boardDriver.getInjector().start()
            return f"Injections into layer {self.injection_layer}, chip {self.injection_chip}, row {self.injection_row} col {self.injection_col} started"
        await self.boardDriver.enableLayersReadout(range(self.nlayers), autoread=self.autoread, flush=True)
        return f"Chip ready for taking data"

    @async_run
    async def do_stopping(self):
        if self.inject:
            await self.boardDriver.getInjector().stop()
            return "Injections stopped"
        return "Nothing is done, AstroPix is unstoppable"

    @async_run
    async def do_run(self, payload: any) -> str:
        while not self._state_thread_evt.is_set():
            if not self.autoread:
                for layer in range(self.nlayers):
                    await self.boardDriver.writeLayerBytes(layer = layer, bytes = [0x00] * 255, flush=True)
            buffer_size = await self.boardDriver.readoutGetBufferSize()
            self.log.debug(f'buffer size = {buffer_size}')
            if buffer_size > 8000:
                self.log.error(f"Buffer size too big ({buffer_size}), probably something went wrong with the readout")
                continue
            counts = self.nbytes_to_read_out if self.nbytes_to_read_out is not None else buffer_size
            readout = await self.boardDriver.readoutReadBytes(counts)
            if buffer_size > 0: #if there is data contained in the readout stream
                self.bitfile.write(buffer_size.to_bytes(2, byteorder='little'))
                self.bitfile.write(readout)
        return "Finished data acquisition"

    def create_files_for_run(self):
        # Save final configuration to output file

        for layer in range(self.nlayers):
            filename = f"{self.outdir}/chip_config_layer{layer}_{self.run_identifier}.yml"
            asic = self.boardDriver.asics[layer]
            dicttofile ={asic.chip:
                {
                    "telescope": {"nchips": asic.num_chips},
                    "geometry": {"cols": asic.num_cols, "rows": asic.num_rows}
                }
            }

            for chip in range(asic.num_chips):
                dicttofile[asic.chip][f'config_{chip}'] = asic.asic_config[f'config_{chip}']

            with open(f"{filename}", "w", encoding="utf-8") as stream:
                try:
                    yaml.dump(dicttofile, stream, default_flow_style=False, sort_keys=False)

                except yaml.YAMLError as exc:
                    logger.error(exc)

        # Prepare text files/logs
        fname = "" if not self.outfile_prefix else self.outfile_prefix + "_"
        bitpath = self.outdir + '/' + fname + self.run_identifier + '.bin'
        # textfiles are always saved so we open it up
        if hasattr(self, 'bitfile'):
            self.bitfile.close()
        self.bitfile = open(bitpath, 'wb')
        self.log.info(f'Bitfile with data: {bitpath}')

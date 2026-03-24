"""
SPDX-FileCopyrightText: 2024 DESY and the Constellation authors
SPDX-License-Identifier: EUPL-1.2

Provides the class for the AstroPix example satellite
"""

import asyncio
import json
import os
import time

import numpy as np
import toml
import yaml

from constellation.core.configuration import Configuration
from constellation.core.satellite import Satellite
from constellation.core.message.cscp1 import SatelliteState
from constellation.core.monitoring import schedule_metric

import drivers.boards


class ASTEP(Satellite):
    """Satellite for controlling an AstroPix chip"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.buffer_size_queue = []

    def async_run(func):
        def internal_func(self, *args, **kwargs):
            async def async_func(self, *args, **kwargs):
                await self.lock.acquire()
                await func(self, *args, **kwargs)
                self.lock.release()

            asyncio.run(async_func(self, *args, **kwargs))

        return internal_func

    def do_initializing(self, config: Configuration):
        self.outfile_prefix = config.get("outfile_prefix", "")
        self.outdir = config.get("outdir", "../AstroPix")
        # Ensures output directory exists
        if os.path.exists(self.outdir) == False:
            os.makedirs(self.outdir)
        # should be gecco or cmod
        self.setup_type = config.get("setup_type")
        self.use_shift_register = config.get("use_shift_register", False)
        self.chips_per_row = config.get("chips_per_row", [1])
        self.autoread = config.get("autoread", True)

        self.config_directory = config.get(
            "config_directory", f"{os.getcwd()}{os.path.sep}scripts{os.path.sep}config"
        )
        self.chip_configs = config.get("chip_configs")

        self.find_chip_configs()

        self.nlayers = len(self.chip_configs)

        self.chip_version = config.get("chip_version")
        if "injection_row" in config:
            self.injection_row = config.get("injection_row")
            if isinstance(self.injection_row, int):
                self.injection_row = [self.injection_row]
        else:
            self.injection_row = None

        if "injection_col" in config:
            self.injection_col = config.get("injection_col")
            if isinstance(self.injection_col, int):
                self.injection_col = [self.injection_col]
        else:
            self.injection_col = None

        self.injection_layer = config.get("injection_layer", 0)
        self.injection_chip = config.get("injection_chip", 0)
        self.inject = (
            True
            if self.injection_row is not None and self.injection_col is not None
            else False
        )
        if "injection_voltage" in config:
            self.injection_voltage = config.get("injection_voltage")
        else:
            self.injection_voltage = None
        self.injection_period = config.get("injection_period", 100)
        self.injection_clkdiv = config.get("injection_clkdiv", 300)
        self.injection_initdelay = config.get("injection_initdelay", 100)
        self.injection_cycle = config.get("injection_cycle", 0)
        self.injection_pulsesperset = config.get("injection_pulsesperset", 1)
        self.analog_layer = config.get("analog_layer", 0)
        self.analog_chip = config.get("analog_chip", 0)
        self.analog_col = config.get("analog_col", 0)
        self.threshold = config.get("threshold", 1000)
        self.injection_onchip = config.get("injection_onchip", True)
        self.threshold_pmos = config.get("threshold_pmos", 1100)
        self.vminuspix = config.get("vminuspix", 1000)

        self.spi_freq = config.get("spi_freq", 1e6)
        if "spi_clkdiv" in config:
            self.spi_clkdiv = config.get("spi_clkdiv")
            self.log.info(f'SPI clkdiv overrides spi frequency. It ({self.spi_clkdiv}) will be used to set the spi clock divider')
            self.spi_freq = None

        if "nbytes_to_read_out" in config:
            self.nbytes_to_read_out = config.get("nbytes_to_read_out")
        else:
            self.nbytes_to_read_out = None

        self.use_tlu = config.get("use_tlu", False)
        self.fpga_timestamp_size = config.get("fpga_timestamp_size", 1) # 0 : 16, 1 : 32, 2 : 48, 3: 64

        self.lock = asyncio.Lock()
        # self.log.debug(f"Configuration:\n {json.dumps(config.get_dict(), indent=1)}")
        self.open_board_driver()
        self.log.info(f"Board driver successfully opened")
        self.run_identifier = None

    def get_fpga_ts_size_bits(self):
        if self.fpga_timestamp_size == 0:
            return 16
        if self.fpga_timestamp_size == 1:
            return 32
        if self.fpga_timestamp_size == 2:
            return 48
        if self.fpga_timestamp_size == 3:
            return 64
        return None

    def find_chip_configs(self):
        self.chip_config_paths = [
            self.config_directory + os.path.sep + config + ".yml"
            for config in self.chip_configs
        ]
        if len(self.chip_config_paths) > len(self.chips_per_row):
            self.chips_per_row = [self.chips_per_row[0]] * len(self.chip_config_paths)
            if len(self.chips_per_row) > 1:
                self.log.warning(
                    f"Number of chips per row not provided for every layer - default to {self.chips_per_row[0]} for all {len(self.chip_config_paths)} layers"
                )
        elif len(self.chip_config_paths) < len(self.chips_per_row):
            raise ValueError(
                "You need to provide one yaml configuration file for every chipsPerRow argument"
            )

    @async_run
    async def open_board_driver(self):
        if not hasattr(self, "boardDriver"):
            if self.setup_type == "gecco":
                self.boardDriver = drivers.boards.getGeccoFTDIDriver()
                # asyncio.run(self.astro.open_fpga(cmod=False, uart=False))
            elif setup_type == "cmod":
                self.boardDriver = drivers.boards.getCMODUartDriver("COM6")
                # asyncio.run(self.astro.open_fpga(cmod=True, uart=True))
            else:
                raise ValueError(
                    f"Unknown setup type {self.setup_type}, should be 'gecco' or 'cmod'"
                )

            await self.boardDriver.open()
        fwid = await self.boardDriver.readFirmwareID()
        self.log.info(f"FW ID: {fwid}")

    async def board_driver_print_status(self, time=0.0, buff=0):
        status = [
            await self.boardDriver.getLayerStatus(layer)
            for layer in range(self.nlayers)
        ]
        ctrl = [
            await self.boardDriver.getLayerControl(layer)
            for layer in range(self.nlayers)
        ]
        wrongl = [
            await self.boardDriver.getLayerWrongLength(layer)
            for layer in range(self.nlayers)
        ]
        log_string = "[{time:04.2} s] buff={0:04d}".format(buff, time=time)
        for i in range(self.nlayers):
            log_string += " {0} = {1:02b}-{2:06b}-{3:04d}".format(
                i, status[i], ctrl[i], wrongl[i]
            )
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
                await self.boardDriver.writeSPIBytesToLane(
                    lane=layer, bytes=[0x00] * 128
                )
                await self.boardDriver.layersDeselectSPI(flush=True)
                # Let's not bother emptying the FPGA buffer, at this point it can overflow, and this data is trashed anyways since disableMISO in probably True
                interrupt_counter += 1
                interrupt = await self.boardDriver.getLayerStatus(layer)
        # Reassert hold to be safe
        await self.boardDriver.holdLayers(hold=True, flush=True)
        # Now all interrupts are high, empty FPGA buffer

        buff = await self.boardDriver.readoutGetBufferSize()
        self.log.info(f"Flush FPGA buffer before data collection: reading {buff} bytes from the buffer")
        await self.boardDriver.readoutReadBytes(buff)
        await self.boardDriver.resetLayerStatCounters(layer)

    async def setup_injection(self):
        if self.inject:
            try:
                for col in self.injection_col:
                    self.log.info(f'Enabling injection column {col}')
                    self.boardDriver.asics[self.injection_layer].enable_inj_col(
                        self.injection_chip, col, inplace=False
                    )
                for row in self.injection_row:
                    self.log.info(f'Enabling injection row {row}')
                    self.boardDriver.asics[self.injection_layer].enable_inj_row(
                        self.injection_chip, row, inplace=False
                    )
                for col in self.injection_col:
                    for row in self.injection_row:
                        self.boardDriver.asics[self.injection_layer].enable_pixel(
                            chip=self.injection_chip,
                            col=col,
                            row=row,
                            inplace=False,
                        )
                # Priority to command line, defaults to yaml - already in vdac units
                if self.injection_voltage is not None:
                    self.boardDriver.asics[self.injection_layer].asic_config[
                        f"config_{self.injection_chip}"
                    ]["vdacs"]["vinj"][1] = int(
                        self.injection_voltage / 1000 * 1024 / 1.8
                    )  # 1.8 V coded on 10 bits

                injector = self.boardDriver.geccoGetInjectionBoard()
                injector.period = self.injection_period
                injector.clkdiv = self.injection_clkdiv
                injector.initdelay = self.injection_initdelay
                injector.cycle = self.injection_cycle
                injector.pulsesperset = self.injection_pulsesperset
                await self.boardDriver.ioSetInjectionToChip(
                    enable=True, flush=True
                )  # Routes injection pattern to on-chip injector
            except (KeyError, IndexError):
                self.log.error(
                    f"Injection arguments layer={self.injection_layer}, chip={self.injection_chip} invalid. Cannot initialize injection."
                )
                self.inject = False

    async def setup_voltages(self):
        if self.setup_type == "gecco":
            voltage_board = self.boardDriver.geccoGetVoltageBoard()
            self.log.debug(f"dacvalues before setting them = {voltage_board.dacvalues}")
            voltage_board.dacvalues = (
                8,
                [self.threshold_pmos / 1000, 0, 1.1, 1, 0, 0, self.vminuspix / 1000, self.threshold / 1000],
            )
            self.log.info(f"dacvalues after setting them = {voltage_board.dacvalues}")
            voltage_board.vcal = 0.989
            voltage_board.vsupply = 2.7
            await voltage_board.update()
            self.log.info("Voltage board initialized")

    def setup_asics(self):
        try:
            for layer, (nchips, config) in enumerate(
                zip(self.chips_per_row, self.chip_config_paths)
            ):
                self.log.debug(
                    f"Setting up layer {layer} chips per row {nchips} config {config}"
                )
                self.boardDriver.asics.clear()
                self.boardDriver.setupASIC(
                    version=self.chip_version,
                    lane=layer,
                    chipsPerLane=nchips,
                    configFile=config,
                )
        except FileNotFoundError as e:
            self.log.error(
                f"Config File {config} was not found, pass the name of a config file from the scripts/config folder"
            )
            raise e
        self.log.info(f"{len(self.boardDriver.asics)} ASIC driver(s) instanciated")

    async def write_configuration(self):
        await self.board_driver_print_status()

        for layer in range(self.nlayers):
            await self.boardDriver.zeroLayerWrongLength(layer, flush=True)

        await self.boardDriver.disableLayersReadout(
            flush=True
        )  # Hold, disableMISO, disableAutoread, CS=inactive
        await self.boardDriver.resetLayersFull()  # Toggle RST

        if self.use_shift_register:
            for layer in range(self.nlayers):
                await self.boardDriver.writeSRAsicConfig(lane=layer, ckdiv=16)
        else:
            # Set chip IDs
            await self.boardDriver.layersSelectSPI(flush=True)  # Set chipSelect
            for layer in range(self.nlayers):
                await self.boardDriver.writeRoutingFrame(lane=0)
                await self.boardDriver.layersDeselectSPI(flush=True)  # Unset chipSelect

                for ichip in range(self.chips_per_row[layer]):
                    await self.boardDriver.layersSelectSPI(flush=True)
                    await self.boardDriver.writeSPIAsicConfig(
                        lane=layer,
                        load=True,
                        n_load=10,
                        broadcast=False,
                        targetChip=ichip,
                    )  # Set chipSelect
                    # payload = self.boardDriver.asics[layer].createSPIConfigFrame(
                    #    load=True, n_load=10, broadcast=False, targetChip=ichip
                    # )
                    # await self.boardDriver.asics[layer].writeSPI(payload)
                    await self.boardDriver.layersDeselectSPI(
                        flush=True
                    )  # Unset chipSelect
        # Flush old data
        await (
            self.board_driver_buffer_flush()
        )  # Exit with hold active and manages chipselect itself
        # from benchtest
        for layer in range(self.nlayers):
            await self.boardDriver.setLayerConfig(
                layer=layer, reset=False, autoread=self.autoread, hold=False, flush=True, disableMISO=False
            )

    async def setup_clocks(self):
        self.log.info("Setting the chip version to v4 (even for v3) to change the frequency of the tot clock")
        await self.boardDriver.rfg.write_chip_version(
            value=4, flush=True
        )
        self.log.info(f"Setting up clocks, use_tlu = {self.use_tlu}, fpga_ts size = {self.get_fpga_ts_size_bits()} bits")
        await self.boardDriver.setExternalClock(enable=self.use_tlu)
        tc = await self.boardDriver.rfg.read_layers_fpga_timestamp_ctrl()
        self.log.info(f'Timestamp config before configuring the timestamp: {tc}')
        await self.boardDriver.enableSensorClocks(flush=True)
        await self.boardDriver.layersConfigFPGATimestampFrequency(
            targetFrequencyHz=1000000, flush=True
        )
        await self.boardDriver.layersConfigFPGATimestamp(
            enable=True,
            use_divider=False,
            use_tlu=self.use_tlu,
            timestamp_size=self.fpga_timestamp_size,
            flush=True,
        )
        tc = await self.boardDriver.rfg.read_layers_fpga_timestamp_ctrl()
        self.log.info(f'Timestamp config after configuring the timestamp: {tc}')
        await self.boardDriver.layersConfigFPGATimestamp(
            enable=True,
            use_divider=False,
            use_tlu=self.use_tlu,
            timestamp_size=self.fpga_timestamp_size,
            flush=True,
        )
        tc = await self.boardDriver.rfg.read_layers_fpga_timestamp_ctrl()
        self.log.info(f'Timestamp config after configuring the timestamp again: {tc}')
        currentTS = await self.boardDriver.rfg.read_layers_fpga_timestamp_counter()
        self.log.info(f'FPGA TS = {currentTS}')
        #await self.boardDriver.configureLayerSPIDivider(self.spi_clkdiv, flush=True)
        if self.spi_freq is None:
            self.log.info(f'Setting SPI clock divider to {self.spi_clkdiv}')
            await self.boardDriver.configureLayerSPIDivider(self.spi_clkdiv, flush=True)
        else:
            self.log.info(f'Setting SPI frequency divider to {self.spi_freq}')
            await self.boardDriver.configureLayerSPIFrequency(self.spi_freq, flush=True)

        await self.boardDriver.rfg.write_layers_cfg_nodata_continue(value=8, flush=True)

    @async_run
    async def do_launching(self) -> str:
        await self.setup_clocks()

        await self.setup_voltages()

        self.setup_asics()

        await self.setup_injection()

        self.boardDriver.asics[self.analog_layer].enable_ampout_col(
            self.analog_chip, self.analog_col, inplace=False
        )

        await self.write_configuration()
        return f"AstroPix is configured"

    @async_run
    async def do_reconfigure(self, partial_config) -> str:
        # When functions are called, the order is the same as in the do_launching method

        # parameters that are not possible to reconfigure

        if "setup_type" in partial_config.get_keys():
            raise ValueError(
                "Changing the setup type (gecco/cmod) is not possible, restart the satellite"
            )

        if "use_shift_register" in partial_config.get_keys():
            raise ValueError(
                "Changing the way of configuring the chip (SPI/shift register) is not possible, restart the satellite"
            )

        if "chips_per_row" in partial_config.get_keys():
            raise ValueError(
                "Changing the number of chips per row is not possible, restart the satellite"
            )

        if "chip_version" in partial_config.get_keys():
            raise ValueError("Reconfiguring chip version is not possible")

        if "injection_onchip" in partial_config.get_keys():
            raise ValueError(
                "Reconfiguring the source of injection (on chip/through the injection board) is not possible"
            )

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
            self.log.info(f"Now {'using' if self.autoread else 'not using'} autoread")

        # clock-related parameters
        call_setup_clocks = False
        if "spi_clkdiv" in partial_config.get_keys():
            self.spi_clkdiv = partial_config["spi_clkdiv"]
            call_setup_clocks = True

        if "spi_freq" in partial_config.get_keys():
            self.spi_freq = partial_config["spi_freq"]
            call_setup_clocks = True

        if "use_tlu" in partial_config.get_keys():
            self.use_tlu = partial_config["use_tlu"]
            call_setup_clocks = True

        if "fpga_timestamp_size" in partial_config.get_keys():
            self.fpga_timestamp_size = partial_config["fpga_timestamp_size"]
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
        prev_injection_row = self.injection_row.copy()
        prev_injection_col = self.injection_col.copy()
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

        if call_setup_injection or call_setup_clocks or call_setup_asics:
            # if injection was going on previously and the chip was not reconfigured, we need to disable the pixel that we were injecting into
            if self.inject and not call_setup_asics:
                for col in prev_injection_col:
                    for row in prev_injection_row:
                        self.boardDriver.asics[self.injection_layer].disable_pixel(
                            row=row,
                            col=col,
                            chip=self.injection_chip,
                        )
            self.inject = (
                True
                if self.injection_row is not None and self.injection_col is not None
                else False
            )
            self.log.info(
                f"Injection into layer {self.injection_layer}, chip {self.injection_chip}, row {self.injection_row}, col {self.injection_col}"
            )
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

        if call_enable_ampout or call_setup_clocks or call_setup_asics:
            self.boardDriver.asics[self.analog_layer].enable_ampout_col(
                self.analog_chip, self.analog_col, inplace=False
            )
            self.log.info(
                f"New analog output layer {self.analog_layer}, chip {self.analog_chip}, column {self.analog_col}"
            )

        self.log.info(f"Reinitializing the chip")
        await self.write_configuration()
        return "AstroPix is reinitialized"

    def do_landing(self) -> str:
        #await self.print_stats()
        return "No way to control anything from here, consider AstroPix landed"

    @async_run
    async def do_starting(self, run_identifier: str):
        self.run_identifier = run_identifier
        self.buffer_size_queue.clear()
        self.create_files_for_run()
        if self.inject:
            await self.boardDriver.geccoGetInjectionBoard().start()
            return f"Injections into layer {self.injection_layer}, chip {self.injection_chip}, row {self.injection_row} col {self.injection_col} started"
        #await self.boardDriver.enableLayersReadout(
        #    range(self.nlayers), autoread=self.autoread, flush=True
        #)
        return f"Chip ready for taking data"

    @async_run
    async def do_stopping(self):
        if self.inject:
            await self.boardDriver.geccoGetInjectionBoard().stop()
            return "Injections stopped"
        return "Nothing is done, AstroPix is unstoppable"

    async def print_stats(self):
        for i in range(self.nlayers):
            idle = await self.boardDriver.getLayerStatIDLECounter(i)
            frames = await self.boardDriver.getLayerStatFRAMECounter(i)
            errors = await self.boardDriver.getLayerWrongLength(i)
            self.log.info(f"Layer {i} stats: {idle} idle bytes, {frames} frames, {errors} errors")

    @schedule_metric("Byte", 5)
    def BUFFER_SIZE(self):
        if self.fsm.current_state_value == SatelliteState.RUN:
            if self.buffer_size_queue:
                mean_buffer_size = int(np.mean(self.buffer_size_queue))
                self.buffer_size_queue.clear()
                return mean_buffer_size
        return None

    #@schedule_metric("", MetricsType.LAST_VALUE, 5)
    #@async_run
    #async def IDLE_COUNT(self):
    #    if self.fsm.current_state_value == SatelliteState.RUN:
    #        return await self.boardDriver.getLayerStatIDLECounter(0)
    #    return None

    #@schedule_metric("", MetricsType.LAST_VALUE, 5)
    #def FRAME_COUNT(self):
    #    if self.fsm.current_state_value == SatelliteState.RUN:
    #        return asyncio.run(self.boardDriver.getLayerStatFRAMECounter(0))
    #    return None

    #@schedule_metric("", MetricsType.LAST_VALUE, 5)
    #def WRONG_LENGTH_COUNT(self):
    #    if self.fsm.current_state_value == SatelliteState.RUN:
    #        return asyncio.run(self.boardDriver.getLayerWrongLength(0))
    #    return None


    @async_run
    async def do_run(self, payload: any) -> str:
        ireadout = 0
        while not self._state_thread_evt.is_set():
            if not self.autoread:
                for layer in range(self.nlayers):
                    await self.boardDriver.writeSPIBytesToLane(
                        lane=layer, bytes=[0x00] * 255
                    )
            buffer_size = await self.boardDriver.readoutGetBufferSize()
            if buffer_size > 17000:
                self.log.error(
                    f"Buffer size too big ({buffer_size}), probably something went wrong with the readout"
                )
                continue
            counts = (
                self.nbytes_to_read_out
                if self.nbytes_to_read_out is not None
                else buffer_size
            )
            readout = await self.boardDriver.readoutReadBytes(counts)
            if buffer_size > 0:  # if there is data contained in the readout stream
                self.buffer_size_queue.append(buffer_size)
                self.bitfile.write(buffer_size.to_bytes(2, byteorder="little"))
                self.bitfile.write(readout)
                ireadout += 1
        return "Finished data acquisition"

    def create_files_for_run(self):
        # Save final configuration to output file

        for layer in range(self.nlayers):
            filename = (
                f"{self.outdir}/chip_config_layer{layer}_{self.run_identifier}.yml"
            )
            asic = self.boardDriver.asics[layer]
            dicttofile = {
                asic.chip: {
                    "telescope": {"nchips": asic.num_chips},
                    "geometry": {"cols": asic.num_cols, "rows": asic.num_rows},
                }
            }

            for chip in range(asic.num_chips):
                dicttofile[asic.chip][f"config_{chip}"] = asic.asic_config[
                    f"config_{chip}"
                ]

            with open(f"{filename}", "w", encoding="utf-8") as stream:
                try:
                    yaml.dump(
                        dicttofile, stream, default_flow_style=False, sort_keys=False
                    )

                except yaml.YAMLError as exc:
                    logger.error(exc)

        # Prepare text files/logs
        fname = "" if not self.outfile_prefix else self.outfile_prefix + "_"
        bitpath = self.outdir + "/" + fname + self.run_identifier + ".bin"
        # textfiles are always saved so we open it up
        if hasattr(self, "bitfile"):
            self.bitfile.close()
        self.bitfile = open(bitpath, "wb")
        self.log.info(f"Bitfile with data: {bitpath}")

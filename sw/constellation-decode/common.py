from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field

import numpy as np


class MatcherStrategy(Enum):
    ALL = 0
    CLOSEST = 1


@dataclass
class DecoderSettingsBase:
    # Number of layers
    nlayers: int
    # Number of chips per layer
    nchips_per_layer: int
    # Length of the FPGA timestamp in bytes
    fpga_ts_length: int
    # FPGA timestamp clock frequency in Hz
    fpga_ts_clock_freq: float
    # Maximum FPGA timestamp difference between halfhits for filtering. If None, filtering is disabled
    fpga_ts_packet_filter_limit: float | None
    # Period of sample clock in ns. Default is 25 ns
    sample_clock_period_ns: float = 25
    # How many readout blocks to read and decode (for debugging)
    max_readout_blocks: int | None = None
    # Was the TLU used? If yes, then all halfhits before T0 are thrown away (this is when the FPGA ts becomes 0)
    use_tlu: bool = False

    def print_setup_info(self) -> None:
        print(f'The setup contains {self.nlayers} layers with {self.nchips_per_layer} chips in each layer')
        print( 'The FPGA timestamp is 8 Bytes long')

    def print_filtering_info(self) -> None:
        print( 'Packet filtering:')
        if self.fpga_ts_packet_filter_limit is None:
            print( '    disabled')
        else:
            print(f'    Packets with FPGA timestamp more than {self.fpga_ts_packet_filter_limit} ns different than the timestamp of the previous packet are discarded')

    def print(self) -> None:
        self.print_setup_info()
        self.print_filtering_info()

@dataclass
class DecoderSettings_v3(DecoderSettingsBase):
    # Maximum FPGA timestamp difference for matching in seconds
    fpga_ts_matching_limit: float = 3e-3
    # Matcher strategy
    matcher_strategy: MatcherStrategy = MatcherStrategy.CLOSEST
    # Maximum halfhit timestamp difference for matching in clock cycles
    matcher_ts_limit: int = 2
    # Maximum relative ToT deviation for matching
    matcher_tot_limit: float = 0.2
    # Flag to save h5 files for row and column halfhits separately
    write_strip_files: bool = False

    def print(self) -> None:
        super().print()
        print( 'HalfHit matching:')
        print(f'    Max FPGA timestamp difference between halfhits in a hit is {self.fpga_ts_matching_limit} s')
        print(f'    {"ALL" if self.matcher_strategy == MatcherStrategy.ALL else "CLOSEST"} matching strategy is used')
        print(f'    Max on-chip timestamp difference between halfhits in a hit is {self.matcher_ts_limit} clock cycles')
        print(f'    Max ToT difference between halfhits in a hit is {self.matcher_tot_limit*100}%')
        print(f'    "Strip" files were {"" if self.write_strip_files else "not "}written')

@dataclass
class DecoderSettings_v4(DecoderSettingsBase):
    use_negedge_ts: bool = True
    def print(self) -> None:
        super().print()
        print( 'Decoding:')
        print(f'    Negedge TS is {" " if self.use_negedge_ts else "not "}used')

@dataclass
class StatsBase:
    total_byte_count = 0
    skipped_byte_count = 0
    filtered_packet_count = 0
    zero_ts_packet_count = 0
    before_t0_packet_count = 0
    hit_count = 0
    first_fpga_timestamp: float | None = None
    last_fpga_timestamp: float | None = None
    block_lengths_total: list[int] = field(default_factory=list)
    block_lengths_current: list[int] = field(default_factory=list)
    reasons_for_skipping_bytes = {key : 0 for key in [
        "header_and_length_different",
        "wrong_fpga_ts_length",
        "wrong_layer",
        "wrong_chip_id",
        "wrong_astropix_payload_length"
        ]
                                 }

    def get_time_string(self, timestamp1, timestamp2):
        if timestamp1 is None or timestamp2 is None:
            return None
        seconds = (max([timestamp1, timestamp2]) - min([timestamp1, timestamp2])) / 1e9
        if seconds < 1:
            return f'{round(seconds, 3)} s'
        seconds = round(seconds)
        return f'{seconds//3600}h {(seconds//60)%60}m {seconds%60}s'

    def print_skipped_byte_stats(self):
        print(f'{self.skipped_byte_count} bytes skipped while decoding out of {self.total_byte_count} bytes of data ({round(self.skipped_byte_count/self.total_byte_count*100, 2) if self.total_byte_count != 0 else np.inf}%)')
        print("Reasons for skipping bytes:")
        for key in self.reasons_for_skipping_bytes:
            print(f"{key} :", self.reasons_for_skipping_bytes[key])

    def print_block_stats(self):
        print(f'Average size of a readout block is {np.mean(self.block_lengths_total)}')

    def print_filtering_stats(self, total_number):
        print(f'{self.filtered_packet_count} packets were filtered out ({round(self.filtered_packet_count/total_number*100., 2) if total_number != 0 else np.inf}%), including {self.zero_ts_packet_count} packets with fpga timestamp 0 and {self.before_t0_packet_count} packets before the T0 signal')

    def print_hit_stats(self):
        print(f'{self.hit_count} hits')

    def print_timestamp_stats(self):
        if self.first_fpga_timestamp:
            print(f'First FPGA timestamp is {self.first_fpga_timestamp:.0f} ns')
        else:
            print( 'First FPGA timestamp is unknown')

        if self.last_fpga_timestamp:
            print(f'Last FPGA timestamp is {self.last_fpga_timestamp:.0f} ns')
        else:
            print( 'Last FPGA timestamp is unknown')
        if self.first_fpga_timestamp and self.last_fpga_timestamp:
            print(f'The decoded part approximately corresponds to {self.get_time_string(self.last_fpga_timestamp, self.first_fpga_timestamp)} of run time')

    def print(self):
        self.print_skipped_byte_stats()
        self.print_block_stats()
        self.print_filtering_stats(self.hit_count)
        self.print_hit_stats()
        self.print_timestamp_stats()

@dataclass
class Stats_v3(StatsBase):
    hh_count = 0
    hh_row_count = 0
    filtered_hh_row_count = 0
    hh_wo_match_count = 0

    def print_filtering_stats(self):
        super().print_filtering_stats(self.hh_count)
        filtered_hh_col_count = self.filtered_packet_count - self.filtered_hh_row_count
        print(f'ratio of filtered column to row halfhits = {filtered_hh_col_count/self.filtered_hh_row_count if self.filtered_hh_row_count != 0 else np.inf} ({filtered_hh_col_count} col halfhits and {self.filtered_hh_row_count} row halfhits)')

    def print_hh_stats(self):
        print(f'{self.hh_count} halfhits')
        hh_col_count = self.hh_count - self.hh_row_count
        print(f'ratio of column to row halfhits = {hh_col_count/self.hh_row_count if self.hh_row_count != 0 else np.inf} ({hh_col_count} col halfhits and {self.hh_row_count} row halfhits)')
        print(f'{self.hh_wo_match_count} halfhits had no match ({round(self.hh_wo_match_count/self.hh_count*100, 0) if self.hh_count != 0 else np.inf}%)')

    def print_hit_stats(self):
        super().print_hit_stats()
        print(f'ratio of hits to halfhits = {self.hit_count/self.hh_count if self.hh_count != 0 else np.inf}')

    def print(self):
        self.print_skipped_byte_stats()
        self.print_block_stats()
        self.print_filtering_stats()
        self.print_hh_stats()
        self.print_hit_stats()
        self.print_timestamp_stats()

@dataclass
class Stats_v4(StatsBase):
    filtered_hit_count = 0

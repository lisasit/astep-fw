from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field

import numpy as np


class MatcherStrategy(Enum):
    ALL = 0
    CLOSEST = 1


@dataclass
class DecoderSettings:
    # Number of layers
    nlayers: int
    # Number of chips per layer
    nchips_per_layer: int
    # Length of the FPGA timestamp in bytes
    fpga_ts_length: int
    # FPGA timestamp clock frequency in Hz
    fpga_ts_clock_freq: float
    # Maximum FPGA timestamp difference between halfhits for filterung
    fpga_ts_hh_filter_limit: float
    # Maximum FPGA timestamp difference for matching in seconds
    fpga_ts_matching_limit: float
    # Matcher strategy
    matcher_strategy: MatcherStrategy
    # Maximum halfhit timestamp difference for matching in clock cycles
    matcher_ts_limit: int
    # Maximum relative ToT deviation for matching
    matcher_tot_limit: float
    # Flag to save h5 files for row and column halfhits separately
    write_strip_files: bool = False
    # Period of sample clock in ns. Default is 25 ns
    sample_clock_period_ns: float = 25
    # how frequently prints about blocks appear. None for not at all
    print_block_stats_freq:int | None  = 1000
    # How many readout blocks to read and decode (for debugging)
    max_readout_blocks: int | None = None

    def print(self) -> None:
        print(f'The setup contains {self.nlayers} layers with {self.nchips_per_layer} chips in each layer')
        print(f'The FPGA timestamp is 8 Bytes long')
        print(f'HalfHit filtering:')
        print(f'    HalfHits with FPGA timestamp more than {self.fpga_ts_hh_filter_limit} ns different than the timestamp of the previous HalfHit are discarded')
        print(f'HalfHit matching:')
        print(f'    Max FPGA timestamp difference between halfhits in a hit is {self.fpga_ts_matching_limit} s')
        print(f'    {"ALL" if self.matcher_strategy == MatcherStrategy.ALL else "CLOSEST"} matching strategy is used')
        print(f'    Max on-chip timestamp difference between halfhits in a hit is {self.matcher_ts_limit} clock cycles')
        print(f'    Max ToT difference between halfhits in a hit is {self.matcher_tot_limit*100}%')
        print(f'    "Strip" files were {"" if self.write_strip_files else "not "}written')


@dataclass
class Stats:
    total_byte_count = 0
    skipped_byte_count = 0
    hh_count = 0
    hh_row_count = 0
    filtered_hh_count = 0
    zero_ts_hh_count = 0
    filtered_hh_row_count = 0
    hh_wo_match_count = 0
    hit_count = 0
    first_fpga_timestamp: float | None = None
    last_fpga_timestamp: float | None = None
    block_lengths_total: list[int] = field(default_factory=list)
    block_lengths_current: list[int] = field(default_factory=list)

    def get_time_string(self, timestamp1, timestamp2):
        if timestamp1 is None or timestamp2 is None:
            return None
        seconds = (max([timestamp1, timestamp2]) - min([timestamp1, timestamp2])) / 1e9
        if seconds < 1:
            return f'{round(seconds, 3)} s'
        seconds = round(seconds)
        return f'{seconds//3600}h {(seconds//60)%60}m {seconds%60}s'

    def print(self):
        print(f'{self.skipped_byte_count} bytes skipped while decoding out of {self.total_byte_count} bytes of data ({round(self.skipped_byte_count/self.total_byte_count*100, 2) if self.total_byte_count != 0 else np.inf}%)')
        print(f'Average size of a readout block is {np.mean(self.block_lengths_total)}')
        print(f'{self.hh_count} halfhits')
        hh_col_count = self.hh_count - self.hh_row_count
        print(f'ratio of column to row halfhits = {hh_col_count/self.hh_row_count if self.hh_row_count != 0 else np.inf} ({hh_col_count} col halfhits and {self.hh_row_count} row halfhits)')
        print(f'{self.filtered_hh_count} halfhits were filtered out ({round(self.filtered_hh_count/self.hh_count, 2) if self.hh_count != 0 else np.inf}%), including {self.zero_ts_hh_count} hits with fpga timestamp 0')
        filtered_hh_col_count = self.filtered_hh_count - self.filtered_hh_row_count
        print(f'ratio of filtered column to row halfhits = {filtered_hh_col_count/self.filtered_hh_row_count if self.filtered_hh_row_count != 0 else np.inf} ({filtered_hh_col_count} col halfhits and {self.filtered_hh_row_count} row halfhits)')
        print(f'{self.hit_count} hits')
        print(f'ratio of hits to halfhits = {self.hit_count/self.hh_count if self.hh_count != 0 else np.inf}')
        print(f'{self.hh_wo_match_count} halfhits had no match ({round(self.hh_wo_match_count/self.hh_count*100, 0) if self.hh_count != 0 else np.inf}%)')
        assert self.first_fpga_timestamp and self.last_fpga_timestamp
        print(f'First FPGA timestamp is {self.first_fpga_timestamp:.0f} ns')
        print(f'Last FPGA timestamp is {self.last_fpga_timestamp:.0f} ns')
        print(f'The decoded part approximately corresponds to {self.get_time_string(self.last_fpga_timestamp, self.first_fpga_timestamp)} of run time')

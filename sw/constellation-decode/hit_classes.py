from dataclasses import dataclass 
import numpy as np

HIT_TYPE = np.dtype([
        ('column', 'i4'),
        ('row', 'i4'),
        ('raw', 'i4'),
        ('charge', 'd'),
        ('timestamp', 'd'),
        ('trigger_number', 'u4')
    ])

@dataclass
class HalfHit_v3:
    packet_length: int
    layer: int
    chip_id: int
    payload: int
    is_col: bool
    location: int
    timestamp: int
    tot_raw: int
    tot_us: float
    fpga_ts: int
    index: int
    readout_id: int


@dataclass
class MatchedHit_v3:
    row: int
    col: int
    fpga_ts_row: int
    fpga_ts_col: int
    tot_row: int
    tot_col: int
    index_row: int
    index_col: int
    timestamp_row: int 
    timestamp_col: int 
    chip_id: int 
    layer: int


@dataclass
class Hit_v3:
    row: int
    col: int
    fpga_ts: int
    tot_raw: int
    tot_us: float
    timestamp: int 
    chip_id: int 
    layer: int 

@dataclass
class Hit_v4:
    row: int
    col: int
    fpga_ts: int
    tot_raw: int
    tot_us: float
    timestamp: int 
    chip_id: int 
    layer: int
    payload: int

        # self.ts1_neg = None
        # self.ts1 = None
        # self.ts1_fine = None
        # self.ts1_tdc = None
        # self.ts2_neg = None
        # self.ts2 = None
        # self.ts2_fine = None
        # self.ts2_tdc = None
        # self.ts1_dec = None
        # self.ts2_dec = None


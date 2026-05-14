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
    tot_ns: float
    fpga_ts: int
    index: int
    readout_id: int
    matches: int = 0


@dataclass
class MatchedHit_v3:
    row_hh: HalfHit_v3
    col_hh: HalfHit_v3


@dataclass
class Hit_v3:
    row: int
    col: int
    fpga_ts: int
    tot_raw: int
    tot_ns: float
    timestamp: int
    chip_id: int
    layer: int

@dataclass
class Hit_v4:
    row: int
    col: int
    fpga_ts: int
    tot_raw: int
    tot_ns: float
    ts1: int
    ts2: int
    chip_id: int
    layer: int
    payload: int
    packet_length: int

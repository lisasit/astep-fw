from __future__ import annotations
from pathlib import Path
from collections import deque
from dataclasses import fields
import h5py
import numpy as np
from tqdm import tqdm

from .common import Stats_v3, DecoderSettings_v3
from .decoder_base import DecoderBase
from .hit_classes import HalfHit_v3, Hit_v3, HIT_TYPE
from .matcher_v3 import Matcher
from .utils import make_nice_number, find_timestamp_difference

class Decoder_v3(DecoderBase):
    def __init__(self, bin_filename, stats: Stats_v3, decoder_settings: DecoderSettings_v3):
        super().__init__(bin_filename, stats, decoder_settings)

        # h5 files for saving the halfhit data as if we had two separate strip detectors
        self.h5_strip_files = {}
        self.h5_strip_datasets = {}

        # Index of the last halfhit
        self.last_hh_index = 0

        # Halfhit matching deque
        self.hh_to_match: deque[HalfHit_v3] = deque()
        self.hh_to_fill: deque[HalfHit_v3] = deque()

        # Matched hits
        self.hits: list[Hit_v3] = []
        # Halfhits
        self.halfhits: list[HalfHit_v3] = []

        self.matcher = Matcher(self.hh_to_match, stats, self.decoder_settings)

        self.pbars_stats.append(tqdm(total=0, bar_format='{desc}'))

    def decode_iteration(self) -> bool:
        # one iteration of decoding. Returns True if more can be decoded and False if this is the last iteration
        # loop for filling hh_to_match once
        while True:
            # read and decode a block
            if self.hh_to_fill is None:
                break
            if len(self.hh_to_fill) == 0:
                self.hh_to_fill = self.read_and_decode_next_block()
                # check if we ran out of blocks in the binary file
                if self.hh_to_fill is None:
                    break
            # Check if the hh_to_match needs to be filled
            hh_to_match_full = False
            while self.hh_to_fill:
                hh = self.hh_to_fill[0]
                if self.hh_to_match and float(find_timestamp_difference(hh.fpga_ts, self.hh_to_match[0].fpga_ts, self.decoder_settings.fpga_ts_length*8)) / self.decoder_settings.fpga_ts_clock_freq > self.decoder_settings.fpga_ts_matching_limit:
                        hh_to_match_full = True
                        break

                # Move halfthit to matching deque and to internal list of all halfhits
                self.halfhits.append(self.hh_to_fill[0])
                self.hh_to_match.append(self.hh_to_fill.popleft())
            if hh_to_match_full:
                break

        # Check if any halfhits are left for matching
        if not self.hh_to_fill and not self.hh_to_match:
            return False

        # Match hits
        matched_hits = self.matcher.match()
        self.hits += matched_hits
        self.stats.hit_count += len(matched_hits)
        return True

    def read_and_decode_next_block(self):
        result: deque[HalfHit_v3] = deque()
        block = self.read_block()

        if block is None:
            return None

        # Split block into packets
        packets = self.split_packets(block)

        # Decode packets
        decoded_packets = [self.decode_packet(packet) for packet in packets]

        # Filter broken packets
        for decoded_packet in decoded_packets:
            if decoded_packet is not None:
                self.stats.hh_count += 1
                self.stats.hh_row_count += 0 if decoded_packet.is_col else 1
                if self.is_not_filtered_out(decoded_packet):
                    result.append(decoded_packet)
                else:
                    self.stats.filtered_packet_count += 1
                    self.stats.filtered_hh_row_count += 0 if decoded_packet.is_col else 1
        return result

    def check_packet(self, packet: bytes) -> bool:
        return super().check_packet(packet, payload_length=4)

    def decode_packet(self, packet: bytes) -> HalfHit_v3 | None:
        if len(packet) < 7:
            print(f'ERROR, hit packet too short ({len(packet)}), probably something went wrong with splitting packets')
            return None
        if len(packet) > 15:
            print(f'ERROR, hit packet too long ({len(packet)}), probably something went wrong with splitting packets')
            return None

        self.last_hh_index += 1

        # byte 0 = length of the packet
        packet_length = int(packet[0])
        # byte 1 = layer
        layer = int(packet[1])
        # byte 2 is a header. 3 bit payload, 5 bit chip id
        byte2 = int(packet[2])
        chip_id = byte2 >> 3
        payload = byte2 & 0b00000111
        # byte 3 is a hit location. 1 bit isCol, 1 bit reserved, 6 bit location id
        byte3 = int(packet[3])
        is_col = bool(byte3 >> 7 & 1)
        location = byte3 & 0b00111111
        # byte 4 is the timestamp
        timestamp = int(packet[4])
        # byte 5 is ToT MSB
        tot_msb = int(packet[5]) & 0b00001111
        # byte 6 is ToT LSB
        tot_lsb = int(packet[6])
        # bytes 7-end are the FPGA timestamp
        fpga_ts = int.from_bytes(packet[len(packet) - self.decoder_settings.fpga_ts_length:], 'big')

        # constructing ToT total
        tot_total = (tot_msb << 8) + tot_lsb

        return HalfHit_v3(packet_length, layer, chip_id, payload, is_col, location, timestamp, tot_total, tot_total*self.decoder_settings.sample_clock_period_ns, fpga_ts, self.last_hh_index, self.last_readout_id)

    def prepare_h5_file(self, filename) -> None:
        super().prepare_h5_file(filename)
        filename_path = Path(filename)

        if self.decoder_settings.write_strip_files:
            for hh_type in ['row', 'col']:
                self.h5_strip_files[hh_type] = h5py.File(f"{filename_path.parent}/{filename_path.stem}_{hh_type}{filename_path.suffix}", "w")
                self.h5_strip_datasets[hh_type] = self.h5_strip_files[hh_type].create_dataset("Hits",
                                                                        shape=(0, ),
                                                                        maxshape=(None, ),
                                                                        chunks=True,
                                                                        dtype=HIT_TYPE
                                                                        )

    def prepare_root_file(self, filename) -> None:
        super().prepare_root_file(filename)
        self.root_file.mktree('hits', {field.name : [] for field in fields(Hit_v3)})
        self.root_file.mktree('halfhits', {field.name : [] for field in fields(HalfHit_v3)})

    def close_files(self):
        super().close_files()
        for hh_type in self.h5_strip_files:
            self.h5_strip_files[hh_type].close()

    def time_to_write_files(self):
        return super().time_to_write_files() or len(self.halfhits) > 20000

    def update_progress_bar(self):
        super().update_progress_bar()
        self.pbars_stats[1].set_description_str(f'{make_nice_number(self.stats.hh_count)} halfhits, {make_nice_number(self.stats.hh_row_count)} row halfhits, {make_nice_number(self.stats.hh_count - self.stats.hh_row_count)} col halfhits')

    def write_hits(self):
        # if writing strip files for halfhits
        if self.h5_file_hits is not None and self.decoder_settings.write_strip_files:
            def is_right_hh(hh, hh_type):
                if hh_type == 'row':
                    return not hh.is_col
                return hh.is_col
            def make_right_list(hh, hh_type):
                result = [0, 0, hh.tot_raw, hh.tot_us, float(hit.fpga_ts) / self.decoder_settings.fpga_ts_clock_freq * 1e9, 0]
                if hh_type == 'row':
                    result[1] = hh.location
                else:
                    result[0] = hh.location
                return result
            for hh_type in ['row', 'col']:
                assert self.h5_strip_datasets[hh_type]
                current_rows = self.h5_strip_datasets[hh_type].shape[0]
                correct_hh = [hh for hh in self.halfhits if is_right_hh(hh, hh_type)]
                self.h5_strip_datasets[hh_type].resize((current_rows + len(correct_hh), ))
                self.h5_strip_datasets[hh_type][current_rows:] = np.array(
                    [make_right_list(hh, hh_type) for hh in correct_hh], dtype=HIT_TYPE
                )
                self.h5_strip_files[h_type].flush()

        # if writing into a root file
        if self.root_file is not None:
            hit_dict = {field.name : [getattr(hit, field.name) for hit in self.hits] for field in fields(Hit_v3)}
            halfhit_dict = {field.name : [getattr(hh, field.name) for hh in self.halfhits] for field in fields(HalfHit_v3)}
            self.root_file['hits'].extend(hit_dict)
            self.root_file['halfhits'].extend(halfhit_dict)
        super().write_hits()
        self.halfhits.clear()

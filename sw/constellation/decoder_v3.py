from collections import deque

import h5py
import numpy as np

from .hit_classes_v3 import HalfHit_v3, Hit_v3, HIT_TYPE
from .matcher_v3 import Matcher
from .common_v3 import Stats, DecoderSettings


class Decoder:
    def __init__(self, bin_filename, stats: Stats, decoder_settings: DecoderSettings):
        self.bin_file = open(bin_filename, 'rb')

        self.decoder_settings = decoder_settings
        self.stats = stats

        # Counters
        self.last_readout_id = 0
        self.last_hh_index = 0

        # Leftover bytes from package splitting
        self.leftovers = bytes()

        # Last FPGA timestamp for filtering
        self.last_good_fpga_ts = 0

        # Halfhit matching deque
        self.hh_to_match: deque[HalfHit_v3] = deque()

        # Matched hits
        self.hits: list[Hit_v3] = []

        self.matcher = Matcher(self.hh_to_match, stats, self.decoder_settings)

        self.h5_file: h5py.File | None = None
        self.h5_dataset: h5py.Dataset | None = None

    def decode(self):
        hh_to_fill = self.read_all_hhs()

        print("Starting filling deque")

        while True:
            # Fill halfhits into matching deque
            while hh_to_fill:
                hh = hh_to_fill[0]

                # Check if halfhit is within matching limit
                if self.hh_to_match and float(hh.fpga_ts - self.hh_to_match[0].fpga_ts) / self.decoder_settings.fpga_ts_clock_freq > self.decoder_settings.fpga_ts_matching_limit:
                    print(f"Stop filling ({float(hh.fpga_ts - self.hh_to_match[0].fpga_ts) / self.decoder_settings.fpga_ts_clock_freq} > {self.decoder_settings.fpga_ts_matching_limit})")
                    break

                print(f"Add {'col' if hh.is_col else 'row'} hh {hh.index} with loc {hh.location:02d}, fpga ts {hh.fpga_ts}, chip ts {hh.timestamp:03d}, tot {hh.tot:04d}")

                # Move halfthit to matching deque
                self.hh_to_match.append(hh_to_fill.popleft())

            # Check if any halfhits are left for matching
            if not hh_to_fill and not self.hh_to_match:
                print("Nothing left to match, leaving")
                break

            # Match hits
            matched_hits = self.matcher.match()
            self.hits += matched_hits
            self.stats.hit_count += len(matched_hits)

            # Write hits from time to time
            if len(self.hits) > 100000:
                self.write_hits()

        self.write_hits()

    def read_all_hhs(self) -> deque[HalfHit_v3]:
        hh_to_fill: deque[HalfHit_v3] = deque()

        print("Reading all halfhits from file")

        while True:
            # Get binary readout block
            block = self.read_block()

            if block is None:
                break

            self.last_readout_id += 1

            # Split block into packets
            packets = self.split_packets(block)

            # Decode packets
            decoded_packets = [self.decode_packet(packet) for packet in packets]

            # Filter broken packets
            for decoded_packet in decoded_packets:
                if decoded_packet is not None:
                    self.stats.hh_count += 1
                    self.stats.hh_row_count += 0 if decoded_packet.is_col else 1
                    if self.check_hh(decoded_packet):
                        hh_to_fill.append(decoded_packet)

        return hh_to_fill

    def read_block(self) -> bytes | None:
        read_int = self.bin_file.read(2)
        if len(read_int) == 0:
            return None
        nbits = int.from_bytes(read_int, 'little')
        result_block = self.bin_file.read(nbits)
        self.stats.total_byte_count += len(result_block)
        return result_block

    def split_packets(self, byte_block: bytes) -> list[bytes]:
        result_packets: list[bytes] = []
        i = 0
        new_byte_block = self.leftovers + byte_block
        self.leftovers = bytes()
        while i < len(new_byte_block):
            packet_length = int(new_byte_block[i])
            packet = new_byte_block[i:i+packet_length+1]
            if self.check_packet(packet):
                result_packets.append(packet)
                i += packet_length + 1
            elif i + packet_length + 1 >= len(byte_block):
                self.leftovers = packet
                break
            else:
                self.stats.skipped_byte_count += 1
                i += 1
        return result_packets

    def check_packet(self, packet: bytes) -> bool:
        if len(packet) - 1 != int(packet[0]):
            return False
        if len(packet) - 7 != self.decoder_settings.fpga_ts_length:
            return False
        layer = int(packet[1])
        # byte 2 is a header. 3 bit payload, 5 bit chip id
        byte = int(packet[2])
        chip_id = byte >> 3
        payload = byte & 0b00000111
        if layer > self.decoder_settings.nlayers:
            return False
        if chip_id >= self.decoder_settings.nchips_per_layer:
            return False
        if payload != 4:
            return False
        return True

    def decode_packet(self, packet: bytes) -> HalfHit_v3 | None:
        if len(packet) < 7:
            print(f'ERROR, hit packet too short ({len(packet)}), probably something went wrong with splitting packets')
            return None
        if len(packet) > 15:
            print(f'ERROR, hit packet too long ({len(packet)}), probably something went wrong with splitting packets')
            return

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

        return HalfHit_v3(packet_length, layer, chip_id, payload, is_col, location, timestamp, tot_total, fpga_ts, self.last_hh_index, self.last_readout_id)

    def check_hh(self, hh: HalfHit_v3) -> bool:
        if hh.fpga_ts == 0:
            self.stats.filtered_hh_count += 1
            self.stats.filtered_hh_row_count += 0 if hh.is_col else 1
            self.stats.zero_ts_hh_count += 1
            return False
        if hh.fpga_ts < self.last_good_fpga_ts:
            self.stats.filtered_hh_count += 1
            self.stats.filtered_hh_row_count += 0 if hh.is_col else 1
            # TODO stats
            return False
        if abs(hh.fpga_ts - self.last_good_fpga_ts) / self.decoder_settings.fpga_ts_clock_freq > self.decoder_settings.fpga_ts_hh_filter_limit:
            self.stats.filtered_hh_count += 1
            self.stats.filtered_hh_row_count += 0 if hh.is_col else 1
            return False
        self.last_good_fpga_ts = hh.fpga_ts
        return True

    def prepare_h5_file(self, filename: str) -> None:
        self.h5_file = h5py.File(filename, 'w')
        self.h5_dataset = self.h5_file.create_dataset(
            "Hits",
            shape=(0, ),
            maxshape=(None, ),
            chunks=True,
            dtype=HIT_TYPE,
        )

    def write_hits(self) -> None:
        if self.h5_file is not None:
            assert self.h5_dataset
            current_rows = self.h5_dataset.shape[0]
            self.h5_dataset.resize((current_rows + len(self.hits), ))
            self.h5_dataset[current_rows:] = np.array(
                [(hit.col, hit.row, hit.tot, hit.tot * 25e-4, float(hit.fpga_ts) / self.decoder_settings.fpga_ts_clock_freq * 1e9, 0) for hit in self.hits], dtype=HIT_TYPE
            )
            self.h5_file.flush()

        if self.stats.first_fpga_timestamp is None:
            self.stats.first_fpga_timestamp = float(self.hits[0].fpga_ts) / self.decoder_settings.fpga_ts_clock_freq * 1e9
        self.stats.last_fpga_timestamp = self.hits[-1].fpga_ts / self.decoder_settings.fpga_ts_clock_freq * 1e9
        self.hits.clear()

from __future__ import annotations
from dataclasses import fields
import numpy as np

from .common import Stats_v4, DecoderSettings_v4
from .decoder_base import DecoderBase
from .hit_classes import Hit_v4

class Decoder_v4(DecoderBase):
    def __init__(self, bin_filename, stats: Stats_v4, decoder_settings: DecoderSettings_v4):
        super().__init__(bin_filename, stats, decoder_settings)
        self.hits: list[Hit_v4]
        self.stats: Stats_v4
        self.decoder_settings: DecoderSettings_v4

        self.past_t0 = False
        self.last_fpga_ts = None

    def decode_iteration(self) -> bool:
        # one iteration of decoding. Returns True if more can be decoded and False if this is the last iteration

        block = self.read_block()
        if block is None:
            return False

        # Split block into packets
        hit_packets = self.split_packets(block)

        # Decode packets
        decoded_packets = [self.decode_packet(packet) for packet in hit_packets]

        # Filter broken packets
        for decoded_packet in decoded_packets:
            if decoded_packet is not None:
                self.stats.packet_count += 1
                self.stats.hit_count += 1

                if self.is_not_filtered_out(decoded_packet):
                    self.hits.append(decoded_packet)
                else:
                    self.stats.filtered_hit_count += 1
        return True

    def check_packet(self, packet: bytes) -> bool:
        return super()._check_packet(packet, payload_length=7)

    def gray_to_dec(self, gray):
        """
        Decode Gray code to decimal

        :param gray: Gray code

        :returns: Decoded decimal
        """
        bits = gray >> 1
        while bits:
            gray ^= bits
            bits >>= 1
        return gray

    def decode_packet(self, packet: bytes) -> Hit_v4 | None:
        if len(packet) < 10:
            print(f'ERROR, hit packet too short ({len(packet)}), probably something went wrong with splitting packets')
            return None
        if len(packet) > 18:
            print(f'ERROR, hit packet too long ({len(packet)}), probably something went wrong with splitting packets')
            return

        # byte 0 = length of the packet
        packet_length = int(packet[0])
        # byte 1 = layer
        layer = int(packet[1])
        # byte 2 is a header. 3 bit payload, 5 bit chip id
        byte2 = int(packet[2])
        chip_id = byte2 >> 3
        payload = byte2 & 0b00000111
        # byte 3 and part of byte 4 is hit location
        byte3 = int(packet[3])
        byte4 = int(packet[4])
        row = byte3 >> 3
        col = ((byte3 & 0b111) << 2) + (byte4 >> 6)
        #
        ts1_neg      = (int(packet[4]) >> 5) & 0b1
        ts1         = ((int(packet[4]) & 0b11111) << 9) + (int(packet[5]) << 1) + (int(packet[6]) >> 7)
        ts1_fine     = (int(packet[6]) >> 4) & 0b111
        ts1_tdc      = ((int(packet[6]) & 0b1111) << 1) + (int(packet[7]) >> 7)
        ts1_dec = self.gray_to_dec((ts1 << 3) + ts1_fine) << 1 | (ts1_neg & self.decoder_settings.use_negedge_ts)
        #
        ts2_neg      = (int(packet[7]) >> 6) & 0b1
        ts2         = ((int(packet[7]) & 0b111111) << 8) + int(packet[8])
        ts2_fine     = (int(packet[9]) >> 5) & 0b111
        ts2_tdc      = int(packet[9]) & 0b11111
        ts2_dec = self.gray_to_dec((ts2 << 3) + ts2_fine) << 1 | (ts2_neg & self.decoder_settings.use_negedge_ts)

        if ts2_dec > ts1_dec:
            tot_raw = ts2_dec - ts1_dec
        else:
            tot_raw = 2**18 + ts2_dec - ts1_dec
        tot_ns = tot_raw * self.decoder_settings.sample_clock_period_ns

        fpga_ts = int.from_bytes(packet[10:], 'big')

        return Hit_v4(row, col, fpga_ts, tot_raw, tot_ns, ts1_dec, ts2_dec, chip_id, layer, payload, packet_length)

    def prepare_root_file(self, filename) -> None:
        super().prepare_root_file(filename)
        self.root_file.mktree('hits', {field.name : [] for field in fields(Hit_v4)})

    def write_hits(self):
        # if writing into a root file
        if self.root_file is not None:
            hit_dict = {field.name : [getattr(hit, field.name) for hit in self.hits] for field in fields(Hit_v4)}
            self.root_file['hits'].extend(hit_dict)

        super().write_hits()

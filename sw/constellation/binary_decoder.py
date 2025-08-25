# import sys
# sys.path.append('../astropix-analysis')
import binascii
from binary_matcher import Matcher, Hit
import uproot

class HalfHit:
    def __init__(self):
        self.sample_clock_period_ns = 5 #ns
        self.packet_length = None
        self.layer = None
        self.isCol = None
        self.location = None
        self.timestamp = None
        self.tot_lsb = None
        self.tot_msb = None
        self.tot_total = None
        self.tot_us = None
        self.chip_id = None
        self.payload = None
        self.readout_id = None
        self.tot_us = None
        self.fpga_ts = None

    def get_tot_us(self):
        if self.tot_us is None:
            self.tot_us = self.tot_total * self.sample_clock_period_ns / 1000.0
        return self.tot_us

    def get_dict(self):
        if self.tot_total is not None:
            self.get_tot_us()
        return self.__dict__

class Decoder:
    #I did not add the code for split hits at the endges of the readout blocks. Will add in the future if necessary
    def __init__(self, bin_filename, legacy=False):
        self.bin_file = open(bin_filename, 'rb')
        self.header_string = b'\x20'
        self.bytes_per_packet = 5
        self.hits = []
        self.halfhits = []
        self.legacy = legacy

    def write_hits_to_file(self, filename):
        #print(f'Writing {len(self.hits)} hits')
        with uproot.recreate(filename) as root_file:
            result_dict = {}
            for attr in Hit().get_dict().keys():
                result_dict[attr] = [getattr(hit, attr) for hit in self.hits]
            root_file['hits'] = result_dict

            result_dict_hh = {}
            for attr in HalfHit().get_dict().keys():
                if attr == 'tot_us':
                    continue
                result_dict_hh[attr] = [getattr(halfhit, attr) for halfhit in self.halfhits]
            root_file['halfhits'] = result_dict_hh


    def decode(self):
        readout_id = 0
        while True:
            block = self.read_block()
            if block is None:
                break
            if self.legacy:
                hit_packets = self.split_packets_legacy(block)
            else:
                hit_packets = self.split_packets(block)
            readout_id += 1
            halfhits = [self.decode_packet(packet, readout_id) for packet in hit_packets]
            halfhits = [halfhit for halfhit in halfhits if halfhit is not None]
            matcher = Matcher(halfhits)
            matcher.match()
            self.halfhits += halfhits
            self.hits += matcher.hits

    def read_block(self):
        read_int = self.bin_file.read(4)
        if len(read_int) == 0:
            return None
        nbits = int.from_bytes(read_int, "big")
        result_block = self.bin_file.read(nbits)
        return result_block


    def check_packet(self, packet):
        return True
        # 2nd bit in byte 1 is reserved, so has to be 0
        if packet[1] & 0b00000010:
            return False
        if packet[3] & 0b11110000:
            return False
        return True


    def split_packets(self, byte_block):
        result_packets = []
        i = 0
        # print('block', binascii.hexlify(byte_block))
        while i < len(byte_block):
            packet_length = int(byte_block[i])
            packet = byte_block[i:i+packet_length+1]
            if self.check_packet(packet):
                result_packets.append(packet)
                i += packet_length + 1
            else:
                i += 1
        # print('readouts', [binascii.hexlify(packet) for packet in result_packets])
        return result_packets


    def decode_packet(self, hit_packet, readout_id):
        try:
            halfhit = HalfHit()
            # byte 0 = length of the packet
            halfhit.packet_length = int(hit_packet[0])
            # byte 1 = layer
            halfhit.layer = int(hit_packet[1])
            # byte 2 is a header. 3 bit payload, 5 bit chip id
            byte = int(hit_packet[2])
            halfhit.chip_id = byte >> 3
            halfhit.payload = byte & 0b00000111
            # byte 3 is a hit location. 1 bit isCol, 1 bit reserved, 6 bit location id
            byte = int(hit_packet[3])
            halfhit.isCol = byte >> 7 & 1
            halfhit.location = byte & 0b00111111
            # byte 4 is the timestamp
            halfhit.timestamp = int(hit_packet[4])
            # byte 5 is ToT MSB
            halfhit.tot_msb = int(hit_packet[5]) & 0b00001111
            # byte 6 is ToT LSB
            halfhit.tot_lsb = int(hit_packet[6])
            # bytes 7-11 are the FPGA timestamp
            halfhit.fpga_ts = int.from_bytes(hit_packet[7:11], 'little')

            # constructing ToT total
            halfhit.tot_total = (halfhit.tot_msb << 8) + halfhit.tot_lsb

            halfhit.readout_id = readout_id

            return halfhit
        except IndexError:
            return None

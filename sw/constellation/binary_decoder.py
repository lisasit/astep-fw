# import sys
# sys.path.append('../astropix-analysis')
import binascii
from binary_matcher import Matcher, Hit
import uproot
import os
import toml
import yaml

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

def flatten(to_flatten):
    result_dict = {}
    if isinstance(to_flatten, dict):
        for_iter = to_flatten.keys()
    elif isinstance(to_flatten, list):
        for_iter = range(len(to_flatten))
    else:
        return to_flatten

    for i in for_iter:
        flat = flatten(to_flatten[i])
        if not isinstance(flat, dict):
            result_dict[f'{i}'] = flat
        else:
            for new_key in flat:
                result_dict[f'{i}/{new_key}'] = flat[new_key]
    return result_dict

def prepare_dict_for_root(dict_to_prepare):
    result_dict = flatten(dict_to_prepare)
    for key in result_dict:
        result_dict[key] = [result_dict[key]]
    return result_dict

class Decoder:
    #I did not add the code for split hits at the endges of the readout blocks. Will add in the future if necessary
    def __init__(self, bin_filename, constellation_config_filename=None, chip_config_filenames=None, legacy=False, verbose=True):
        """
        constellation_config_filename and chip_config_filenames can be added to provide metadata about the run that will be saved to the root file. If they are not provided, Decoder will try to look for a .toml (for the constellation config) and all .yml (for the chip configs) files with the same timestamp in the same directory as the binary file. If they are not found, the metadata is not written
        """

        self.bin_file = open(bin_filename, 'rb')
        self.verbose = verbose
        if self.verbose:
            print(f'Decoding {bin_filename}')

        if constellation_config_filename is None or chip_config is None:
            timestamp = bin_filename.split('/')[-1].split('_')[-1].replace('.bin', '')
            bin_directory = '/'.join(bin_filename.split('/')[:-1])
            same_timestamp_files = [filename for filename in os.listdir(bin_directory) if timestamp in filename]

            def find_fitting_file(file_extension):
                fitting_filenames = [filename for filename in same_timestamp_files if filename.endswith(file_extension)]
                if len(fitting_filenames) != 0:
                    if self.verbose:
                        print(f'Found {file_extension} config(s): {fitting_filenames}')
                    return [bin_directory + '/' + filename for filename in fitting_filenames]
                else:
                    if self.verbose:
                        print(f'{file_extension} config(s) not provided and could not be automatically identified')
                return None

            if constellation_config_filename is None:
                constellation_config_filename = find_fitting_file('.toml')
                if constellation_config_filename is not None:
                    if len(constellation_config_filename) > 1:
                        if self.verbose:
                            print('Several possible constellation configs, will not choose one, will skip this metadata')
                        constellation_config_filename = None
                    else:
                        constellation_config_filename = constellation_config_filename[0]

            if chip_config_filenames is None:
                chip_config_filenames = find_fitting_file('.yml')

        self.constellation_config_filename = constellation_config_filename
        self.chip_config_filenames = chip_config_filenames
        self.header_string = b'\x20'
        self.bytes_per_packet = 5
        self.hits = []
        self.halfhits = []
        self.legacy = legacy

    def write_hits_to_file(self, filename):
        # print(f'Writing {len(self.hits)} hits to  {filename}')
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

            if self.constellation_config_filename is not None:
                with open(self.constellation_config_filename, 'r') as f:
                    config = toml.load(f)
                root_file['constellation_config'] = prepare_dict_for_root(config)

            if self.chip_config_filenames is not None:
                config = {}
                for filename in self.chip_config_filenames:
                    with open(filename, "r", encoding="utf-8") as stream:
                        key_for_dict = '_'.join(filename.split('/')[-1].replace('.yml', '').split('_')[:-1])
                        config[key_for_dict] = yaml.safe_load(stream)
                root_file['chip_config'] = prepare_dict_for_root(config)


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
        read_int = self.bin_file.read(2)
        if len(read_int) == 0:
            return None
        nbits = int.from_bytes(read_int, "little")
        result_block = self.bin_file.read(nbits)
        return result_block


    def check_packet(self, packet):
        if int(packet[0]) > 16:
            return False
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

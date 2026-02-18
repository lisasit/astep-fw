# import sys
# sys.path.append('../astropix-analysis')
import binascii
from binary_matcher import Matcher
import uproot
import os
import toml
import yaml
import numpy as np
import h5py
from histogram_filler import HistogramFiller
from hit_classes import HalfHit_v3, Hit_v4, Hit_v3
from hit_filter_better import HitFilter
from datetime import timedelta

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

HIT_TYPE = np.dtype([
        ('column', 'i4'),
        ('row', 'i4'),
        ('raw', 'i4'),
        ('charge', 'd'),
        ('timestamp', 'd'),
        ('trigger_number', 'u4')
    ])

class Stats:
    def __init__(self, chip_version, fpga_ts_length=None):
        self.chip_version = chip_version
        self.hit_count = 0
        self.row_halfhit_count = 0
        self.col_halfhit_count = 0
        self.fpga_ts_length = fpga_ts_length
        self.skipped_byte_count = 0
        self.total_byte_count = 0
        self.filtered_hit_count = 0
        self.zero_ts_hit_count = 0
        self.last_timestamp = None #ns
        self.first_timestamp = None #ns

    def get_time_string(self, timestamp1, timestamp2):
        if timestamp1 is None or timestamp2 is None:
            return None
        seconds = np.max([timestamp1, timestamp2]) - np.min([timestamp1, timestamp2])
        if seconds < 1:
            return f'{round(seconds, 3)} s'
        seconds = round(seconds)
        return f'{seconds//3600} h {(seconds//60)%60} m {seconds%60} s'
        # result_string = ""
        # remainder = timestamp
        # unit_count = 0
        # if remainder / (60*60) > 1:
        #     result_string +=  f'{round(remainder) // (60*60)} h '
        #     remainder = remainder % (60*60)
        #     unit_count += 1
        # if unit_count > 0 or remainder / 60 > 1:
        #     result_string +=  f'{round(remainder) // 60} m '
        #     remainder = remainder % 60
        #     unit_count += 1
        # if unit_count > 0 or remainder > 1:
        #     result_string += f'{round(remainder)} s '
        #     remainder = timestamp - round(timestamp)
        # if unit_count < 3 and (unit_count > 0 or remainder * 1000 > 1):
        #     result_string += f'{round(remainder*1000)} ms '
        #     remainder = remainder - round(remainder*1000)/1000


    def print(self):
        self.halfhit_count = self.row_halfhit_count + self.col_halfhit_count
        print(f'{self.hit_count} hits')
        if self.chip_version == 3:
            print(f'{self.halfhit_count} halfhits')
            print(f'ratio of hits to halfhits = {self.hit_count/self.halfhit_count if self.halfhit_count != 0 else np.inf}')
            print(f'ratio of column to row halfhits = {self.col_halfhit_count/self.row_halfhit_count if self.row_halfhit_count != 0 else np.inf} ({self.col_halfhit_count} col halfhits and {self.row_halfhit_count} row halfhits)')
        print(f'Provided FPGA timestamp length {self.fpga_ts_length} bytes')
        print(f'{self.skipped_byte_count} bytes skipped while decoding out of {self.total_byte_count} bytes of data ({round(self.skipped_byte_count/self.total_byte_count*100, 2) if self.total_byte_count != 0 else np.inf}%)')
        print(f'When (if) writing into the h5 file, {self.filtered_hit_count} hits were filtered out ({round(self.filtered_hit_count/self.hit_count, 2) if self.hit_count != 0 else np.inf}%), including {self.zero_ts_hit_count} hits with fpga timestamp 0')

        print(f'First FPGA timestamp is {self.first_timestamp} ns')
        print(f'Last FPGA timestamp is {self.last_timestamp} ns')
        print(f'The decoded part approximately corresponds to {self.get_time_string(self.last_timestamp/1e9, self.first_timestamp/1e9)} of run time')

class Decoder:
    #I did not add the code for split hits at the endges of the readout blocks. Will add in the future if necessary
    def __init__(self, bin_filename, chip_version, fpga_ts_length=None, nlayers=None, nchips_per_layer=None, fpga_ts_clock_freq=80e6, constellation_config_filename=None, chip_config_filenames=None, verbose=True, max_nreadouts=None):
        """
        constellation_config_filename and chip_config_filenames can be added to provide metadata about the run that will be saved to the root file. If they are not provided, Decoder will try to look for a .toml (for the constellation config) and all .yml (for the chip configs) files with the same timestamp in the same directory as the binary file. If they are not found, the metadata is not written
        """

        self.bin_file = open(bin_filename, 'rb')
        self.max_nreadouts = max_nreadouts
        self.verbose = verbose
        self.chip_version = chip_version
        self.fpga_ts_clock_freq = fpga_ts_clock_freq
        self.fpga_ts_length = fpga_ts_length
        self.nlayers = nlayers
        self.nchips_per_layer = nchips_per_layer
        self.count_skipped_bytes = 0
        self.count_total_bytes = 0
        self.root_file = None 
        self.h5_file = None
        self.stats = Stats(self.chip_version, self.fpga_ts_length)
        if self.verbose:
            print(f'Decoding {bin_filename}')

        if constellation_config_filename is not None and self.verbose:
            print(f'Using provided constellation config file: {constellation_config_filename}')

        if chip_config_filenames is not None and self.verbose:
            print(f'Using provided chip config files: {chip_config_filenames}')

        if constellation_config_filename is None or chip_config_filenames is None:
            run_id = bin_filename.split('/')[-1].replace('.bin', '')
            bin_directory = '/'.join(bin_filename.split('/')[:-1])
            same_id_files = [filename for filename in os.listdir(bin_directory) if len(filename.split('.')) > 1 and filename.split('.')[-2].endswith(run_id)]

            def find_fitting_file(file_extension):
                fitting_filenames = [filename for filename in same_id_files if filename.endswith(file_extension)]
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
        self.read_configs()
        self.hits = []
        self.halfhits = []
        self.fpga_ts_lengths = []
        self.leftovers = bytes()

    def read_configs(self):
        if self.constellation_config_filename is not None:
            with open(self.constellation_config_filename, 'r') as f:
                self.constellation_config = toml.load(f)
        else:
            self.constellation_config = None

        if self.chip_config_filenames is not None:
            self.chip_config = {}
            for filename in self.chip_config_filenames:
                with open(filename, "r", encoding="utf-8") as stream:
                    key_for_dict = '_'.join(filename.split('/')[-1].replace('.yml', '').split('_')[:-1])
                    self.chip_config[key_for_dict] = yaml.safe_load(stream)
        else:
            self.chip_config = None

    def prepare_root_file(self, filename):
        self.root_filename = filename
        self.root_file = uproot.recreate(filename)
        if self.chip_version == 3:
            self.root_file.mktree('hits', {key : [] for key in Hit_v3().__dict__})
            self.root_file.mktree('halfhits', {key : [] for key in HalfHit_v3().__dict__})

        if self.chip_version == 4:
            self.root_file.mktree('hits', {key : [] for key in Hit_v4(True).__dict__})

    def prepare_h5_file(self, filename):
        self.h5_filename = filename
        self.h5_file =  h5py.File(filename, 'w')
        self.h5_dataset = self.h5_file.create_dataset("Hits",  
                                                        shape=(0, ), 
                                                        maxshape=(None, ), 
                                                        chunks=True,
                                                        dtype=HIT_TYPE
                                                        )

    def OLD_write_hits_to_file(self, filename):
        if self.verbose:
            print(f'Writing data to  {filename}:')
            print(f'{len(self.hits)} hits')
            if self.chip_version == 3:
                print(f'{len(self.halfhits)} halfhits')
                print(f'ratio of hits to halfhits = {len(self.hits)/len(self.halfhits) if len(self.halfhits) != 0 else np.inf}')
                col_hh = [hh for hh in self.halfhits if hh.isCol]
                print(f'ratio of column to row halfhits = {len(col_hh)/(len(self.halfhits) - len(col_hh)) if len(self.halfhits) != len(col_hh) else np.inf} ({len(col_hh)} col halfhits and {len(self.halfhits) - len(col_hh)} row halfhits)')
            if self.fpga_ts_length is None:
                print(f'Derived FPGA timestamp length {int(np.median(self.fpga_ts_lengths)) if len(self.fpga_ts_lengths) != 0 else None} bytes')
            else:
                print(f'Provided FPGA timestamp length {self.fpga_ts_length} bytes')
            print(f'{self.count_skipped_bytes} bytes skipped while decoding out of {self.count_total_bytes} bytes of data ({self.count_skipped_bytes/self.count_total_bytes*100}%)')
            

        if '.root' in filename:
            self.write_hits_to_root_file(filename)
        elif '.h5' in filename:
            self.write_hits_to_hdf5_file(filename)
        else:
            print(f'ERROR! Unknown file extension in {filename}, only .root and .h5 are currently recognized')

    def OLD_write_hits_to_root_file(self, filename, make_histograms=True):
        if make_histograms:
            print('Filling histograms...')
            histogram_filler = HistogramFiller(self, self.verbose)
            histogram_filler.fill_histograms()
            print('... done!')

        with uproot.recreate(filename) as root_file:
            result_dict = {}
            if len(self.hits) != 0:
                for hit in self.hits:
                    hit.get_dict()
                for attr in self.hits[0].get_dict().keys():
                    result_dict[attr] = [getattr(hit, attr) for hit in self.hits]
            root_file['hits'] = result_dict


            if self.chip_version == 3:
                result_dict_hh = {}
                for attr in HalfHit_v3().get_dict().keys():
                    if attr == 'tot_us':
                        continue
                    result_dict_hh[attr] = [getattr(halfhit, attr) for halfhit in self.halfhits]

                root_file['halfhits'] = result_dict_hh

            #if self.constellation_config is not None:
            #    root_file['constellation_config'] = prepare_dict_for_root(self.constellation_config)

            #if self.chip_config is not None:
            #    root_file['chip_config'] = prepare_dict_for_root(self.chip_config)

            if make_histograms:
                hists = histogram_filler.get_histograms()
                for key in hists:
                    root_file[f'histograms/{key}'] = hists[key]

    def OLD_write_hits_to_hdf5_file(self, filename):
        HIT_TYPE = np.dtype([
            ('column', 'i4'),
            ('row', 'i4'),
            ('raw', 'i4'),
            ('charge', 'd'),
            ('timestamp', 'd'),
            ('trigger_number', 'u4')
        ])
        print(f'{len([1 for hit in self.hits if hit.fpga_ts < 0.01])} hits with fpga_ts == 0')
        if self.chip_version == 4:
            for hit in self.hits:
                hit.get_dict()
        hit_filter = HitFilter([hit for hit in self.hits if hit.fpga_ts > 0.1])
        hit_filter.filter(always_ok=False)
        if self.verbose:
            print(f'{len(hit_filter.hits)} hits before filtering, {len(hit_filter.filtered_hits)} hits after filtering ({len(hit_filter.hits) - len(hit_filter.filtered_hits)} hits filtered out = {(len(hit_filter.hits) - len(hit_filter.filtered_hits))/len(hit_filter.hits)})')
            ts_diff = (hit_filter.filtered_hits[-1].fpga_ts - hit_filter.filtered_hits[0].fpga_ts) / self.fpga_ts_clock_freq
            print(f'{ts_diff} s between the lowest and the highest FPGA timestamp. Rate is ~{len(hit_filter.filtered_hits)/ts_diff} hits/s')
        #data_hits = np.array(
        #    [(hit.col, hit.row, hit.tot, hit.tot_us, hit.fpga_ts / self.fpga_ts_clock_freq * 1e9, 0) for hit in self.hits if hit.fpga_ts > 0.1], dtype=HIT_TYPE
        #) # fpga_ts in ns
        data_hits = np.array(
            [(hit.col, hit.row, hit.tot_total, hit.tot_us, hit.fpga_ts / self.fpga_ts_clock_freq * 1e9, 0) for hit in hit_filter.filtered_hits], dtype=HIT_TYPE
        ) # fpga_ts in ns
        with h5py.File(filename, 'w') as hdf5_file:
            dset = hdf5_file.create_dataset("Hits", data=data_hits)

    def write_hits(self):
        if self.root_file is not None:
            if self.chip_version == 3:
                hit_dict = {key : [getattr(hit, key) for hit in self.hits] for key in Hit_v3().__dict__}
                for hh in self.halfhits:
                    hh.get_dict()
                halfhit_dict = {key : [getattr(hh, key) for hh in self.halfhits] for key in HalfHit_v3().__dict__}
                self.root_file['hits'].extend(hit_dict)
                self.root_file['halfhits'].extend(halfhit_dict)
            elif self.chip_version == 4:
                for hit in self.hits:
                    hit.get_dict()
                hit_dict = {key : [getattr(hit, key) for hit in self.hits] for key in Hit_v4(True).__dict__}
                self.root_file['hits'].extend(hit_dict)
        if self.h5_file is not None:
            hit_filter = HitFilter(self.hits, self.previous_good_fpga_timestamp)
            hit_filter.filter(always_ok=False)
            self.previous_good_fpga_timestamp = hit_filter.last_good_fpga_timestamp
            self.stats.filtered_hit_count += hit_filter.total_filtered_hits
            self.stats.zero_ts_hit_count += hit_filter.zero_ts_hits
            current_rows = self.h5_dataset.shape[0]
            self.h5_dataset.resize((current_rows + len(hit_filter.filtered_hits), ))
            self.h5_dataset[current_rows:] = np.array(
                [(hit.col, hit.row, hit.tot_total, hit.tot_us, 1.*hit.fpga_ts / self.fpga_ts_clock_freq * 1e9, 0) for hit in hit_filter.filtered_hits], dtype=HIT_TYPE
            ) # fpga_ts in ns
            self.h5_file.flush()

        if self.stats.first_timestamp is None:
            self.stats.first_timestamp = self.hits[0].fpga_ts / self.fpga_ts_clock_freq * 1e9
        self.stats.last_timestamp = self.hits[-1].fpga_ts / self.fpga_ts_clock_freq * 1e9
        self.stats.hit_count += len(self.hits)
        self.stats.row_halfhit_count += len([1 for hh in self.halfhits if not hh.isCol])
        self.stats.col_halfhit_count += len([1 for hh in self.halfhits if hh.isCol]) 
        self.hits.clear()
        self.halfhits.clear()



    def decode(self):
        readout_id = 0
        block_lengths = []
        self.previous_good_fpga_timestamp = None
        if self.root_file is None and self.h5_file is None:
            print('WARNING! No files set up for writing, no output file will be created!!!')
        try:
            while True:
                block = self.read_block()
                if block is None:
                    break
                readout_id += 1
                hit_packets = self.split_packets(block)

                decoded_packets = [self.decode_packet(packet, readout_id) for packet in hit_packets]
                decoded_packets = [decoded_packet for decoded_packet in decoded_packets if decoded_packet is not None]
                if self.chip_version == 3:
                    self.halfhits += decoded_packets
                    matcher = Matcher(decoded_packets)
                    matcher.match(strategy='all_all')
                    self.hits += matcher.hits
                    if len(self.halfhits) > 1e6:
                        self.write_hits()     
                elif self.chip_version == 4:
                    self.hits += decoded_packets

                if self.verbose:
                    block_lengths.append(len(block))
                    if readout_id % 100 == 0:
                        print(f'Read {readout_id} readout blocks, average block length is {np.mean(block_lengths)}')
                        block_lengths = []

                if self.max_nreadouts is not None and readout_id >= self.max_nreadouts:
                    if self.verbose:
                        print(f'Reached {self.max_nreadouts} readouts, stopping')
                    break
        except KeyboardInterrupt:
            pass
        self.write_hits()
        if self.root_file is not None:
            self.root_file.close()
            print(f'Wrote data to the .root file {self.root_filename}')
        if self.h5_file is not None:
            self.h5_file.close()
            print(f'Wrote data to the .h5 file {self.h5_filename}')
        if self.verbose:
            print(f'{readout_id} readout blocks read in total')
            self.stats.print()


    def read_block(self):
        read_int = self.bin_file.read(2)
        if len(read_int) == 0:
            return None
        nbits = int.from_bytes(read_int, "little")
        result_block = self.bin_file.read(nbits)
        self.stats.total_byte_count += len(result_block)
        return result_block


    def check_packet(self, packet):
        if len(packet) - 1 != int(packet[0]):
            return False
        if self.chip_version == 3:
            if self.fpga_ts_length is None and len(packet) not in [9, 11, 13, 15]:
                return False
            if self.fpga_ts_length is not None and len(packet) - 7 != self.fpga_ts_length:
                return False
            layer = int(packet[1])
            # byte 2 is a header. 3 bit payload, 5 bit chip id
            byte = int(packet[2])
            chip_id = byte >> 3
            payload = byte & 0b00000111
            if self.nlayers is not None and layer > self.nlayers:
                return False
            if self.nchips_per_layer is not None and chip_id >= self.nchips_per_layer:
                return False
            if payload != 4:
                return False
        if self.chip_version == 4:
            if self.fpga_ts_length is None and len(packet) not in [12, 14, 16, 18]:
                return False
            if self.fpga_ts_length is not None and len(packet) - 10 != self.fpga_ts_length:
                return False
            layer = int(packet[1])
            # byte 2 is a header. 3 bit payload, 5 bit chip id
            byte = int(packet[2])
            chip_id = byte >> 3
            payload = byte & 0b00000111
            if self.nlayers is not None and layer > self.nlayers:
                return False
            if self.nchips_per_layer is not None and chip_id >= self.nchips_per_layer:
                return False
            if payload != 7:
                return False
        return True


    def split_packets(self, byte_block):
        result_packets = []
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

    def decode_packet(self, hit_packet, readout_id):
        if self.chip_version == 3:
            return self.decode_packet_v3(hit_packet, readout_id)
        if self.chip_version == 4:
            return self.decode_packet_v4(hit_packet, readout_id)

    def check_halfhit(self, halfhit):
        #print('Checking halfhit')
        #print(f'{self.nlayers} >= {halfhit.layer}?')
        #print(f'{self.nchips_per_layer} > halfhit.chip_id?')
        #print(f'{halfhit.payload} == 4?')
        if self.nlayers is not None and halfhit.layer > self.nlayers:
            return False
        if self.nchips_per_layer is not None and halfhit.chip_id >= self.nchips_per_layer:
            return False
        if halfhit.payload != 4:
            return False
        return True

    def decode_packet_v3(self, hit_packet, readout_id):
        if len(hit_packet) > 15:
            print(f'ERROR, hit packet too long ({len(hit_packet)}), probably something went wrong with splitting packets')
            return
        self.fpga_ts_lengths.append(len(hit_packet) - 7)
        try:
            halfhit = HalfHit_v3()
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
            # bytes 7-end are the FPGA timestamp
            halfhit.fpga_ts = np.uint64(int.from_bytes(hit_packet[len(hit_packet) - self.fpga_ts_length:], 'big'))

            # constructing ToT total
            halfhit.tot_total = (halfhit.tot_msb << 8) + halfhit.tot_lsb

            halfhit.readout_id = readout_id

            return halfhit
        except IndexError:
            return None

    def decode_packet_v4(self, hit_packet, readout_id):
        if len(hit_packet) > 18:
            print(f'ERROR, hit packet too long ({len(hit_packet)}), probably something went wrong with splitting packets')
            return
        self.fpga_ts_lengths.append(len(hit_packet) - 10)
        try:
            hit = Hit_v4(use_negedge_ts=True)
            # byte 0 = length of the packet
            hit.packet_length = int(hit_packet[0])
            # byte 1 = layer
            hit.layer = int(hit_packet[1])
            # byte 2 is a header. 3 bit payload, 5 bit chip id
            byte = int(hit_packet[2])
            hit.chip_id = byte >> 3
            hit.payload = byte & 0b00000111
            # byte 3 and part of byte 4 is hit location
            byte3 = int(hit_packet[3])
            byte4 = int(hit_packet[4])
            hit.row = byte3 >> 3
            hit.col = ((byte3 & 0b111) << 2) + (byte4 >> 6)
            #
            hit.ts1_neg      = (int(hit_packet[4]) >> 5) & 0b1
            hit.ts1         = ((int(hit_packet[4]) & 0b11111) << 9) + (int(hit_packet[5]) << 1) + (int(hit_packet[6]) >> 7)
            hit.ts1_fine     = (int(hit_packet[6]) >> 4) & 0b111
            hit.ts1_tdc      = ((int(hit_packet[6]) & 0b1111) << 1) + (int(hit_packet[7]) >> 7)
            #
            hit.ts2_neg      = (int(hit_packet[7]) >> 6) & 0b1
            hit.ts2         = ((int(hit_packet[7]) & 0b111111) << 8) + int(hit_packet[8])
            hit.ts2_fine     = (int(hit_packet[9]) >> 5) & 0b111
            hit.ts2_tdc      = int(hit_packet[9]) & 0b11111

            hit.fpga_ts = np.uint64(int.from_bytes(hit_packet[10:], 'big'))

            hit.readout_id = readout_id

            return hit
        except IndexError:
            return None

from common import Stats, DecoderSettings
from hit_classes import HIT_TYPE



class DecoderBase:
    def __init__(self, bin_filename, stats: Stats, decoder_settings: DecoderSettings):
        self.bin_file = open(bin_filename, 'rb')

        self.decoder_settings = decoder_settings 
        self.stats = stats

        # Leftover bytes from package splitting
        # Sometimes one packet is split between two FPGA readout buffers
        self.leftovers = bytes()

        # Last FPGA timestamp for filtering
        self.last_good_fpga_ts = 0

        # number of the last readout block
        self.last_readout_id = 0

        self.h5_file_hits: h5py.File | None = None
        self.h5_dataset_hits: h5py.Dataset | None = None

        self.root_file: uproot.File | None = None

        self.find_configs(bin_filename=bin_filename)

    def flatten(self, to_flatten):
        result_dict = {}
        if isinstance(to_flatten, dict):
            for_iter = to_flatten.keys()
        elif isinstance(to_flatten, list):
            for_iter = range(len(to_flatten))
        else:
            return to_flatten

        for i in for_iter:
            flat = self.flatten(to_flatten[i])
            if not isinstance(flat, dict):
                result_dict[f'{i}'] = flat
            else:
                for new_key in flat:
                    result_dict[f'{i}/{new_key}'] = flat[new_key]
        return result_dict

    def prepare_dict_for_root(self, dict_to_prepare):
        result_dict = self.flatten(dict_to_prepare)
        for key in result_dict:
            result_dict[key] = [result_dict[key]]
        return result_dict

    def find_configs(self, bin_filename):
        # the chip config and the constellation config should be in the same directory as the raw data
        # they should also contain the run id in the name
        run_id = bin_filename.split('/')[-1].replace('.bin', '')
        bin_directory = '/'.join(bin_filename.split('/')[:-1])

        def find_fitting_file(file_extension):
            fitting_files = [filename for filename in os.listdir(bin_directory) if filename.endswith(run_id + '.' + file_extension)]
            if len(fitting_files) == 0:
                if self.verbose:
                    print(f'.{file_extension} file could not be found automatically')
                return None 
            elif len(fitting_files) > 1:
                if self.verbose:
                    print(f'Multiple .{file_extension} files could be the config, so leaving it empty')
                    print(f'Possible configs: {fitting_files}')
                return None 
            else:
                if self.verbose:
                    print(f'.{file_extension} config found: {fitting_files[0]}')
                return bin_directory + '/' + fitting_files[0]

        self.constellation_config = find_fitting_file('toml')
        self.chip_config = find_fitting_file('yml')


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

    def prepare_h5_file(self, filename):
        self.h5_file_hits =  h5py.File(filename, 'w')
        self.h5_dataset_hits = self.h5_file_hits.create_dataset("Hits",
                                                                    shape=(0, ),
                                                                    maxshape=(None, ),
                                                                    chunks=True,
                                                                    dtype=HIT_TYPE
                                                                    )

    def prepare_root_file(self, filename):
        self.root_filename = filename
        self.root_file = uproot.recreate(filename)
        self.read_configs()
        if self.constellation_config is not None:
            root_file['constellation_config'] = prepare_dict_for_root(self.constellation_config)

        if self.chip_config is not None:
            root_file['chip_config'] = prepare_dict_for_root(self.chip_config)

    def read_block(self):
        read_int = self.bin_file.read(2)
        if len(read_int) == 0:
            return None
        nbits = int.from_bytes(read_int, "little")
        result_block = self.bin_file.read(nbits)
        self.stats.total_byte_count += len(result_block)
        return result_block

    def split_packets(self, byte_block: bytes) -> list[bytes]:
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
            elif i + packet_length + 1 >= len(new_byte_block):
                self.leftovers = packet
                break
            else:
                self.stats.skipped_byte_count += 1
                i += 1
        return result_packets

    def write_hits(self):
        if self.h5_file_hits is not None:
            assert self.h5_dataset_hits
            current_rows = self.h5_dataset_hits.shape[0]
            self.h5_dataset_hits.resize((current_rows + len(self.hits), ))
            self.h5_dataset_hits[current_rows:] = np.array(
                [(hit.col, hit.row, hit.tot_raw, hit.tot_us, float(hit.fpga_ts) / self.decoder_settings.fpga_ts_clock_freq * 1e9, 0) for hit in self.hits], dtype=HIT_TYPE
            )
            self.h5_file.flush()

        if self.stats.first_fpga_timestamp is None:
            self.stats.first_fpga_timestamp = float(self.hits[0].fpga_ts) / self.decoder_settings.fpga_ts_clock_freq * 1e9
        self.stats.last_fpga_timestamp = self.hits[-1].fpga_ts / self.decoder_settings.fpga_ts_clock_freq * 1e9
        self.hits.clear()

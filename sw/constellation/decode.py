from constellation.decoder_v3 import Decoder_v3
from constellation.common import DecoderSettings, Stats, MatcherStrategy
import argparse
import os

def decode(filename, force, file_extensions, chip_version, fpga_ts_length, nchips_per_layer, nlayers, outdir):
    os.makedirs('/'.join(filename.split('/')[:-1]), exist_ok=True)

    if outdir is None:
        name_output = filename.replace('raw_data', 'decoded')
    else:
        name_output = outdir
        if not name_output.endswith('/'):
            name_output += '/'
        name_output += filename.split('/')[-1]

    if not force:
        all_files_exist = True
        for file_extension in file_extensions:
            if not os.path.exists(name_output.replace('.bin', file_extension)):
                all_files_exist = False
        if all_files_exist:
            print(f'File decoded with all ({file_extensions}) extensions, skipping')
            return

    stats = Stats()
    
    if chip_version == 3:
        decoder_settings = DecoderSettings(
            nlayers=nlayers,
            nchips_per_layer=nchips_per_layer,
            fpga_ts_length=fpga_ts_length,
            fpga_ts_clock_freq=80e6,
            fpga_ts_hh_filter_limit = 100000, # 100ks aka ~28h
            fpga_ts_matching_limit=3e-3, # 3ms
            matcher_strategy=MatcherStrategy.ALL,
            matcher_ts_limit=2, # clk cycles
            matcher_tot_limit=0.2 # 20%
        )
        d = Decoder_v3(filename, stats, decoder_settings)
    else:
        raise ValueError(f"Decoder is not (yet) defined for chip version {chip_version}")
    if '.root' in file_extensions:
        d.prepare_root_file(name_output.replace('.bin', '.root'))
    if '.h5' in file_extensions:
        d.prepare_h5_file(name_output.replace('.bin', '.h5'))
    d.decode()
    # for file_extension in file_extensions:
    #     d.write_hits_to_file(name_output.replace('.bin', file_extension))

def main(args):
    if args.name is None and args.dir is None:
        print('No -n and no -d arguments passed, nothing to decode')
        return

    if not args.h5 and not args.root:
        print('Specify the format of the output file (--root or --h5 or both)')
        return

    if args.name is not None and args.dir is not None:
        print('Choose either -n or -d to decode, you cannot have both')
        return

    if args.name is not None:
        filenames = [args.name]
    else:
        print(f'Decoding directory {args.dir}')
        filenames = [f'{args.dir}/{filename}' for filename in os.listdir(args.dir) if filename.endswith('.bin')]

    for filename in filenames:
        print(f'Decoding file {filename}')
        file_extensions = []
        if args.h5:
            file_extensions.append('.h5')
        if args.root:
            file_extensions.append('.root')
        decode(filename, args.force, file_extensions, args.version, fpga_ts_length=args.fpga_ts_length, nchips_per_layer=args.nchips_per_layer, nlayers=args.nlayers, outdir=args.outdir)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Astropix Driver Code')
    parser.add_argument('-n', '--name', required=False, default=None,
                  help='Name of the file to decode')
    parser.add_argument('-d', '--dir', required=False, default=None, help='Directory with files to decode')
    parser.add_argument('-f', '--force', required=False, default=False, action='store_true', help='Decode even if files exist already')
    parser.add_argument('-h5', '--h5', required=False, default=False, action="store_true", help='Write the decoded output into an h5 file')
    parser.add_argument('-root', '--root', required=False, default=False, action="store_true", help='Write the decoded output into a root file')
    parser.add_argument('-v', '--version', required=True, help='Chip version', type=int)
    parser.add_argument('--fpga_ts_length', required=False, help='Length of the FPGA imestamp in bytes', type=int, default=8)
    parser.add_argument('--nchips_per_layer', required=False, help='Number of chips per layer', type=int, default=1)
    parser.add_argument('--nlayers', required=False, help='Number of layers', type=int, default=1)
    parser.add_argument('-o', '--outdir', required=False, help='Directory for the output file', default=None)

    args = parser.parse_args()
    main(args)

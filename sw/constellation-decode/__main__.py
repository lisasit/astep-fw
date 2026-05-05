import argparse
import os

from .decoder_v3 import Decoder_v3
from .decoder_v4 import Decoder_v4
from .common import DecoderSettings_v3, DecoderSettings_v4, Stats_v3, Stats_v4, MatcherStrategy

def decode(filename, force, file_extensions, chip_version, fpga_ts_length, nchips_per_layer, nlayers, outdir, max_readout_blocks, write_strip_files, matcher_strategy, use_tlu):
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

    if chip_version == 3:
        stats = Stats_v3()
        decoder_settings = DecoderSettings_v3(
            nlayers=nlayers,
            nchips_per_layer=nchips_per_layer,
            fpga_ts_length=fpga_ts_length,
            fpga_ts_clock_freq=80e6,
            fpga_ts_packet_filter_limit = None,#100000, # 100ks aka ~28h
            fpga_ts_matching_limit=args.matcher_time_window,
            matcher_strategy=matcher_strategy,
            matcher_ts_limit=args.matcher_ts_limit,
            matcher_tot_limit=args.matcher_tot_limit,
            max_readout_blocks=max_readout_blocks,
            write_strip_files=write_strip_files,
            use_tlu=use_tlu
        )
        d = Decoder_v3(filename, stats, decoder_settings)
    else:
        stats = Stats_v4()
        decoder_settings = DecoderSettings_v4(
            nlayers=nlayers,
            nchips_per_layer=nchips_per_layer,
            fpga_ts_length=fpga_ts_length,
            fpga_ts_clock_freq=80e6,
            fpga_ts_packet_filter_limit = None,#100000, # 100ks aka ~28h
            max_readout_blocks=max_readout_blocks,
            use_tlu=use_tlu
        )
        d = Decoder_v4(filename, stats, decoder_settings)
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

    if args.matcher_strategy == 'all':
        matcher_strategy = MatcherStrategy.ALL
    elif args.matcher_strategy == 'closest':
        matcher_strategy = MatcherStrategy.CLOSEST
    elif args.matcher_strategy == 'closest_rowfirst':
        matcher_strategy = MatcherStrategy.CLOSEST_ROWFIRST
    else:
        print('Invalid matcher strategy, use either `all`, `closest` or `closest_rowfirst`')
        return

    for filename in filenames:
        print(f'Decoding file {filename}')
        file_extensions = []
        if args.h5:
            file_extensions.append('.h5')
        if args.root:
            file_extensions.append('.root')
        decode(filename, args.force, file_extensions, args.version, fpga_ts_length=args.fpga_ts_length, nchips_per_layer=args.nchips_per_layer, nlayers=args.nlayers, outdir=args.outdir, max_readout_blocks=args.max_readout_blocks, write_strip_files=args.write_strip_files, matcher_strategy=matcher_strategy, use_tlu=args.use_tlu)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Astropix Driver Code')
    parser.add_argument('-n', '--name', required=False, default=None,
                  help='Name of the file to decode')
    parser.add_argument('-d', '--dir', required=False, default=None, help='Directory with files to decode')
    parser.add_argument('-f', '--force', required=False, default=False, action='store_true', help='Decode even if files exist already')
    parser.add_argument('-h5', '--h5', required=False, default=False, action="store_true", help='Write the decoded output into an h5 file')
    parser.add_argument('-root', '--root', required=False, default=False, action="store_true", help='Write the decoded output into a root file')
    parser.add_argument('-v', '--version', required=True, help='Chip version', type=int)
    parser.add_argument('--fpga-ts-length', required=False, help='Length of the FPGA imestamp in bytes', type=int, default=8)
    parser.add_argument('--nchips-per-layer', required=False, help='Number of chips per layer', type=int, default=1)
    parser.add_argument('--nlayers', required=False, help='Number of layers', type=int, default=1)
    parser.add_argument('-o', '--outdir', required=False, help='Directory for the output file', default=None)
    parser.add_argument('-m', '--max-readout-blocks', required=False, help='Max number of readout blocks to process (for debugging mostly)', type=int, default=None)
    parser.add_argument('-s', '--write-strip-files', required=False, action="store_true", default=False, help="Save the \"strip\" h5 files, where row and column halfhits are treated as hits in two separate strip detectors")
    parser.add_argument('-t', '--use-tlu', required=False, action="store_true", default=False, help="Flag to indicate that the TLU was used. This means that the FPGA timestamp does not grow monotonously, but drops to 0 when the T0 signal from the TLU is received")
    parser.add_argument('--matcher-strategy', required=False, type=str, default='all', help="Strategy to use for matching (v3 only)")
    parser.add_argument('--matcher-ts-limit', required=False, type=int, default=2, help="Maximum chip timestamp difference in clock cycles for matching (v3 only)")
    parser.add_argument('--matcher-tot-limit', required=False, default=None, type=float, help="Relative ToT limit for matching (v3 only). If used, only halfhits whose ToT deviates at most by the given limit will be considerd for matching, otherwise ToT matching is disabled")
    parser.add_argument('--matcher-time-window', required=False, type=float, default=3e-3, help="Time window for matching in seconds (v3 only)")

    args = parser.parse_args()
    main(args)

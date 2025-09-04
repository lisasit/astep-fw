from constellation.binary_decoder import Decoder
import argparse
import os

def decode(filename, force, max_nreadouts):
  name_root = filename.replace('.bin', '.root')
  name_root = name_root.replace('raw_data', 'decoded')
  if not force and os.path.exists(name_root):
      print('File decoded, skipping')
      return
  
  os.makedirs('/'.join(name_root.split('/')[:-1]), exist_ok=True)
  
  d = Decoder(filename, max_nreadouts=max_nreadouts)
  d.decode()
  d.write_hits_to_file(name_root)

if __name__ == "__main__":

  parser = argparse.ArgumentParser(description='Astropix Driver Code')
  parser.add_argument('-n', '--name', required=False, default=None,
                  help='Name of the file to decode')
  parser.add_argument('-d', '--dir', required=False, default=None, help='Directory with files to decode')
  parser.add_argument('-f', '--force', required=False, default=False, action='store_true', help='Decode even if files exist already')
  parser.add_argument('-m', '--max-nreadouts', required=False, default=None, help='Maximum number of readout blocks per file to decode')
  
  args = parser.parse_args()
  if args.max_nreadouts is not None:
      args.max_nreadouts = int(args.max_nreadouts)
  if args.name is None and args.dir is None:
      print('No -n and no -d arguments passed, nothing to decode')
  if args.name is not None and args.dir is not None:
      print('Choose either -n or -d to decode, you cannot have both')
  elif args.name is not None:
      filenames = [args.name]
  elif args.dir is not None:
      print(f'Decoding directory {args.dir}')
      filenames = [f'{args.dir}/{filename}' for filename in os.listdir(args.dir) if filename.endswith('.bin')]
for filename in filenames:
    print(f'Decoding file {filename}')
    decode(filename, args.force, args.max_nreadouts)

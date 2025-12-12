import numpy as np
import hist
from hist import Hist
import json

class HistogramFiller:
    def __init__(self, decoder, verbose=False):
        self.decoder = decoder
        self.verbose = verbose
        self.derive_chip_configuration()
        self.hitmaps = [[Hist(
            hist.axis.Regular(35, 0, 35, name="col"),
            hist.axis.Regular(35, 0, 35, name="row")
            ) for i in range(self.nchips_per_layer)] for j in range(self.nlayers)]

    def fill_histograms(self):
        self.fill_hitmap_histogram()

    def derive_chip_configuration(self):
        if self.decoder.chip_config is None:
            if self.verbose:
                print('No chip config, so assuming the default configuration with 1 chip')
            self.nlayers = 1
            self.nchips_per_layer = 1
        else:
            self.nlayers = len(self.decoder.chip_config)
            first_config = self.decoder.chip_config[list(self.decoder.chip_config.keys())[0]]['astropix3'] # TODO change for other versions???
            self.nchips_per_layer = len([key for key in first_config if 'config' in key])
            if self.verbose:
                print(f'Derived configuration from the config file(s): {self.nlayers} layers, each with {self.nchips_per_layer} chips')

    def get_masks(self):
        self.masks = [[np.full((35, 35), 0) for i in range(self.nchips_per_layer)] for j in range(self.nlayers)]
        if self.decoder.chip_config is not None:
            for ilayer in range(self.nlayers):
                layer_key = [key for key in self.decoder.chip_config if f'layer{ilayer}' in key][0]
                layer_config = self.decoder.chip_config[layer_key]['astropix3'] # TODO change for other versions???
                for ichip in range(self.nchips_per_layer):
                    chip_config = layer_config[f'config_{ichip}']['recconfig']
                    for col in range(35):
                        col_mask = chip_config[f'col{col}'][1]
                        for row in range(35):
                            if col_mask & 2**(1 + row):
                                self.masks[ilayer][ichip][col, row] = 1

    def fill_hitmap_histogram(self):
        self.get_masks()
        for hit in self.decoder.hits:
            self.hitmaps[0][0].fill(hit.col, hit.row)
        # for ilayer in range(self.nlayers):
        #     for ichip in range(self.nchips_per_layer):
        #         for row in range(35):
        #             for col in range(35):
        #                 if self.masks[ilayer][ichip][row, col]:
        #                     self.hitmaps[ilayer][ichip][col, row] = -1


    def get_histograms(self):
        result = {}
        for ilayer in range(self.nlayers):
            for ichip in range(self.nchips_per_layer):
                result[f'hitmap_layer{ilayer}_chip{ichip}'] = self.hitmaps[ilayer][ichip]

        return result

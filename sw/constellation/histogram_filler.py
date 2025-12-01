import numpy as np
import hist
from hist import Hist


class HistogramFiller:
    def __init__(self):
        self.hitmap = Hist(
            hist.axis.Regular(35, 0, 35, name="col"),
            hist.axis.Regular(35, 0, 35, name="row")
            )

    def fill_histograms(self, hits):
        self.fill_hitmap_histogram(hits)

    def fill_hitmap_histogram(self, hits):
        for hit in hits:
            self.hitmap.fill(hit.col, hit.row)

    def get_dict(self):
        return self.__dict__

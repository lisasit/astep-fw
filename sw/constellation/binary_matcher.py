

class Hit:
    def __init__(self):
        self.row = None
        self.col = None
        self.timestamp = None
        self.readout_id = None
        self.payload = None
        self.chip_id = None
        self.tot_us = None
        self.fpga_ts

    def get_dict(self):
        return self.__dict__

class Matcher:
    def __init__(self, halfhits, timestamp_tolerance=1, tot_us_tolerance=0.5):
        """
        halfhits: list of halfhits for matching
        timestamp_tolerance: the maximum difference between the timestamps of halfhits that are matched
        tot_us_tolerance: the maximum difference between the tot in us for the halfhits that are matched
        """
        self.row_halfhits = [halfhit for halfhit in halfhits if not halfhit.isCol]
        self.col_halfhits = [halfhit for halfhit in halfhits if halfhit.isCol]
        self.timestamp_tolerance = timestamp_tolerance
        self.tot_us_tolerance = tot_us_tolerance
        self.hits = []

    def calculate_chi2(self, one_halfhit, other_halfhit):
        chi2 = 0
        if one_halfhit.get_tot_us() != 0:
            chi2 += abs(other_halfhit.get_tot_us() - one_halfhit.get_tot_us())
        return chi2

    def find_match(self, halfhit):
        if halfhit.isCol:
            other_halfhits = self.row_halfhits
        else:
            other_halfhits = self.col_halfhits

        def check_timestamps(halfhit, other_halfhit, tolerance):
            if abs(other_halfhit.timestamp - halfhit.timestamp) <= tolerance:
                return True
            if abs(abs(other_halfhit.timestamp - halfhit.timestamp) - 256) <= tolerance:
                return True
            return False

        for tolerance in range(self.timestamp_tolerance + 1):
            matches = [other_halfhit for other_halfhit in other_halfhits if check_timestamps(halfhit, other_halfhit, tolerance) and abs(other_halfhit.get_tot_us() - halfhit.get_tot_us()) < self.tot_us_tolerance]
            if len(matches) == 0:
                continue
            if len(matches) > 1:
                matches = sorted(matches, key=lambda x: self.calculate_chi2(halfhit, x))
            return matches[0]
        return None


    def match(self):
        for row_halfhit in self.row_halfhits:
            col_halfhit = self.find_match(row_halfhit)
            if col_halfhit is not None:
                hit = Hit()
                hit.row = row_halfhit.location
                hit.col = col_halfhit.location
                hit.timestamp = (row_halfhit.timestamp + col_halfhit.timestamp)//2
                hit.readout_id = row_halfhit.readout_id
                hit.payload = row_halfhit.payload
                hit.chip_id = row_halfhit.chip_id
                hit.tot_us = (row_halfhit.get_tot_us() + col_halfhit.get_tot_us())/2
                hit.fpga_ts = (row_halfhit.fpga_ts + col_halfhit.fpga_ts)//2
                self.hits.append(hit)

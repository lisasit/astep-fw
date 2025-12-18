

from hit_classes import Hit_v3

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

    def find_match_mult(self, halfhit):
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

        matches = [other_halfhit for other_halfhit in other_halfhits if check_timestamps(halfhit, other_halfhit, self.timestamp_tolerance) and abs(other_halfhit.get_tot_us() - halfhit.get_tot_us()) < self.tot_us_tolerance]
        return matches

    def sort_matches(self, key_hh_type):
        if key_hh_type == 'row':
            key_hh = self.row_halfhits
            other_hh = self.col_halfhits
        else:
            key_hh = self.col_halfhits
            other_hh = self.row_halfhits

        matches = [[hh] for hh in key_hh]
        if len(matches) != 0:
            for hh in other_hh:
                match_i = min(range(len(matches)), key=lambda i: abs(matches[i][0].timestamp - hh.timestamp))
                matches[match_i].append(hh)
        return matches

    def make_hit(self, hh1, hh2):
        if hh1.isCol and not hh2.isCol:
            row_halfhit = hh2
            col_halfhit = hh1
        elif not hh1.isCol and hh2.isCol:
            row_halfhit = hh1
            col_halfhit = hh2
        else:
            print(f'Cannot make a hit out of halfhits with isCol = {hh1.isCol} and {hh2.isCol}')
        hit = Hit_v3()
        hit.row = row_halfhit.location
        hit.col = col_halfhit.location
        hit.timestamp = (row_halfhit.timestamp + col_halfhit.timestamp)//2
        hit.readout_id = row_halfhit.readout_id
        hit.payload = row_halfhit.payload
        hit.chip_id = row_halfhit.chip_id
        hit.tot_us = (row_halfhit.get_tot_us() + col_halfhit.get_tot_us())/2
        hit.tot = row_halfhit.tot_total
        hit.fpga_ts = row_halfhit.fpga_ts
        return hit

    def match(self, strategy='best_row'):
        """
        Makes a list of hits from the halfhits. Available strategies:
        best_row: for each row halfhit finds a best column halfhit within the provided timestamp and tot tolerances
        best_col: same, but finds a row hh for each col hh
        all_row: sorts all col hh to the row hh that fits best (one row hh can have multiple col hh matches, but each col hh has only one matching row hh)
        all_col: same, but row and col switch places (one col can have multiple row matches)
        """
        if 'best' in strategy:
            if strategy == 'best_row':
                for row_halfhit in self.row_halfhits:
                    col_halfhit = self.find_match(row_halfhit)
                    if col_halfhit is not None:
                        hit = self.make_hit(row_halfhit, col_halfhit)
                        self.hits.append(hit)
            elif strategy == 'best_col':
                for col_halfhit in self.col_halfhits:
                    row_halfhit = self.find_match(col_halfhit)
                    if row_halfhit is not None:
                        hit = self.make_hit(row_halfhit, col_halfhit)
                        self.hits.append(hit)
            else:
                print(f'Unrecognized trategy: {strategy}')
        
        if 'all' in strategy:
            if strategy == 'all_row':
                matches = self.sort_matches('row')
            elif strategy == 'all_col':
                matches = self.sort_matches('col')
            else:
                print(f'Unrecognized trategy: {strategy}')
            for match_group in matches:
                for match_hh in match_group[1:]:
                    self.hits.append(self.make_hit(match_group[0], match_hh))

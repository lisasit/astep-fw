

from hit_classes import Hit_v3

class Matcher:
    def __init__(self, halfhits, block_to_use, timestamp_tolerance=1, tot_us_tolerance=0.5):
        """
        halfhits: list of halfhits for matching
        timestamp_tolerance: the maximum difference between the timestamps of halfhits that are matched
        tot_us_tolerance: the maximum difference between the tot in us for the halfhits that are matched
        """
        i = 0
        for block_number in range(len(halfhits)):
            for hh in halfhits[block_number]:
                hh.index = i
                i += 1

        self.row_halfhits = [halfhit for halfhit in halfhits[block_to_use] if not halfhit.isCol]
        self.col_halfhits = [halfhit for halfhit in halfhits[block_to_use] if halfhit.isCol]
        self.row_halfhits_other = sum([[halfhit for halfhit in halfhits[block_number] if not halfhit.isCol] for block_number in range(len(halfhits))], [])
        self.col_halfhits_other = sum([[halfhit for halfhit in halfhits[block_number] if halfhit.isCol] for block_number in range(len(halfhits))], [])
        self.timestamp_tolerance = timestamp_tolerance
        self.tot_us_tolerance = tot_us_tolerance
        self.hits = []
        self.out_file = open('matches_run95.txt', 'a')
        self.out_file.write('Next block!')
        if len(halfhits[0]) == 0:
            self.out_file.write(' no halfhits\n')
        else:
            self.out_file.write(f' {halfhits[0][0].readout_id}\n')
        self.out_file.write('Halfhits:\n')
        self.row_format = "{:>8}  {:>3}  {:>5}  {:>10}  {:>10}  {:>20}  {:<10}\n"
        self.out_file.write(self.row_format.format("Index", "Loc", "isCol", "ToT", "ts", "fpga_ts", "matches"))

    def __del__(self):
        self.out_file.close()

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

    def check_timestamps(self, timestamp1, timestamp2, tolerance):
            if abs(timestamp1 - timestamp2) <= tolerance:
                return True
            if abs(abs(timestamp1 - timestamp2) - 256) <= tolerance:
                return True
            return False

    def find_ts_difference(self, timestamp1, timestamp2):
        return min(abs(timestamp1 - timestamp2), abs(abs(timestamp1 - timestamp2) - 256))

    def find_match_mult(self, halfhit):
        if halfhit.isCol:
            other_halfhits = self.row_halfhits
        else:
            other_halfhits = self.col_halfhits

        matches = [other_halfhit for other_halfhit in other_halfhits if self.check_timestamps(halfhit.timestamp, other_halfhit.timestamp, self.timestamp_tolerance) and abs(other_halfhit.get_tot_us() - halfhit.get_tot_us()) < self.tot_us_tolerance]
        return matches

    def is_possible_match(self, hh1, hh2):
        return True
        if hh1.isCol == hh2.isCol:
            return False
        if hh1.isCol and hh1.index < hh2.index:
            return False 
        if hh2.isCol and hh2.index < hh1.index:
            return False
        return True

    def sort_matches(self, key_hh_type):
        if key_hh_type == 'row':
            key_hh = self.row_halfhits_other
            other_hh = self.col_halfhits
        else:
            key_hh = self.col_halfhits_other
            other_hh = self.row_halfhits

        matches = [[hh] for hh in key_hh]
        if len(matches) != 0:
            for hh in other_hh:
                ts_differences = [self.find_ts_difference(hh.timestamp, match_group[0].timestamp) for match_group in matches if self.is_possible_match(hh, match_group[0])]
                if len(ts_differences) == 0:
                    continue
                min_ts_diff = min(ts_differences)
                matching_indices = [i for i in range(len(matches)) if self.find_ts_difference(hh.timestamp, matches[i][0].timestamp) == min_ts_diff]
                # matching_indices = [i for i in range(len(matches)) if self.find_ts_difference(hh.timestamp, matches[i][0].timestamp) <= self.timestamp_tolerance]
                for match_i in matching_indices:
                    matches[match_i].append(hh)
        return matches

    def make_hit(self, hh1, hh2, ref_hh_type):
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
        if ref_hh_type == 'row':
            ref_hh = row_halfhit
        elif ref_hh_type == 'col':
            ref_hh = col_halfhit
        else:
            print(f'Unknown reference halfhit type {ref_hh_type}')
        hit.timestamp = ref_hh.timestamp
        hit.readout_id = ref_hh.readout_id
        hit.payload = ref_hh.payload
        hit.chip_id = ref_hh.chip_id
        hit.tot_us = ref_hh.get_tot_us()
        hit.tot_total = ref_hh.tot_total
        # hit.fpga_ts = ref_hh.fpga_ts
        hit.fpga_ts = min(hh1.fpga_ts, hh2.fpga_ts)

        hit.row_halfhit_index = row_halfhit.index
        hit.col_halfhit_index = col_halfhit.index
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
                        hit = self.make_hit(row_halfhit, col_halfhit, 'col')
                        self.hits.append(hit)
            elif strategy == 'best_col':
                for col_halfhit in self.col_halfhits:
                    row_halfhit = self.find_match(col_halfhit)
                    if row_halfhit is not None:
                        hit = self.make_hit(row_halfhit, col_halfhit, 'row')
                        self.hits.append(hit)
            else:
                print(f'Unrecognized trategy: {strategy}')
        
        if 'all' in strategy and strategy != 'all_all':
            if strategy == 'all_row':
                matches = self.sort_matches('row')
                ref_hh_type = 'col'
            elif strategy == 'all_col':
                matches = self.sort_matches('col')
                ref_hh_type = 'row'
            else:
                print(f'Unrecognized trategy: {strategy}')
            for match_group in matches:
                for match_hh in match_group[1:]:
                    self.hits.append(self.make_hit(match_group[0], match_hh, ref_hh_type))

        if strategy == 'all_all':
            matches_row = self.sort_matches('row')
            matches_col = self.sort_matches('col')
            for match_group in matches_row:
                for match_hh in match_group[1:]:
                    self.hits.append(self.make_hit(match_group[0], match_hh, 'col'))

            for match_group in matches_col:
                for match_hh in match_group[1:]:
                    # if abs(match_group[0].fpga_ts*1e-6 - match_hh.fpga_ts*1e-6) > 0.1*1e-6 or len([hit for hit in self.hits if hit.col_halfhit_index == match_group[0].index and hit.row_halfhit_index == match_hh.index]) == 0:
                    if len([hit for hit in self.hits if hit.col_halfhit_index == match_group[0].index and hit.row_halfhit_index == match_hh.index]) == 0:
                        self.hits.append(self.make_hit(match_group[0], match_hh, 'row'))

            for i in range(len(self.row_halfhits_other) + len(self.col_halfhits_other)):
                halfhit = [hh for hh in self.row_halfhits_other + self.col_halfhits_other if hh.index == i]
                if len(halfhit) != 1:
                    print('WOW! NO HALFHIT MATCH!!!')
                halfhit = halfhit[0]
                if halfhit.isCol:
                    matches = [str(hit.row_halfhit_index) for hit in self.hits if hit.col_halfhit_index == halfhit.index]
                else:
                    matches = [str(hit.col_halfhit_index) for hit in self.hits if hit.row_halfhit_index == halfhit.index]
                if len(matches) == 0:
                    matches_str = '-'
                else:
                    matches_str = ', '.join(matches)
                self.out_file.write(self.row_format.format(halfhit.index, halfhit.location, halfhit.isCol, halfhit.get_tot_us(), halfhit.timestamp, halfhit.fpga_ts*1.*1e9/80e6, matches_str)) 

            row_format1 = "{:>8}  {:>3}  {:>3}  {:>20}\n"
            self.out_file.write('Hits:\n')
            self.out_file.write(row_format1.format("Index", "Row", "Col", "fpga_ts"))
            for i, hit in enumerate(self.hits):
                self.out_file.write(row_format1.format(i, hit.row, hit.col, hit.fpga_ts*1.*1e9/80e6)) 





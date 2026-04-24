from collections import deque

from .common import DecoderSettings_v3, MatcherStrategy, Stats_v3
from .hit_classes import HalfHit_v3, Hit_v3, MatchedHit_v3
from .utils import find_timestamp_difference

class Matcher:

    def __init__(self, hh_to_match: deque[HalfHit_v3], stats: Stats_v3, decoder_settings: DecoderSettings_v3):
        self.hh_to_match = hh_to_match
        self.stats = stats
        self.decoder_settings = decoder_settings

    def match(self) -> list[Hit_v3]:
        first_fpga_ts = self.hh_to_match[0].fpga_ts
        hits: list[Hit_v3] = []

        time = (self.hh_to_match[-1].fpga_ts - self.hh_to_match[0].fpga_ts) / self.decoder_settings.fpga_ts_clock_freq

        while self.hh_to_match:
            matches: list[MatchedHit_v3] = []

            # Check if we got a new trigger timestamp and need to refill deque
            if self.hh_to_match[0].fpga_ts != first_fpga_ts:
                break

            hh = self.hh_to_match.popleft()

            # Row halfhits arrive before column halfhits, thus we can skip them
            if hh.is_col:
                continue

            # Match row halfhit
            for other_hh in self.hh_to_match:
                if not other_hh.is_col:
                    continue
                if not self.chip_check(hh, other_hh):
                    continue
                if not self.timestamp_check(hh.timestamp, other_hh.timestamp):
                    continue
                if not self.tot_check(hh, other_hh):
                    continue
                matches.append(self.make_matched_hit(hh, other_hh))

            if not matches:
                self.stats.hh_wo_match_count += 1
                continue

            # Select matches based on strategy
            if self.decoder_settings.matcher_strategy == MatcherStrategy.CLOSEST:
                hits += self.strategy_closest(matches)
            else:
                hits += self.strategy_all(matches)

        return hits

    def chip_check(self, hh: HalfHit_v3, other_hh: HalfHit_v3) -> bool:
        if hh.layer != other_hh.layer:
            return False
        if hh.chip_id != other_hh.chip_id:
            return False
        return True

    def timestamp_check(self, ts1: int, ts2: int) -> bool:
        timestamp_difference = find_timestamp_difference(ts1, ts2, 8)
        if timestamp_difference > self.decoder_settings.matcher_ts_limit:
            return False
        return True

    def tot_check(self, hh: HalfHit_v3, other_hh: HalfHit_v3) -> bool:
        if self.decoder_settings.matcher_tot_limit is None:
            return True
        if hh.tot_raw == 0 or abs(hh.tot_raw - other_hh.tot_raw) / hh.tot_raw > self.decoder_settings.matcher_tot_limit:
            return False
        return True

    def make_matched_hit(self, row_hh: HalfHit_v3, col_hh: HalfHit_v3) -> MatchedHit_v3:
        return MatchedHit_v3(
            row_hh.location,
            col_hh.location,
            row_hh.fpga_ts,
            col_hh.fpga_ts,
            row_hh.tot_raw,
            col_hh.tot_raw,
            row_hh.index,
            col_hh.index,
            row_hh.timestamp,
            col_hh.timestamp,
            row_hh.chip_id,
            row_hh.layer
        )

    def convert_hit(self, hit: MatchedHit_v3) -> Hit_v3:
        # Take the row timestamp since it is read out first
        # Take the average ToT
        hit_tot_raw = round((hit.tot_col + hit.tot_row) / 2)
        return Hit_v3(hit.row, hit.col, hit.fpga_ts_row, hit_tot_raw, hit_tot_raw*self.decoder_settings.sample_clock_period_ns, hit.timestamp_row, hit.chip_id, hit.layer)

    def strategy_all(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick all hits
        return [self.convert_hit(hit) for hit in matches]

    def strategy_closest(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick the hit where the halfhits are the closest to each other (in terms of readout sequence)
        return [self.convert_hit(min(matches, key=lambda match: match.index_col - match.index_row))]

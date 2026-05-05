from collections import deque

from .common import DecoderSettings_v3, MatcherStrategy, Stats_v3
from .hit_classes import HalfHit_v3, Hit_v3, MatchedHit_v3
from .utils import find_timestamp_difference

class Matcher:

    def __init__(self, hh_to_match: deque[HalfHit_v3], stats: Stats_v3, decoder_settings: DecoderSettings_v3):
        self.hh_to_match = hh_to_match
        self.stats = stats
        self.decoder_settings = decoder_settings

        self.strategy = self.strategy_all
        if self.decoder_settings.matcher_strategy == MatcherStrategy.CLOSEST:
            self.strategy = self.strategy_closest
        elif self.decoder_settings.matcher_strategy == MatcherStrategy.CLOSEST_ROWFIRST:
            self.strategy = self.strategy_closest_rowfirst

    def match(self) -> list[Hit_v3]:
        matches: list[MatchedHit_v3] = []

        # Take first hit in queue
        hh = self.hh_to_match.popleft()

        # Match to other halfhit
        for other_hh in self.hh_to_match:
            if hh.is_col == other_hh.is_col:
                continue
            if not self.chip_check(hh, other_hh):
                continue
            if not self.timestamp_check(hh.timestamp, other_hh.timestamp):
                continue
            if not self.tot_check(hh, other_hh):
                continue
            matches.append(self.make_matched_hit(hh, other_hh))

        # Select matches based on strategy
        hits = self.strategy(matches)

        # Check if halfhit was matched at some point
        if hh.matches == 0:
            self.stats.hh_wo_match_count += 1
        else:
            self.stats.hh_matches_count += hh.matches

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

    def make_matched_hit(self, hh: HalfHit_v3, other_hh: HalfHit_v3) -> MatchedHit_v3:
        row_hh, col_hh = (hh, other_hh) if other_hh.is_col else (other_hh, hh)
        return MatchedHit_v3(row_hh, col_hh)

    def make_hit(self, hit: MatchedHit_v3) -> Hit_v3:
        # Mark halfhits as matched
        hit.row_hh.matches += 1
        hit.col_hh.matches += 1

        # Take the earlier FPGA timestamp
        fpga_ts = min(hit.row_hh.fpga_ts, hit.col_hh.fpga_ts)
        # Take the average ToT
        hit_tot_raw = round((hit.row_hh.tot_raw + hit.col_hh.tot_raw) / 2)
        # Take the average chip timestamp
        hit_timestamp = round((hit.row_hh.timestamp + hit.col_hh.timestamp) / 2)

        return Hit_v3(
            hit.row_hh.location,
            hit.col_hh.location,
            fpga_ts, hit_tot_raw,
            hit_tot_raw*self.decoder_settings.sample_clock_period_ns,
            hit_timestamp,
            hit.row_hh.chip_id,
            hit.row_hh.layer,
        )

    def strategy_all(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick all hits
        return [self.make_hit(hit) for hit in matches]

    def strategy_closest(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick the hit where the halfhits are the closest to each other (in terms of readout sequence)
        if matches:
            # TODO: what if there are two with same position diff ??? E.g. +1 and -1 -> use best in that case?
            return [self.make_hit(min(matches, key=lambda match: abs(match.col_hh.index - match.row_hh.index)))]
        return []

    def strategy_closest_rowfirst(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Like strategy_closest but only consider matches where the row halfhit arrived before the column halfhit
        filtered_matches: list[MatchedHit_v3] = []
        for match in matches:
            if match.row_hh.index < match.col_hh.index:
                filtered_matches.append(match)
        return self.strategy_closest(filtered_matches)

from collections import deque

from .common_v3 import DecoderSettings, MatcherStrategy, Stats
from .hit_classes_v3 import HalfHit_v3, Hit_v3, MatchedHit_v3


class Matcher:

    def __init__(self, hh_to_match: deque[HalfHit_v3], stats: Stats, decoder_settings: DecoderSettings):
        self.hh_to_match = hh_to_match
        self.stats = stats
        self.decoder_settings = decoder_settings

    def match(self) -> list[Hit_v3]:
        first_fpga_ts = self.hh_to_match[0].fpga_ts
        hits: list[Hit_v3] = []

        time = (self.hh_to_match[-1].fpga_ts - self.hh_to_match[0].fpga_ts) / 80e6
        print(f"Starting to match, first fpga ts {self.hh_to_match[0].fpga_ts}, last fpga ts {self.hh_to_match[-1].fpga_ts}, diff {time}s, {len(self.hh_to_match)} entries")

        while self.hh_to_match:
            matches: list[MatchedHit_v3] = []

            # Check if we got a new trigger timestamp and need to refill deque
            if self.hh_to_match[0].fpga_ts != first_fpga_ts:
                print("New trigger timestamp, refilling queue")
                break

            hh = self.hh_to_match.popleft()

            # Row halfhits arrive before column halfhits, thus we can skip them
            if hh.is_col:
                continue

            # Match row halfhit
            for other_hh in self.hh_to_match:
                if not other_hh.is_col:
                    continue
                if not self.timestamp_check(hh.timestamp, other_hh.timestamp):
                    continue
                if not self.tot_check(hh, other_hh):
                    continue
                matches.append(self.make_matched_hit(hh, other_hh))

            if not matches:
                print(f'No match found for halfhit with index {hh.index} and readout ID {hh.readout_id}')
                self.stats.hh_wo_match_count += 1
                continue

            # Select matches based on strategy
            if self.decoder_settings.matcher_strategy == MatcherStrategy.CLOSEST:
                hits += self.strategy_closest(matches)
            else:
                hits += self.strategy_all(matches)

        return hits

    def timestamp_check(self, ts1: int, ts2: int) -> bool:
        larger_ts, smaller_ts = (ts1, ts2) if ts1 > ts2 else (ts2, ts1)
        timestamp_difference = min([larger_ts - smaller_ts, 256 + smaller_ts - larger_ts])
        if timestamp_difference > self.decoder_settings.matcher_ts_limit:
            return False
        return True

    def tot_check(self, hh: HalfHit_v3, other_hh: HalfHit_v3) -> bool:
        if hh.tot == 0 or abs(hh.tot - other_hh.tot) / hh.tot > self.decoder_settings.matcher_tot_limit:
            return False
        return True

    def make_matched_hit(self, row_hh: HalfHit_v3, col_hh: HalfHit_v3) -> MatchedHit_v3:
        print(f"Matched row hh {row_hh.index} to col hh {col_hh.index}")
        return MatchedHit_v3(
            row_hh.location,
            col_hh.location,
            row_hh.fpga_ts,
            col_hh.fpga_ts,
            row_hh.tot,
            col_hh.tot,
            row_hh.index,
            col_hh.index,
        )

    def convert_hit(self, hit: MatchedHit_v3) -> Hit_v3:
        # Take the row timestamp since it is read out first
        # Take the average ToT
        print(f"Selected match with row hh {hit.index_row} and col hh {hit.index_col}")
        return Hit_v3(hit.row, hit.col, hit.fpga_ts_row, round((hit.tot_col + hit.tot_row) / 2))

    def strategy_all(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick all hits
        return [self.convert_hit(hit) for hit in matches]

    def strategy_closest(self, matches: list[MatchedHit_v3]) -> list[Hit_v3]:
        # Pick the hit where the halfhits are the closest to each other (in terms of readout sequence)
        return [self.convert_hit(min(matches, key=lambda match: match.index_col - match.index_row))]

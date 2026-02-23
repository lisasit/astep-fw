

class HitFilter:
    def __init__(self, hits, previous_good_fpga_timestamp):
        self.hits = hits
        self.filtered_hits = []
        self.zero_ts_hits = 0
        self.total_filtered_hits = 0
        self.previous_good_fpga_timestamp = previous_good_fpga_timestamp
        self.last_good_fpga_timestamp = None

    def filter(self, always_ok=False):
        if always_ok:
            self.filtered_hits = self.hits
            return
        if self.previous_good_fpga_timestamp is None:
            prev_ts = min([hit.fpga_ts for hit in self.hits[:800]])
            prev_ts_i = [i for i in range(len(self.hits[:800])) if self.hits[i].fpga_ts == prev_ts][0]
        else:
            prev_ts = self.previous_good_fpga_timestamp
            prev_ts_i = 0

        # print(f'Starting timestamp #{prev_ts_i} = {prev_ts} counts = {prev_ts/80e6 *1e9} ns')
        for i in range(prev_ts_i, len(self.hits)):
            hit = self.hits[i]
            if hit.fpga_ts < 0.1:
                self.zero_ts_hits += 1
                continue
            # if hit.fpga_ts < prev_ts or hit.fpga_ts - prev_ts > 1000000000:
            if abs(hit.fpga_ts*1e-6 - prev_ts*1e-6) > 1000000000*1e-6:
                continue
            prev_ts = hit.fpga_ts
            self.filtered_hits.append(hit)

        self.last_good_fpga_timestamp = self.filtered_hits[-1].fpga_ts if len(self.filtered_hits) != 0 else self.previous_good_fpga_timestamp
        self.total_filtered_hits += len(self.hits) - len(self.filtered_hits)


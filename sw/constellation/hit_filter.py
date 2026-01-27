

class HitFilter:
    def __init__(self, hits):
        self.hits = hits
        self.filtered_hits = []

    def filter(self, always_ok=False):
        if always_ok:
            self.filtered_hits = self.hits
            return
        prev_ts = min([hit.fpga_ts for hit in self.hits[:800]])
        prev_ts_i = [i for i in range(800) if self.hits[i].fpga_ts == prev_ts][0]
        print(f'Starting timestamp #{prev_ts_i} = {prev_ts} counts = {prev_ts/80e6 *1e9} ns')
        for i in range(prev_ts_i, len(self.hits)):
            hit = self.hits[i]
            if hit.fpga_ts < prev_ts or hit.fpga_ts - prev_ts > 1000000000:
                continue
            prev_ts = hit.fpga_ts
            self.filtered_hits.append(hit)

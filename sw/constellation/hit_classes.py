class HalfHit_v3:
    def __init__(self):
        self.sample_clock_period_ns = 25 #ns
        self.packet_length = None
        self.layer = None
        self.isCol = None
        self.location = None
        self.timestamp = None
        self.tot_lsb = None
        self.tot_msb = None
        self.tot_total = None
        self.tot_us = None
        self.chip_id = None
        self.payload = None
        self.readout_id = None
        self.fpga_ts = None
        self.index = False

    def get_tot_us(self):
        if self.tot_us is None:
            self.tot_us = self.tot_total * self.sample_clock_period_ns / 1000.0
        return self.tot_us

    def get_dict(self):
        if self.tot_total is not None:
            self.get_tot_us()
        return self.__dict__

class Hit_v3:
    def __init__(self):
        self.row = None
        self.col = None
        self.timestamp = None
        self.readout_id = None
        self.payload = None
        self.chip_id = None
        self.tot_us = None
        self.fpga_ts = None
        self.tot_total = None
        self.row_halfhit_index = None
        self.col_halfhit_index = None

    def get_dict(self):
        return self.__dict__

class Hit_v4:
    def __init__(self, use_negedge_ts):
        self.sample_clock_period_ns = 25 #ns
        self.packet_length = None
        self.layer = None
        self.chip_id = None
        self.payload = None
        self.row = None
        self.col = None
        self.ts1_neg = None
        self.ts1 = None
        self.ts1_fine = None
        self.ts1_tdc = None
        self.ts2_neg = None
        self.ts2 = None
        self.ts2_fine = None
        self.ts2_tdc = None
        self.fpga_ts = None
        self.readout_id = None
        self.tot_us = None
        self.ts1_dec = None
        self.ts2_dec = None
        self.tot_total = None
        self.use_negedge_ts = use_negedge_ts

    def get_dict(self):
        if self.tot_total is None:
            self.get_tot_total()
        if self.tot_us is None:
            self.get_tot_us()
        if self.ts1_dec is None:
            self.get_ts1_dec()
        if self.ts2_dec is None:
            self.get_ts2_dec()
        result = {}
        for key in self.__dict__:
            if key in ['use_negedge_ts']:
                continue
            result[key] = self.__dict__[key]
        return result

    def get_tot_us(self):
        if self.tot_us is None:
            self.tot_us = self.get_tot_total() * self.sample_clock_period_ns / 1000.0
        return self.tot_us

    def get_ts1_dec(self):
        if self.ts1_dec is None:
            self.ts1_dec = self.gray_to_dec((self.ts1 << 3) + self.ts1_fine) << 1 | (self.ts1_neg & self.use_negedge_ts)
        return self.ts1_dec

    def get_ts2_dec(self):
        if self.ts2_dec is None:
            self.ts2_dec = self.gray_to_dec((self.ts2 << 3) + self.ts2_fine) << 1 | (self.ts2_neg & self.use_negedge_ts)
        return self.ts2_dec

    def get_tot_total(self):
        if self.tot_total is None:
            if self.ts2_dec is None:
                self.ts2_dec = self.get_ts2_dec()
            if self.ts1_dec is None:
                self.ts1_dec = self.get_ts1_dec()

            if self.ts2_dec > self.ts1_dec:
                self.tot_total = self.ts2_dec - self.ts1_dec
            else:
                self.tot_total = 2**18 - 1 + self.ts2_dec - self.ts1_dec
        return self.tot_total

    def gray_to_dec(self, gray):
        """
        Decode Gray code to decimal

        :param gray: Gray code

        :returns: Decoded decimal
        """
        bits = gray >> 1
        while bits:
            gray ^= bits
            bits >>= 1
        return gray



def make_nice_number(num, prec='.1f'):
    if num < 1e3:
        return f"{num:{prec}}"
    if num < 1e6:
        return f"{num/1e3:{prec}}k"
    if num < 1e9:
        return f"{num/1e6:{prec}}M"
    return f"{num/1e3:{prec}}B"

def find_timestamp_difference(ts1, ts2, size_in_bits):
    max_value = 2**size_in_bits
    larger_ts, smaller_ts = (ts1, ts2) if ts1 > ts2 else (ts2, ts1)
    timestamp_difference = min([larger_ts - smaller_ts, max_value + smaller_ts - larger_ts])
    return timestamp_difference


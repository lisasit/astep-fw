

def make_nice_number(num, prec='.1f'):
    if num < 1e3:
        return f"{num:{prec}}"
    if num < 1e6:
        return f"{num/1e3:{prec}}k"
    if num < 1e9:
        return f"{num/1e6:{prec}}M"
    return f"{num/1e3:{prec}}B"



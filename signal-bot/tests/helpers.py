import random

from signal_bot.exchanges import Candle

TF = 900_000


def random_walk(n=500, seed=7, start=100.0):
    rnd = random.Random(seed)
    out, price = [], start
    for i in range(n):
        o = price
        c = max(1.0, o * (1 + rnd.gauss(0, 0.01)))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.004)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.004)))
        out.append(Candle(i * TF, o, h, l, c, 1000.0))
        price = c
    return out


def flat(n, price=100.0, start_ts=0):
    return [Candle(start_ts + i * TF, price, price + 0.5, price - 0.5, price, 100.0) for i in range(n)]

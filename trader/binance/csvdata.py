import collections
import io
import itertools
from datetime import datetime

import backtrader
from backtrader import date2num


class BinanceCSVData(backtrader.CSVDataBase):

    params = (
        ('nullvalue', 0),
        ('dtformat', '%S'),
        ('tmformat', '%H:%M:%S'),

        ('datetime', 0),
        ('time', -1),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', -1),
        ('close_time',6),
        ('quote_volume', 7),
        ('count', 8),
        ('taker_buy_volume', 9),
        ('taker_buy_quote_volume', 10),
        ('ignore', 11),
        ('reverse', False),
    )

    def start(self):
        super(BinanceCSVData, self).start()
        if not self.params.reverse:
            return

        # Yahoo sends data in reverse order and the file is still unreversed
        dq = collections.deque()
        for line in self.f:
            dq.appendleft(line)

        f = io.StringIO(newline=None)
        f.writelines(dq)
        f.seek(0)
        self.f.close()
        self.f = f

    def stop(self):
        pass

    def _loadline(self, linetokens):
        i = itertools.count(0)

        dttxt = linetokens[next(i)]
        dtnum = date2num(datetime.fromtimestamp(int(dttxt)/1000))
        self.lines.datetime[0] = dtnum
        self.lines.open[0] = float(linetokens[next(i)])
        self.lines.high[0] = float(linetokens[next(i)])
        self.lines.low[0] = float(linetokens[next(i)])
        self.lines.close[0] = float(linetokens[next(i)])
        self.lines.volume[0] = float(linetokens[next(i)])

        next(i)
        next(i)
        next(i)
        next(i)
        next(i)
        next(i)
        return True

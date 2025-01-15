
import backtrader as bt


class ChainerRSI(bt.Indicator):
    lines = ('rsi', 'signal',)
    params = (('period_rsi', 14), ('period_signal', 9),
              ('movav', bt.indicators.MovAv.Exponential),)

    plotinfo = dict(plothlines=[0.0])
    plotlines = dict(signal=dict(ls='--'))

    def _plotlabel(self):
        plabels = super(ChainerRSI, self)._plotlabel()
        return plabels

    def __init__(self):
        super(ChainerRSI, self).__init__()
        rsi = bt.indicators.RSI(self.data, period=self.params.period_rsi)

        self.lines.rsi = rsi
        self.lines.signal = self.params.movav(self.lines.rsi,period=self.params.period_signal)



class ChainerRSIHisto(ChainerRSI):
    alias = ('ChainerRSIHistogram',)

    lines = ('histo',)
    plotlines = dict(histo=dict(_method='bar', alpha=0.50, width=1.0))

    def __init__(self):
        super(ChainerRSIHisto, self).__init__()
        self.lines.histo = self.lines.rsi - self.lines.signal

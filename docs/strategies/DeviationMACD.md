# DeviationMACD Strategy

## Overview
The DeviationMACD strategy is a sophisticated trading strategy that combines MACD (Moving Average Convergence Divergence) with price divergence patterns to identify potential market reversals and trading opportunities. This strategy is particularly effective in trending markets and can help traders identify both regular and hidden divergences.

## Key Components

### 1. MACD Configuration
- Fast Period: 12 (default)
- Slow Period: 26 (default)
- Signal Period: 9 (default)

### 2. Risk Management
- Take Profit: 5.0% (default)
- Stop Loss: 2.0% (default)
- Dynamic Stop Loss based on ATR (Average True Range)

### 3. Divergence Detection
The strategy supports multiple types of divergences:
- Regular Divergence
- Hidden Divergence
- Combined Regular/Hidden Divergence

#### Divergence Parameters
- Minimum Number of Divergences: 1
- Maximum Pivot Points to Check: 10
- Maximum Bars to Check: 100
- Confirmation Options: Can be disabled for faster signals

### 4. ATR (Average True Range) Settings
- Smoothing Methods: RMA, SMA, EMA, WMA
- Multiplier: 1.5 (default)
- Dynamic Stop Loss Calculation

## Trading Logic

### Entry Conditions
1. Positive Regular or Hidden Divergence detected
2. Price queue confirmation (minimum 3 consecutive lower prices)
3. No existing long position

### Exit Conditions
1. Take Profit hit (5% by default)
2. Stop Loss hit (2% by default)
3. Negative Regular or Hidden Divergence detected
4. Price queue confirmation for exit (minimum 3 consecutive higher prices)

## Visual Indicators
- Divergence Lines
- Pivot Points
- Buy/Sell Signals
- ATR-based Stop Loss Levels

## Alert Conditions
The strategy provides alerts for:
- Positive Regular Divergence
- Negative Regular Divergence
- Positive Hidden Divergence
- Negative Hidden Divergence
- Combined Positive Divergence
- Combined Negative Divergence

## Usage Guidelines

### Recommended Timeframes
- 4H
- 1D
- 1W

### Best Market Conditions
- Trending markets
- High liquidity
- Moderate to high volatility

### Risk Management
1. Always use proper position sizing
2. Monitor ATR levels for dynamic stop loss adjustment
3. Consider market volatility when setting take profit levels

## Customization Options

### MACD Settings
```pine
period = input.int(12, title = 'period', group = "Base")
slowLength = input.int(26, title="slow period", group = "MACD")
signalLength = input.int(9, title="signal period", group = "MACD")
```

### Risk Parameters
```pine
takeProfitPerc = input.float(5.0, title="profit", minval=0.1, group = "Stop loss")
stopLossPerc = input.float(2.0, title="loss", minval=0.1, group = "Stop loss")
```

### Divergence Settings
```pine
searchdiv = input.string(defval = 'Regular', title = 'Divergence Type', 
    options = ['Regular', 'Hidden', 'Regular/Hidden'])
showlimit = input.int(1, title = 'Minimum Number of Divergence', 
    minval = 1, maxval = 11)
```

## Performance Considerations
1. The strategy uses arrays for price queue management
2. Divergence detection can be computationally intensive
3. Consider adjusting the maximum bars to check based on your timeframe

## Limitations
1. May generate false signals in ranging markets
2. Requires sufficient price history for divergence detection
3. Performance may be affected in low liquidity conditions

## Best Practices
1. Always backtest with sufficient historical data
2. Monitor and adjust parameters based on market conditions
3. Use in conjunction with other technical analysis tools
4. Consider market fundamentals and news events

## Support and Updates
For questions, issues, or updates, please refer to the project repository or contact the development team.

## Disclaimer
This strategy is provided for educational purposes only. Always test thoroughly before using in live trading. Past performance is not indicative of future results. 
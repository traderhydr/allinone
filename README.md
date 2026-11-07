# Merged Algo

A single TradingView indicator (Pine Script v5) combining:

- **Signals and risk levels**: supertrend + SMA13 Buy/Sell, "Smart" tag (EMA200 trend and ADX not sideways), ATR stop with 1:1, 2:1 and 3:1 targets
- **Daily levels**: settlement and ±0.5 / 0.7 / 1.0 SD bands from daily historical volatility, daily VWAP, EMA 200
- **Dashboard**: multi-timeframe EMA200 trend and RSI table, plus position, market state, volatility, session and momentum
- **Optional modules (off by default)**: CPR, MACD/RSI reversal signals and zones, pivot support/resistance, supply/demand zones, UT Bot trailing stop
- **Alerts**: buy, sell, stop hit, strong reversal buy/sell

## Use

1. Open the Pine Editor in TradingView.
2. Paste the contents of `merged-algo.pine`.
3. Click **Add to chart**.

## Status

Not yet compiled or backtested in TradingView. It is a chart-reading aid, not a tested strategy, and not financial advice.

## Algo Signals + Algo Structure

Two companion indicators (Pine v5) that combine the strongest part of eight community scripts. They are compact rewrites, not pasted copies, and are split in two to stay inside TradingView's drawing-object and compile-size limits. Add both to the same chart.

| File | Part | Taken from |
|---|---|---|
| `algo-signals.pine` | Buy / sell signals (range supertrend + McGinley Braid filter) | Infinity Algo |
| | TP1-3 / stop levels, hit tracking, stop-to-entry option | 2 UT Bot Strategy |
| | Entry / SL / TP lines and labels, dashboard, alerts | ELITE TP |
| | HILO moving-average channel, bar colours | Price Action Explorer |
| | Today's, tomorrow's and weekly CPR, R1-R3 / S1-S3 | Brahmastra |
| `algo-structure.pine` | Swing and internal BOS / CHoCH, order blocks, equal highs / lows, sweeps, premium / discount | Price Action Concepts |
| | Fair value gaps, previous day / week / month high and low | Mayfair |
| | Supply / demand zones, key swing levels | Neural Network |

Not carried over: volume profile, divergence / oscillators, multi-timeframe FVG, harmonic / zigzag tools, and the per-asset presets and webhook JSON from GG-SHOT.

### Notes

- Signal sensitivity follows Infinity Algo exactly: the supertrend band is `sensitivity x 2 x (high - low)`, so the default of 6 is very wide. Lower it for more signals.
- Trade levels default to ATR multiples (1 / 2 / 3, stop 1.5). Switch **Level mode** to Percent to use fixed percentages instead.
- When a bar touches both the stop and a target, the stop is counted first.
- The dashboard's TP1 rate is trades that reached TP1 divided by closed trades. It is a chart-reading aid, not a backtest.

### Status

Not compiled or run in TradingView, and not backtested. Expect to fix small compile errors on first paste. Not financial advice.

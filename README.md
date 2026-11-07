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

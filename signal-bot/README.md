# Signal bot

Pulls candles from **Binance** (spot or USD-M futures) and **BloFin** (perpetual swaps), runs the same signal engine as `algo-signals.pine`, and posts to your **Telegram channel**:

- a **BUY / SELL** message with entry, stop and TP1-TP3 when a new signal appears
- a follow-up when a target or the stop is hit

Pine Script cannot call exchanges or Telegram, so this runs as a small separate program (Python 3.9+, standard library only, nothing to install).

It uses public market data only. **It needs no exchange API keys, and it places no orders.**

## What it covers

Ported from `algo-signals.pine`: the Infinity Algo range supertrend, the McGinley Braid filter, and the UT Bot-style ATR trade levels with TP/stop tracking. The structure, volume profile, divergence, QQE, Vix Fix, VWAP CCI, CPR and matrix parts stay in TradingView.

Signals are computed only on **closed** candles, so a message never appears and then disappears.

## Leverage (15x cross by default)

Every message shows the leverage, the **return on margin** (ROE) at each target and at the stop, and an **estimated liquidation price**. A warning appears when the stop sits beyond that estimate. Set it in `config.json`:

```json
"leverage": {"x": 15, "mode": "cross", "maintenance_pct": 0.5}
```

Use `"leverage": null` to turn it off.

This is **display only**. The bot never sets leverage or margin mode on the exchange and places no orders, so set 15x cross on Binance / BloFin yourself. The liquidation figure is an isolated-equivalent estimate: with cross margin the real price depends on your whole account balance and other open positions, and each symbol has its own maximum leverage and maintenance rate. ROE ignores fees and funding.

## Set up

1. **Create the bot.** In Telegram, message `@BotFather`, send `/newbot`, and copy the token.
2. **Add it to your channel** as an administrator with permission to post messages.
3. **Find the chat id.** For a public channel it is `@yourchannelname`. For a private channel it is a number starting `-100`: post something in the channel, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id`.
4. **Set the credentials** as environment variables (never put them in a file you commit):

   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC..."
   export TELEGRAM_CHAT_ID="@yourchannelname"
   ```

5. **Configure the pairs:**

   ```bash
   cd signal-bot
   cp config.example.json config.json
   ```

   Edit `config.json`: pairs, timeframes and strategy settings. Symbols are written `BTC-USDT` for both exchanges. For Binance set `"market": "futures"` or `"spot"`.

## Try it, then run it

```bash
python3 -m signal_bot --test-telegram
```

sends one test message to your channel.

```bash
python3 -m signal_bot --dry-run --replay 200 --once
```

fetches live candles and prints the messages the last 200 candles would have produced, without sending anything. Use this to confirm the exchange connection works.

```bash
python3 -m signal_bot
```

runs for real. On first start it records the latest candle and sends nothing, so old signals are never replayed. State is kept in `state.json`, so a restart does not repeat messages.

To keep it running, use `tmux`/`screen`, or a systemd service:

```ini
[Unit]
Description=Algo signal bot
After=network-online.target

[Service]
WorkingDirectory=/path/to/allinone/signal-bot
Environment=TELEGRAM_BOT_TOKEN=...
Environment=TELEGRAM_CHAT_ID=@yourchannelname
ExecStart=/usr/bin/python3 -m signal_bot
Restart=always

[Install]
WantedBy=multi-user.target
```

## Differences from TradingView

- TradingView computes from the chart's full history; the bot uses the last `history` candles (default 500). The supertrend band ratchets from its starting point, so the two can disagree for a while after a fresh start, and entries may differ slightly. Compare a few signals against the chart before relying on it.
- Binance may refuse some regions (HTTP 451). If so, run the bot from another location or use BloFin.
- If the bot is offline, it catches up on missed candles when it restarts and sends the messages in order, including late TP/stop updates.
- A new signal replaces any open trade without a message for the old one.

## Tests

```bash
cd signal-bot && python3 -m unittest discover -s tests -t .
```

The tests use fixtures for the exchange responses and a mocked Telegram. **The bot has not been run against the live Binance, BloFin or Telegram APIs.** Run the dry run above first.

Not financial advice.

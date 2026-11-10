# Signal bot

Pulls candles from **Binance** (spot or USD-M futures) and **BloFin** (perpetual swaps), runs the same signal engine as `algo-signals.pine`, and posts to your **Telegram channel**:

- a signal message in this layout when a new signal appears:

  ```
  #ARB/USDT
  SHORT
  Entry Targets:
  1) 0.16189
  Take-Profit Targets:
  1) 0.16069
  2) 0.15949
  3) 0.15829
  Stop Targets:
  1) 0.16369
  Leverage: Cross (15x)
  ```
- optionally (`"follow_ups": true`), a follow-up when a target or the stop is hit

Pine Script cannot call exchanges or Telegram, so this runs as a small separate program (Python 3.9+, standard library only, nothing to install).

It uses public market data only. **It needs no exchange API keys, and it places no orders.**

## What it covers

Ported from `algo-signals.pine`: the Infinity Algo range supertrend, the McGinley Braid filter, and the UT Bot-style ATR trade levels with TP/stop tracking. The structure, volume profile, divergence, QQE, Vix Fix, VWAP CCI, CPR and matrix parts stay in TradingView.

Signals are computed only on **closed** candles, so a message never appears and then disappears.

## Leverage (15x cross by default)

The signal message ends with a `Leverage: Cross (15x)` line, and the target / stop follow-up messages show the **return on margin** (ROE) at that price. The bot also estimates the liquidation price and writes a warning to its log (not to the channel) when a signal's stop is beyond it: `journalctl -u signal-bot | grep liquidation`. Set the leverage in `config.json`:

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

   `config.futures.example.json` is a ready-made list of 43 Binance USDT-futures symbols; copy that one instead if you want them all. Edit `config.json`: pairs, timeframes and strategy settings. Symbols are written `BTC-USDT` for both exchanges. For Binance set `"market": "futures"` or `"spot"`.

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

## Using it with Cornix

The signal layout is the one Cornix reads. Cornix works out long or short from the prices, so the `LONG` / `SHORT` line is for people; the entry, take-profit and stop prices are always on the correct side for the direction.

- **Follow-up messages are off by default** (`"follow_ups": false`). Cornix watches the channel and acts on what it reads. An extra "TP1 hit" post is not a signal, but I could not confirm how Cornix treats it, and a misread could place a real order. Cornix manages its own take-profits and stops from the signal. The bot still tracks every trade internally, so repeat protection works the same either way. Set `"follow_ups": true` only if you want the updates for human readers and have checked how Cornix handles them.
- **Test with paper trading first.** Run it on a Cornix demo / paper account for a few days before connecting a real exchange account.
- **Check Cornix's settings** for duplicate signals and for an opposite signal on a pair that already has an open trade. The bot suppresses a same-direction repeat while its own simulated trade is open, but it does not know what Cornix actually has open.
- **Check the symbols and leverage.** Make sure Cornix supports each pair on your exchange (the `1000...` names in particular) and that the exchange allows the leverage in the message for that symbol.
- **The prices are the closed-candle price at signal time.** By the time Cornix places the order, the market may have moved; Cornix's entry settings decide what happens then.

## No repeated messages or trades

- **Same direction twice:** a BUY while a long trade is already open on that symbol and timeframe (or a SELL while a short is open) is ignored. Once the trade has hit its stop or TP3, a new signal in the same direction is allowed. An opposite signal replaces the open trade.
- **Cooldown:** set `"cooldown_bars": 4` in `config.json` to also ignore any signal on a series for that many candles after the previous one. The default is 0 (off).
- **Each message is sent once.** Messages are written to `state.json` first and removed only after Telegram accepted them. If Telegram is down, they stay queued and go out in order on the next pass, so nothing is lost and nothing is resent. A restart or crash resumes from the queue.
- **One copy only.** A second live copy using the same `state.json` would post everything twice, so the bot refuses to start (exit code 3) while another is running. `--dry-run`, `--replay` and `--test-telegram` don't take the lock and are safe next to the service.

Two limits: if the process dies in the instant after Telegram delivered a message but before the file was updated, that single message can be sent again after the restart. And a second copy running from a different folder (its own `state.json`) is not detected.

## Differences from TradingView

- TradingView computes from the chart's full history; the bot uses the last `history` candles (default 500). The supertrend band ratchets from its starting point, so the two can disagree for a while after a fresh start, and entries may differ slightly. Compare a few signals against the chart before relying on it.
- Binance may refuse some regions (HTTP 451). If so, run the bot from another location or use BloFin.
- A symbol the exchange does not list (delisted, or named differently on BloFin) is logged and retried after 1, 2, 4 ... minutes up to once an hour, so one bad symbol never blocks the rest. Check the log after the first run and remove any that keep failing.
- If the bot is offline, it catches up on missed candles when it restarts and sends the messages in order, including late TP/stop updates.
- An opposite signal replaces the open trade without a message for the old one.

## Tests

```bash
cd signal-bot && python3 -m unittest discover -s tests -t .
```

The tests use fixtures for the exchange responses and a mocked Telegram. **The bot has not been run against the live Binance, BloFin or Telegram APIs.** Run the dry run above first.

Not financial advice.

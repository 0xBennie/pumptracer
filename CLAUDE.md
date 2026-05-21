# pumptracer — Orderbook Forensics

This plugin provides the **ob-replay** skill for analyzing Binance USDT perpetual futures orderbook manipulation patterns.

## Available Skills

- **ob-replay** — Replay any coin's historical orderbook into a 3-panel chart + manipulation narrative + detector blind-spot audit

## When to Trigger ob-replay

Invoke automatically when the user asks to:
- 复盘 / replay / analyze a specific coin's movement
- 拆解 / break down pump/dump/砸盘/拉盘 behavior
- See the K-line + depth chart for a symbol
- Understand what the 庄家/market maker was doing
- Compare patterns across historical cases

## Quick Reference

```bash
# Auto-find largest move in last 48h
python3 replay.py --symbol LABUSDT --auto

# Specific window (UTC+8)
python3 replay.py --symbol CHIPUSDT --from "2026-05-20 15:00" --to "2026-05-21 03:00"

# Last N hours
python3 replay.py --symbol FIDAUSDT --hours 12

# Batch backfill (30 days)
python3 backfill.py --days 30 --min-range 0.08 --max-cases 500
```

## 8 Fingerprints (793 cases)

| Pattern | Samples |
|---------|---------|
| bid_wall_pull | 350 |
| lopsided_book | 341 |
| flash_dump | 316 |
| distribution_wall | 254 |
| pump_continuation | 18 |
| rapid_pump_distribution | 10 |
| consolidation_breakout | common |
| consolidation_then_pump | common |

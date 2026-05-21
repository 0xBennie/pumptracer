# pumptracer

Orderbook forensics tool for Binance USDT perpetual futures. Replays any coin's historical orderbook depth into a 3-panel chart + manipulation pattern report, built from **793 real case studies** across 30 days of live data.

```bash
python3 replay.py --symbol LABUSDT --auto
python3 replay.py --symbol CHIPUSDT --from "2026-05-20 15:00" --to "2026-05-21 03:00"
python3 backfill.py --days 30 --min-range 0.08 --max-cases 200
```

---

## What it does

For any symbol + time window it produces:

| Output | Content |
|--------|---------|
| **3-panel PNG** | K-line (OHLC) · 1-tier bid/ask depth · 1% cumulative depth walls |
| **Case markdown** | Stage table · depth signatures · auto-generated narrative · detector blind-spot audit |
| **Pattern library** | `_index.md` (all cases) · `_patterns.md` (fingerprint buckets, auto-updated) |

---

## 8 Manipulation Fingerprints

Derived from **793 cases / 30 days** of live Binance orderbook data:

| Pattern | Trigger | Samples | Detector Rule |
|---------|---------|---------|---------------|
| `bid_wall_pull` | bid 1% cumulative drops 30%+ in 5 snapshots | **350** | ✅ `bid_wall_pull` |
| `lopsided_book` | ask > bid × 3 AND ask > $100k | **341** | ✅ `lopsided_book` |
| `flash_dump` | 1-min drop > 2.5% | **316** | ✅ `flash_dump` |
| `distribution_wall` | ask 1% cumulative > $200k | **254** | ✅ `distribution_wall` |
| `pump_continuation` | current 30m +15% AND prior 6h had +20% | 18 | ✅ `pump_continuation` |
| `rapid_pump_distribution` | 1h +20% then ask/bid > 3x | 10 | ✅ `rapid_pump_distribution` |
| `consolidation_breakout` | 2h range < 5% then 5m move > 5% | common | ✅ `breakout_after_consolidation` |
| `consolidation_then_pump` | 2h range < 5% followed by +8% | common | ✅ `breakout_after_consolidation` |

All 8 patterns now have corresponding real-time detector rules.

---

## Data Sources

Reads from a local SQLite database (`data/orderbook.db`) populated by a Binance WebSocket + REST collector:

| Table | Interval | Retention | Content |
|-------|----------|-----------|---------|
| `ob_summary` | 10s | 2 days | bid1/ask1 price + USD depth + imbalance |
| `ob_deep_depth` | 30s | 30 days | 1% cumulative bid/ask USD + max wall price/size |
| `ob_events` | on trigger | 30 days | detector rule hits |
| `shadow_signals` | on trigger | 30 days | spread monitor signals (pushed / rejected) |

---

## Usage

### Single coin replay

```bash
# Auto-detect largest amplitude window in last 48h
python3 replay.py --symbol LABUSDT --auto

# Specific time window (UTC+8)
python3 replay.py --symbol CHIPUSDT \
  --from "2026-05-20 15:00" \
  --to   "2026-05-21 03:00" \
  --tags "distribution,lopsided"

# Last N hours
python3 replay.py --symbol FIDAUSDT --hours 12
```

### Batch backfill

```bash
# Scan last 30 days, amplitude > 8%, up to 500 new cases
python3 backfill.py --days 30 --min-range 0.08 --max-cases 500

# Dry run — preview candidates without generating
python3 backfill.py --days 30 --min-range 0.15 --dryrun
```

---

## Output example

```
docs/ob-cases/
├── LABUSDT-20260519.png      ← 3-panel chart
├── LABUSDT-20260519.md       ← case report with narrative
├── _index.md                 ← all cases sorted by date
└── _patterns.md              ← fingerprint buckets (350 bid_wall_pull, 341 lopsided, ...)
```

**Case report structure:**
- Metadata table (open/close/high/low/duration/tags)
- 15-min stage table with bid/ask depth
- Key depth signatures (peak bid 1%, peak ask 1%, peak walls with price levels)
- Auto-generated manipulation narrative (stage-by-stage)
- Detector blind-spot audit (signals that should have fired but didn't)
- Fingerprint tags

**Sample narrative output:**
```
本段行情净跌 12.7%，区间底部较开盘低 29.4%，呈下行走势。
盘口出现大量 ask 挂单（ask 1% 累计峰值 $1515k），是庄家派发的直接证据。
盘口严重偏斜（ask$1518k vs bid$2k, 比值 644.5x），卖压远大于买压。
出现闪电砸盘（跌 -4.11%），短时大幅下跌触发恐慌盘。
```

---

## Top Repeat Offenders (30-day analysis, 793 cases)

Symbols appearing most frequently across all pattern buckets:

| Rank | Symbol | Occurrences | Typical Playbook |
|------|--------|-------------|-----------------|
| 1 | LABUSDT | 34 | distribution + lopsided + flash dump |
| 2 | JTOUSDT | 28 | bid wall pull + lopsided |
| 3 | BILLUSDT | 28 | distribution + bid wall pull |
| 4 | ONDOUSDT | 25 | distribution wall multi-day |
| 5 | DOGSUSDT | 24 | flash dump + pump continuation |

High repeat count = fixed market maker with predictable playbook. These are the highest-priority symbols to monitor in real time.

---

## Requirements

```
python >= 3.9
matplotlib >= 3.7
Pillow >= 10.0
```

Chinese font for labels (optional, falls back gracefully):
```
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc   # Linux
/System/Library/Fonts/PingFang.ttc                         # macOS
```

---

## Learning Loop

1. Every replay extracts fingerprints → appended to `_patterns.md`
2. When a bucket reaches **30+ samples** → promote to a real-time detector rule
3. Pattern hit rates feed back into threshold calibration
4. Weekly `backfill` cron keeps the case library current

**All 6 high-sample patterns (30+ samples) now have detector rules.** The loop is closed.

---

## Architecture

```
Binance WS/REST
      │
      ▼
ob_summary (10s, 2d)          ob_deep_depth (30s, 30d)
      │                               │
      ▼                               ▼
ob-detector.ts (13 rules)    deep-depth-monitor (2 rules)
      │                               │
      └──────────┬────────────────────┘
                 ▼
          TG alert (ob group)
                 │
                 ▼
           ob_events table
                 │
                 ▼
         replay.py / backfill.py
                 │
                 ▼
     docs/ob-cases/ (793 cases)
                 │
                 ▼
          _patterns.md → threshold tuning
```

---

## License

MIT

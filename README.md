# pumptracer

Orderbook forensics tool for Binance USDT perpetual futures. Replays any coin's historical order book depth into a 3-panel chart + manipulation pattern report, built from 800+ real pump/dump case studies.

```
python3 replay.py --symbol LABUSDT --auto
python3 replay.py --symbol EDENUSDT --from "2026-05-19 14:00" --to "2026-05-20 01:30"
python3 backfill.py --days 30 --min-range 0.08 --max-cases 200
```

---

## What it does

For any symbol + time window it produces:

| Output | Content |
|--------|---------|
| **3-panel PNG** | K-line (OHLC) · 1-tier bid/ask depth · 1% cumulative depth walls |
| **Case markdown** | Stage table · depth signature · manipulation narrative · detector blind-spot audit |
| **Pattern index** | `_index.md` (all cases) · `_patterns.md` (fingerprint buckets) |

---

## 8 Manipulation Fingerprints

Derived from **834 cases / 30 days** of Binance orderbook data:

| Pattern | Trigger | Samples | Detector Rule |
|---------|---------|---------|---------------|
| `lopsided_book` | ask > bid × 3 AND ask > $100k | **221** | `lopsided_book` |
| `flash_dump` | 1-min drop > 2.5% | **202** | `flash_dump` |
| `bid_wall_pull` | bid 1% cumulative drops 30%+ in 5 snapshots | **190** | pending |
| `distribution_wall` | ask 1% cumulative > $200k | **172** | `distribution_wall` |
| `pump_continuation` | current 30m +15% AND prior 6h had +20% | 11 | `pump_continuation` |
| `consolidation_breakout` | 2h range < 5% then 5m move > 5% | common | `breakout_after_consolidation` |
| `consolidation_then_pump` | 2h range < 5% followed by +8% | common | `breakout_after_consolidation` |
| `rapid_dump_after_pump` | 1h +20% then ask wall > $150k | medium | pending |

---

## Data Sources

Reads from a local SQLite database (`data/orderbook.db`) populated by a Binance WebSocket collector:

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
python3 replay.py --symbol EDENUSDT \
  --from "2026-05-19 14:00" \
  --to   "2026-05-20 01:30" \
  --tags "multi-pump,distribution"

# Last N hours
python3 replay.py --symbol FIDAUSDT --hours 12
```

### Batch backfill

```bash
# Scan last 30 days, amplitude > 8%, up to 200 new cases
python3 backfill.py --days 30 --min-range 0.08 --max-cases 200

# Dry run to preview candidates
python3 backfill.py --days 30 --min-range 0.15 --dryrun
```

---

## Output example

```
docs/ob-cases/
├── LABUSDT-20260519.png     ← 3-panel chart
├── LABUSDT-20260519.md      ← case report
├── _index.md                ← all cases sorted by date
└── _patterns.md             ← fingerprint buckets (221 lopsided, 202 flash_dump, ...)
```

**Case report structure:**
- Metadata table (open/close/high/low/duration)
- 15-min stage table with bid/ask depth
- Key depth signatures (peak bid 1%, peak ask 1%, peak walls)
- Auto-generated manipulation narrative
- Detector blind-spot audit (what should have fired but didn't)
- Fingerprint tags

---

## Top Repeat Offenders (30-day analysis)

Symbols appearing most frequently across all pattern buckets:

| Rank | Symbol | Occurrences | Typical Pattern |
|------|--------|-------------|-----------------|
| 1 | LABUSDT | 20 | distribution + lopsided |
| 2 | ONDOUSDT | 17 | distribution + lopsided |
| 3 | ZECUSDT | 15 | flash dump |
| 4 | JTOUSDT / DOGSUSDT / BUSDT | 14 | mixed |

High repeat count = fixed market maker team with predictable playbook.

---

## Requirements

```
python >= 3.9
matplotlib
Pillow
```

Chinese font for labels (optional, falls back gracefully):
```
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

---

## Learning Loop

1. Every replay extracts fingerprints → appended to `_patterns.md`
2. When a bucket reaches **30+ samples** → promote to a detector rule
3. Pattern hit rates feed back into threshold tuning
4. Weekly backfill cron keeps the case library current

**Current threshold status:**
- `lopsided_book` (221): ✅ in detector
- `flash_dump` (202): ✅ in detector  
- `bid_wall_pull` (190): needs detector rule
- `distribution_wall` (172): ✅ in detector

---

## License

MIT

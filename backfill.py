#!/usr/bin/env python3
"""
ob-replay backfill: 扫最近 30 天 ob_deep_depth 找大波动 symbol, 批量复盘

策略:
  1. 按 symbol 按天分组 ob_deep_depth
  2. 每天计算 max-min 振幅
  3. 振幅 > 15% 的 symbol-day 加入候选
  4. 对每个候选跑 replay.py
  5. 已有的 case 不重跑 (按 docs/ob-cases/<symbol>-<date>.md 存在判断)

注意:
  - ob_summary 仅保留 2 天, > 2 天的 case 只有 1% 累计深度图 (无 K 线)
  - ob_deep_depth 保留 30 天
"""
import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OB_DB = REPO_ROOT / 'data' / 'orderbook.db'
CASES_DIR = REPO_ROOT / 'docs' / 'ob-cases'
REPLAY_SCRIPT = Path(__file__).parent / 'replay.py'
UTC8 = timezone(timedelta(hours=8))


def find_candidates(days_back, min_range_pct):
    """扫 ob_deep_depth 按 symbol+日期 找大波动"""
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)
    conn = sqlite3.connect(str(OB_DB))
    rows = conn.execute(
        "SELECT symbol, ts, mid_price FROM ob_deep_depth WHERE ts >= ? AND mid_price > 0",
        (since_ms,),
    ).fetchall()
    conn.close()

    # 按 symbol+UTC+8 日期分组
    by_day = {}
    for sym, ts, mid in rows:
        d = (datetime.utcfromtimestamp(ts/1000) + timedelta(hours=8)).strftime('%Y-%m-%d')
        k = (sym, d)
        if k not in by_day:
            by_day[k] = []
        by_day[k].append((ts, mid))

    # 计算每个 (symbol, day) 的振幅
    candidates = []
    for (sym, day), pts in by_day.items():
        if len(pts) < 10:
            continue
        prices = [p[1] for p in pts]
        max_p = max(prices)
        min_p = min(prices)
        if min_p <= 0:
            continue
        rng = (max_p - min_p) / min_p
        if rng < min_range_pct:
            continue
        # 找开始时间 (最低点前 30min) 和 结束时间 (最高点后 30min)
        candidates.append({
            'symbol': sym, 'day': day, 'range': rng,
            'min_p': min_p, 'max_p': max_p,
            'first_ts': pts[0][0], 'last_ts': pts[-1][0],
        })

    candidates.sort(key=lambda c: -c['range'])
    return candidates


def case_exists(symbol, date_str):
    md = CASES_DIR / f'{symbol}-{date_str.replace("-", "")}.md'
    return md.exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30, help='回溯天数')
    ap.add_argument('--min-range', type=float, default=0.15, help='单日最小振幅 (默认 15%%)')
    ap.add_argument('--max-cases', type=int, default=50, help='最多生成多少个 case')
    ap.add_argument('--dryrun', action='store_true', help='只打印候选,不生成')
    args = ap.parse_args()

    print(f'[backfill] scanning last {args.days} days, min_range={args.min_range*100:.0f}%')
    candidates = find_candidates(args.days, args.min_range)
    print(f'[backfill] found {len(candidates)} candidate symbol-days')

    new_cases = []
    skipped = 0
    for c in candidates:
        date_str = c['day'].replace('-', '')
        if case_exists(c['symbol'], c['day']):
            skipped += 1
            continue
        new_cases.append(c)
        if len(new_cases) >= args.max_cases:
            break

    print(f'[backfill] {skipped} already exist, will generate {len(new_cases)} new cases')

    if args.dryrun:
        print('\nTOP 候选:')
        for c in new_cases[:20]:
            print(f'  {c["symbol"]:15s} {c["day"]}  range={c["range"]*100:.1f}%  '
                  f'(${c["min_p"]:.5f} → ${c["max_p"]:.5f})')
        return

    success = fail = 0
    for i, c in enumerate(new_cases, 1):
        # 时间窗: 从当天 00:00 UTC+8 到当天 23:59 (但要在数据范围内)
        day_dt = datetime.strptime(c['day'], '%Y-%m-%d').replace(tzinfo=UTC8)
        from_str = day_dt.strftime('%Y-%m-%d 00:00')
        to_str = (day_dt + timedelta(days=1, minutes=-1)).strftime('%Y-%m-%d %H:%M')

        tags = f'振幅{c["range"]*100:.0f}%'
        print(f'\n[{i}/{len(new_cases)}] {c["symbol"]} {c["day"]} range={c["range"]*100:.1f}%')
        try:
            r = subprocess.run(
                ['python3', str(REPLAY_SCRIPT),
                 '--symbol', c['symbol'],
                 '--from', from_str,
                 '--to', to_str,
                 '--tags', tags],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                success += 1
                print(r.stdout.strip().split('\n')[-1] if r.stdout else 'ok')
            else:
                fail += 1
                print(f'  FAIL: {r.stderr.strip()[:200]}')
        except subprocess.TimeoutExpired:
            fail += 1
            print(f'  TIMEOUT')

    print(f'\n[backfill] done: {success} ok, {fail} fail, {skipped} skip')


if __name__ == '__main__':
    main()

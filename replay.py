#!/usr/bin/env python3
"""
ob-replay: 单币种盘口操盘复盘工具
用法:
  # 自动找最大波幅窗口
  python3 replay.py --symbol EDENUSDT --auto

  # 指定时间窗 (UTC+8)
  python3 replay.py --symbol EDENUSDT --from "2026-05-19 14:00" --to "2026-05-20 01:30"

  # 最近 N 小时
  python3 replay.py --symbol STARUSDT --hours 6

  # 加标签
  python3 replay.py --symbol EDENUSDT --auto --tags "多段拉升,派发铁证"
"""
import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
OB_DB = REPO_ROOT / 'data' / 'orderbook.db'
SIG_DB = REPO_ROOT / 'data' / 'signals.db'
CASES_DIR = REPO_ROOT / 'docs' / 'ob-cases'
INDEX_FILE = CASES_DIR / '_index.md'
PATTERNS_FILE = CASES_DIR / '_patterns.md'

FONT_PATHS = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
]
ZH = None
for p in FONT_PATHS:
    if os.path.exists(p):
        ZH = font_manager.FontProperties(fname=p)
        break
plt.rcParams['axes.unicode_minus'] = False

UTC8 = timezone(timedelta(hours=8))


def to_dt(ms):
    return datetime.utcfromtimestamp(ms / 1000) + timedelta(hours=8)


def parse_local_dt(s):
    """Parse '2026-05-19 14:00' as UTC+8."""
    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S+08:00', '%Y-%m-%dT%H:%M:%S']:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s}")


def auto_window(symbol, look_back_h=48):
    """扫最近 N 小时找振幅最大的连续窗口"""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    from_ms = now_ms - look_back_h * 3600_000
    conn = sqlite3.connect(str(OB_DB))
    rows = conn.execute(
        "SELECT ts, (bid1+ask1)/2 AS mid FROM ob_summary WHERE symbol=? AND ts>=? ORDER BY ts ASC",
        (symbol, from_ms),
    ).fetchall()
    conn.close()
    if len(rows) < 50:
        # 退到 deep_depth (保留 30 天)
        conn = sqlite3.connect(str(OB_DB))
        rows = conn.execute(
            "SELECT ts, mid_price FROM ob_deep_depth WHERE symbol=? AND ts>=? ORDER BY ts ASC",
            (symbol, from_ms),
        ).fetchall()
        conn.close()
    if len(rows) < 10:
        return None, None

    # 滑动窗口找 12h 内最大振幅
    win_ms = 12 * 3600_000
    best_range = 0
    best_lo = best_hi = 0
    for i, (t0, p0) in enumerate(rows):
        max_p = min_p = p0
        for j in range(i, len(rows)):
            t, p = rows[j]
            if t - t0 > win_ms:
                break
            if p > max_p:
                max_p = p
            if p < min_p:
                min_p = p
        if min_p > 0 and (max_p - min_p) / min_p > best_range:
            best_range = (max_p - min_p) / min_p
            best_lo = t0
            # 找窗口右端
            for j in range(i, len(rows)):
                if rows[j][0] - t0 > win_ms:
                    break
                best_hi = rows[j][0]

    if best_range < 0.05:
        return None, None
    # 前后各 padding 30min
    return best_lo - 30 * 60_000, best_hi + 30 * 60_000


def load_data(symbol, from_ms, to_ms):
    """Load ob_summary + ob_deep_depth + shadow_signals + ob_events."""
    conn = sqlite3.connect(str(OB_DB))
    cur = conn.cursor()
    cur.execute(
        "SELECT ts, bid1, ask1, bid_depth_usd, ask_depth_usd, imbalance FROM ob_summary "
        "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts ASC",
        (symbol, from_ms, to_ms),
    )
    summary = cur.fetchall()
    cur.execute(
        "SELECT ts, mid_price, bid_1pct_usd, ask_1pct_usd, imb_1pct, "
        "max_bid_wall_usd, max_bid_wall_price, max_ask_wall_usd, max_ask_wall_price "
        "FROM ob_deep_depth WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts ASC",
        (symbol, from_ms, to_ms),
    )
    deep = cur.fetchall()
    try:
        cur.execute(
            "SELECT ts, level, types, details FROM ob_events "
            "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts ASC",
            (symbol, from_ms, to_ms),
        )
        events = cur.fetchall()
    except sqlite3.OperationalError:
        events = []
    conn.close()

    shadow = []
    if SIG_DB.exists():
        sconn = sqlite3.connect(str(SIG_DB))
        try:
            shadow = sconn.execute(
                "SELECT timestamp, spreadPct, maxSpreadExchange, volume24h, change24h, "
                "confidenceScore, mainPushed, rejectReason FROM shadow_signals "
                "WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp ASC",
                (symbol, from_ms, to_ms),
            ).fetchall()
        except sqlite3.OperationalError:
            pass
        sconn.close()

    return summary, deep, events, shadow


def build_ohlc(summary, bar_min):
    """Resample summary into N-min OHLC bars."""
    if not summary:
        return []
    buckets = defaultdict(list)
    for ts, b1, a1, bd, ad, imb in summary:
        mid = (b1 + a1) / 2
        d = to_dt(ts)
        floor_min = (d.minute // bar_min) * bar_min
        key = d.replace(minute=floor_min, second=0, microsecond=0)
        buckets[key].append((mid, bd, ad))
    bars = []
    for k in sorted(buckets):
        pts = buckets[k]
        ps = [p[0] for p in pts]
        bars.append({
            'ts': k, 'open': ps[0], 'high': max(ps), 'low': min(ps), 'close': ps[-1],
            'bid_depth': sum(p[1] for p in pts) / len(pts),
            'ask_depth': sum(p[2] for p in pts) / len(pts),
        })
    return bars


def render(symbol, from_ms, to_ms, summary, deep, out_png, tags):
    duration_h = (to_ms - from_ms) / 3600_000
    bar_min = 1 if duration_h <= 2 else (5 if duration_h <= 12 else 15)
    bars = build_ohlc(summary, bar_min)

    # 2 个子图: K 线 + 1档深度 (上), 1% 累计 (下)
    fig, axes = plt.subplots(3, 1, figsize=(16, 11),
                             gridspec_kw={'height_ratios': [3, 1.2, 1.3]}, sharex=True)
    ax1, ax2, ax3 = axes

    # Panel 1: K 线
    if bars:
        for b in bars:
            is_up = b['close'] >= b['open']
            color = '#26a69a' if is_up else '#ef5350'
            x = mdates.date2num(b['ts'])
            ax1.plot([x, x], [b['low'], b['high']], color=color, linewidth=1.0, zorder=2)
            body_h = max(abs(b['close'] - b['open']), b['open'] * 0.0002)
            body_low = min(b['open'], b['close'])
            width_days = bar_min / (60 * 24) * 0.85
            ax1.add_patch(plt.Rectangle((x - width_days/2, body_low), width_days, body_h,
                                        facecolor=color, edgecolor=color, zorder=3))

        op, cl = bars[0]['open'], bars[-1]['close']
        hi = max(b['high'] for b in bars)
        lo = min(b['low'] for b in bars)
        info = (f'起 ${op:.5f}\n终 ${cl:.5f} ({(cl-op)/op*100:+.2f}%)\n'
                f'顶 ${hi:.5f} ({(hi-op)/op*100:+.2f}%)\n底 ${lo:.5f} ({(lo-op)/op*100:+.2f}%)')
        ax1.text(0.012, 0.97, info, transform=ax1.transAxes, fontsize=10, va='top',
                fontproperties=ZH,
                bbox=dict(boxstyle='round', facecolor='white', edgecolor='gray', alpha=0.9))
    else:
        ax1.text(0.5, 0.5, 'ob_summary 无数据 (>2 天前)',
                ha='center', va='center', transform=ax1.transAxes, fontsize=12, fontproperties=ZH)

    title = f'{symbol} 操盘复盘 · {duration_h:.1f}h · {bar_min}min OHLC'
    if tags:
        title += f' · {tags}'
    ax1.set_title(title, fontsize=13, fontweight='bold', pad=10, fontproperties=ZH)
    ax1.set_ylabel('价格 (USDT)', fontsize=11, fontproperties=ZH)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_facecolor('#fafafa')

    # Panel 2: 1档深度
    if bars:
        ts_list = [b['ts'] for b in bars]
        ax2.fill_between(ts_list, 0, [b['bid_depth'] for b in bars],
                         color='#26a69a', alpha=0.6, label='Bid 1档$')
        ax2.fill_between(ts_list, 0, [-b['ask_depth'] for b in bars],
                         color='#ef5350', alpha=0.6, label='Ask 1档$')
        ax2.axhline(0, color='black', linewidth=0.5)
        ax2.legend(loc='upper right', fontsize=9, prop=ZH)
    ax2.set_ylabel('1档深度 (USD)', fontsize=11, fontproperties=ZH)
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_facecolor('#fafafa')

    # Panel 3: 1% 累计深度墙
    if deep:
        dts = [to_dt(d[0]) for d in deep]
        dbid = [d[2] for d in deep]
        dask = [d[3] for d in deep]
        ax3.plot(dts, dbid, '-', color='#2e7d32', label='Bid 1% 累计$', linewidth=1.4, alpha=0.85)
        ax3.plot(dts, dask, '-', color='#c62828', label='Ask 1% 累计$', linewidth=1.4, alpha=0.85)
        ax3.fill_between(dts, dbid, alpha=0.15, color='#2e7d32')
        ax3.fill_between(dts, dask, alpha=0.15, color='#c62828')
        # 标 ask 巨墙 (派发铁证)
        max_ask = max((d[7] or 0) for d in deep)
        if max_ask > 100_000:
            for d in deep:
                if d[7] == max_ask:
                    et = to_dt(d[0])
                    ax3.annotate(f'派发铁证\nask墙${int(d[7]/1000)}k@{d[8]:.4f}',
                                xy=(et, d[3]),
                                xytext=(et, d[3] * 1.5),
                                ha='center', fontsize=9, color='#b71c1c', fontweight='bold',
                                fontproperties=ZH,
                                arrowprops=dict(arrowstyle='->', color='#b71c1c', lw=1.5))
                    break
        # 标 bid 巨墙
        max_bid = max((d[5] or 0) for d in deep)
        if max_bid > 50_000:
            for d in deep:
                if d[5] == max_bid:
                    et = to_dt(d[0])
                    ax3.annotate(f'撑盘 bid墙\n${int(d[5]/1000)}k@{d[6]:.4f}',
                                xy=(et, d[2]),
                                xytext=(et, d[2] * 1.3),
                                ha='center', fontsize=9, color='#1b5e20', fontweight='bold',
                                fontproperties=ZH,
                                arrowprops=dict(arrowstyle='->', color='#1b5e20', lw=1.5))
                    break
        ax3.legend(loc='upper right', fontsize=9, prop=ZH)
    else:
        ax3.text(0.5, 0.5, 'ob_deep_depth 无数据',
                ha='center', va='center', transform=ax3.transAxes, fontsize=12, fontproperties=ZH)
    ax3.set_ylabel('1% 累计深度 (USD)', fontsize=11, fontproperties=ZH)
    ax3.set_xlabel('时间 (UTC+8)', fontsize=11, fontproperties=ZH)
    ax3.grid(True, alpha=0.3, linestyle='--')
    ax3.set_facecolor('#fafafa')

    xlim_lo = to_dt(from_ms)
    xlim_hi = to_dt(to_ms)
    for ax in axes:
        ax.set_xlim(xlim_lo, xlim_hi)
        if duration_h <= 4:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=15))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, int(duration_h / 12))))
        for lbl in ax.get_xticklabels() + ax.get_yticklabels():
            if ZH:
                lbl.set_fontproperties(ZH)

    plt.tight_layout()
    plt.savefig(out_png, dpi=110, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def extract_fingerprint(summary, deep, bars):
    """从数据提取操盘指纹 — 这是学习闭环的核心"""
    fp = []
    if not bars and not deep:
        return fp

    # ── 1. 派发铁证: ask 1% 累计 > $200k ──
    if deep:
        max_ask_1pct = max(d[3] or 0 for d in deep)
        if max_ask_1pct > 200_000:
            fp.append({
                'pattern': '派发铁证',
                'detail': f'ask 1% 累计峰值 ${int(max_ask_1pct/1000)}k',
                'value': max_ask_1pct,
            })

    # ── 2. 多段拉升: 6-12h 内 ≥2 次 30min +15% ──
    if bars:
        rises = []
        for i, b in enumerate(bars):
            window_start = b['ts'] - timedelta(minutes=30)
            base = next((bb for bb in bars if bb['ts'] >= window_start), None)
            if base and base['ts'] < b['ts']:
                rise = (b['close'] - base['open']) / base['open']
                if rise > 0.15:
                    rises.append((b['ts'], rise))
        dedup = []
        for t, r in rises:
            if not dedup or (t - dedup[-1][0]).total_seconds() > 1800:
                dedup.append((t, r))
        if len(dedup) >= 2:
            fp.append({
                'pattern': '多段拉升',
                'detail': f'{len(dedup)} 次 30min+{int(dedup[0][1]*100)}% 拉升 (首次 {dedup[0][0].strftime("%H:%M")} / 末次 {dedup[-1][0].strftime("%H:%M")})',
                'value': len(dedup),
            })

    # ── 3. 闪电砸盘: 1min 内跌 > 2.5%，报告最大跌幅 ──
    if summary:
        worst_drop = 0
        worst_detail = ''
        prev_ts, prev_mid = summary[0][0], (summary[0][1] + summary[0][2]) / 2
        for ts, b1, a1, *_ in summary[1:]:
            mid = (b1 + a1) / 2
            if ts - prev_ts <= 60_000:
                drop = (mid - prev_mid) / prev_mid
                if drop < -0.025 and abs(drop) > worst_drop:
                    worst_drop = abs(drop)
                    worst_detail = f'{to_dt(prev_ts).strftime("%H:%M:%S")} → {to_dt(ts).strftime("%H:%M:%S")} 跌 {drop*100:.2f}%'
            prev_ts, prev_mid = ts, mid
        if worst_drop > 0:
            fp.append({
                'pattern': '闪电砸盘',
                'detail': worst_detail,
                'value': worst_drop,
            })

    # ── 4. 横盘吸筹: 2h+ 振幅 < 5%，优先检测拉升前的横盘 ──
    if bars and len(bars) > 12:
        found_consol = None
        max_bars = len(bars) - 12
        for i in range(min(max_bars, len(bars) - 12)):
            window = bars[i:i+12]
            if len(window) < 12:
                continue
            if window[-1]['ts'] - window[0]['ts'] < timedelta(hours=1, minutes=45):
                continue
            prices = [p for b in window for p in (b['high'], b['low'])]
            r = (max(prices) - min(prices)) / min(prices)
            if r < 0.05:
                # 检查之后是否有拉升 (横盘后突破价值更高)
                after = bars[i+12:i+18] if i+18 <= len(bars) else bars[i+12:]
                if after:
                    after_high = max(b['high'] for b in after)
                    breakout_pct = (after_high - window[-1]['close']) / window[-1]['close']
                    if breakout_pct > 0.08:
                        found_consol = {
                            'pattern': '横盘后突破',
                            'detail': f'{window[0]["ts"].strftime("%H:%M")}-{window[-1]["ts"].strftime("%H:%M")} 振幅{r*100:.1f}% 后 +{breakout_pct*100:.1f}%',
                            'value': breakout_pct,
                        }
                        break
                    else:
                        if found_consol is None:
                            found_consol = {
                                'pattern': '横盘吸筹',
                                'detail': f'{window[0]["ts"].strftime("%H:%M")}-{window[-1]["ts"].strftime("%H:%M")} 振幅 {r*100:.1f}%',
                                'value': r,
                            }
        if found_consol:
            fp.append(found_consol)

    # ── 5. lopsided book: 取最大 ask/bid 比值 ──
    if summary:
        max_ratio = 0
        max_detail = ''
        for ts, b1, a1, bd, ad, imb in summary:
            if bd > 0 and ad > 100_000:
                ratio = ad / bd
                if ratio > 3 and ratio > max_ratio:
                    max_ratio = ratio
                    max_detail = f'{to_dt(ts).strftime("%H:%M:%S")} ask${int(ad/1000)}k vs bid${int(bd/1000)}k (比值 {ratio:.1f}x)'
        if max_ratio > 0:
            fp.append({
                'pattern': 'lopsided_book',
                'detail': max_detail,
                'value': max_ratio,
            })

    # ── 6. 急拉后派发: 1h 内涨 > 20%，之后 ask 墙出现 ──
    if bars and deep:
        for i, b in enumerate(bars):
            look_back = b['ts'] - timedelta(hours=1)
            base = next((bb for bb in bars if bb['ts'] >= look_back), None)
            if base and base['ts'] < b['ts']:
                rise = (b['high'] - base['open']) / base['open']
                if rise > 0.20:
                    # 检查该时间之后的 ask 墙
                    after_ts_ms = int(b['ts'].replace(tzinfo=UTC8).timestamp() * 1000) if b['ts'].tzinfo else int((b['ts'] + timedelta(hours=-8)).timestamp() * 1000)
                    after_deep = [d for d in deep if d[0] >= after_ts_ms]
                    if after_deep:
                        peak_ask = max(d[3] or 0 for d in after_deep)
                        if peak_ask > 150_000:
                            fp.append({
                                'pattern': '急拉后派发',
                                'detail': f'{base["ts"].strftime("%H:%M")}→{b["ts"].strftime("%H:%M")} +{rise*100:.0f}% 后 ask墙${int(peak_ask/1000)}k',
                                'value': rise,
                            })
                    break

    # ── 7. 撤墙砸盘: bid 1% 累计快速下降 30%+ ──
    if deep and len(deep) > 5:
        bids = [d[2] or 0 for d in deep]
        for i in range(len(bids) - 5):
            window = bids[i:i+5]
            if window[0] > 100_000:
                drop_ratio = (window[0] - min(window[1:])) / window[0]
                if drop_ratio > 0.30:
                    t = to_dt(deep[i][0])
                    fp.append({
                        'pattern': '撤墙砸盘',
                        'detail': f'{t.strftime("%H:%M")} bid墙从${int(window[0]/1000)}k 骤降 {drop_ratio*100:.0f}%',
                        'value': drop_ratio,
                    })
                    break

    return fp


def generate_narrative(bars, fp):
    """根据 K 线和指纹生成简短的操盘叙事"""
    if not bars:
        return '无 K 线数据，叙事不可用。'

    op = bars[0]['open']
    cl = bars[-1]['close']
    hi = max(b['high'] for b in bars)
    lo = min(b['low'] for b in bars)
    total_pct = (cl - op) / op * 100
    hi_pct = (hi - op) / op * 100
    lo_pct = (lo - op) / op * 100

    fp_names = [f['pattern'] for f in fp]

    lines = []

    # 开头: 整体走势
    if total_pct > 15:
        lines.append(f'本段行情净涨 **{total_pct:.1f}%**，区间顶部较开盘高 **{hi_pct:.1f}%**，呈拉升走势。')
    elif total_pct < -10:
        lines.append(f'本段行情净跌 **{abs(total_pct):.1f}%**，区间底部较开盘低 **{abs(lo_pct):.1f}%**，呈下行走势。')
    else:
        lines.append(f'本段行情波动，净变化 **{total_pct:+.1f}%**，区间振幅 **{hi_pct - lo_pct:.1f}%**。')

    # 各 pattern 对应的叙事
    if '横盘后突破' in fp_names:
        lines.append('行情初期处于横盘蓄势阶段，随后发生向上突破，符合吸筹后拉升操盘剧本。')
    elif '横盘吸筹' in fp_names:
        lines.append('存在明显的横盘整理阶段，价格窄幅震荡，可能是庄家吸筹期。')

    if '多段拉升' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == '多段拉升')
        lines.append(f'拉升为多段式结构：{detail}。典型庄家分批拉盘模式，每段拉升后短暂回调再继续。')

    if '急拉后派发' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == '急拉后派发')
        lines.append(f'急速拉升后立即出现大量 ask 挂单（{detail}），为典型的拉高出货派发手法。')
    elif '派发铁证' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == '派发铁证')
        lines.append(f'盘口出现大量 ask 挂单（{detail}），是庄家派发的直接证据。')

    if 'lopsided_book' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == 'lopsided_book')
        lines.append(f'盘口严重偏斜（{detail}），卖压远大于买压，价格承压明显。')

    if '撤墙砸盘' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == '撤墙砸盘')
        lines.append(f'出现撤墙操作（{detail}），bid 支撑突然消失，随后价格下跌。')

    if '闪电砸盘' in fp_names:
        detail = next(f['detail'] for f in fp if f['pattern'] == '闪电砸盘')
        lines.append(f'出现闪电砸盘（{detail}），短时大幅下跌触发恐慌盘。')

    if not lines[1:]:
        lines.append('无明显操盘手法特征，可能为自然波动或尚未被已知 pattern 覆盖的新手法。')

    return ' '.join(lines)


def write_case_md(symbol, from_ms, to_ms, summary, deep, events, shadow, tags, fp, out_md, png_name):
    duration_h = (to_ms - from_ms) / 3600_000
    bars = build_ohlc(summary, 5)

    if bars:
        op, cl = bars[0]['open'], bars[-1]['close']
        hi = max(b['high'] for b in bars)
        lo = min(b['low'] for b in bars)
    else:
        op = cl = hi = lo = 0

    # 写 case md
    lines = []
    lines.append(f'# {symbol} 操盘复盘 · {to_dt(from_ms).strftime("%Y-%m-%d %H:%M")} → {to_dt(to_ms).strftime("%Y-%m-%d %H:%M")} UTC+8')
    lines.append('')
    lines.append(f'> 生成: {datetime.now(UTC8).strftime("%Y-%m-%d %H:%M:%S")} UTC+8  ')
    lines.append(f'> 数据: ob_summary ({len(summary)} 行) + ob_deep_depth ({len(deep)} 行)  ')
    lines.append(f'> 图: ![chart]({png_name})')
    lines.append('')
    lines.append('## 元数据')
    lines.append('')
    lines.append('| 项 | 值 |')
    lines.append('|----|----|')
    lines.append(f'| Symbol | `{symbol}` |')
    lines.append(f'| 时长 | {duration_h:.1f}h |')
    if op > 0:
        lines.append(f'| 起价 | ${op:.5f} |')
        lines.append(f'| 终价 | ${cl:.5f} ({(cl-op)/op*100:+.2f}%) |')
        lines.append(f'| 区间最高 | ${hi:.5f} ({(hi-op)/op*100:+.2f}%) |')
        lines.append(f'| 区间最低 | ${lo:.5f} ({(lo-op)/op*100:+.2f}%) |')
    lines.append(f'| 标签 | {tags or "未标注"} |')
    lines.append('')

    # 行情阶段表 (按 15min 桶聚合)
    if summary:
        lines.append('## 行情阶段 (15min 桶)')
        lines.append('')
        lines.append('| 时间 | mid 价 | 涨幅 | bid 1档$ | ask 1档$ |')
        lines.append('|------|--------|------|----------|----------|')
        buckets = defaultdict(list)
        for ts, b1, a1, bd, ad, _ in summary:
            d = to_dt(ts)
            floor_min = (d.minute // 15) * 15
            key = d.replace(minute=floor_min, second=0, microsecond=0)
            buckets[key].append(((b1+a1)/2, bd, ad))
        keys = sorted(buckets)[:20]  # 最多 20 行
        open_p = None
        for k in keys:
            pts = buckets[k]
            mid = sum(p[0] for p in pts) / len(pts)
            if open_p is None:
                open_p = mid
            pct = (mid - open_p) / open_p * 100
            bd = sum(p[1] for p in pts) / len(pts)
            ad = sum(p[2] for p in pts) / len(pts)
            lines.append(f'| {k.strftime("%m-%d %H:%M")} | {mid:.5f} | {pct:+.2f}% | ${bd:.0f} | ${ad:.0f} |')
        lines.append('')

    # 关键深度签名
    if deep:
        max_bid_1pct = max((d[2] or 0, to_dt(d[0])) for d in deep)
        max_ask_1pct = max((d[3] or 0, to_dt(d[0])) for d in deep)
        max_bid_wall = max((d[5] or 0, to_dt(d[0]), d[6]) for d in deep)
        max_ask_wall = max((d[7] or 0, to_dt(d[0]), d[8]) for d in deep)
        lines.append('## 关键深度签名')
        lines.append('')
        lines.append('| 指标 | 时刻 | 数值 |')
        lines.append('|------|------|------|')
        lines.append(f'| Peak bid 1% 累计 | {max_bid_1pct[1].strftime("%m-%d %H:%M")} | ${int(max_bid_1pct[0])} |')
        lines.append(f'| Peak ask 1% 累计 | {max_ask_1pct[1].strftime("%m-%d %H:%M")} | ${int(max_ask_1pct[0])} |')
        lines.append(f'| Peak bid 单墙 | {max_bid_wall[1].strftime("%m-%d %H:%M")} | ${int(max_bid_wall[0])}@{max_bid_wall[2]:.5f} |')
        lines.append(f'| Peak ask 单墙 | {max_ask_wall[1].strftime("%m-%d %H:%M")} | ${int(max_ask_wall[0])}@{max_ask_wall[2]:.5f} |')
        lines.append('')

    # 操盘剧本叙事
    narrative = generate_narrative(bars, fp)
    lines.append('## 操盘剧本')
    lines.append('')
    lines.append(narrative)
    lines.append('')

    # 检测器命中诊断
    lines.append('## 检测器命中诊断')
    lines.append('')
    lines.append(f'- `ob_events` 命中: **{len(events)} 条**')
    lines.append(f'- `shadow_signals` 命中: **{len(shadow)} 条** (其中推送 {sum(1 for s in shadow if s[6]==1)} 条)')
    if events:
        lines.append('')
        lines.append('### 实际触发事件')
        for ts, lv, types, details in events[:20]:
            t = to_dt(ts).strftime('%m-%d %H:%M:%S')
            lines.append(f'- `{t}` **{lv}** [{types}] {(details or "")[:80]}')
    if not events and bars and op > 0:
        amp = (hi - lo) / op
        missed = []
        fp_names = [f['pattern'] for f in fp]
        if amp > 0.10:
            missed.append(f'振幅 {amp*100:.0f}% > 10%')
        if '派发铁证' in fp_names:
            missed.append('派发铁证 (ask 1% > $200k)')
        if '闪电砸盘' in fp_names:
            val = next(f['value'] for f in fp if f['pattern'] == '闪电砸盘')
            missed.append(f'闪电砸盘 ({val*100:.1f}% 跌幅)')
        if 'lopsided_book' in fp_names:
            missed.append('lopsided_book (ask > bid×3)')
        if '撤墙砸盘' in fp_names:
            missed.append('撤墙砸盘')
        if missed:
            lines.append('')
            lines.append(f'⚠️ **检测器盲区**: 以下信号应触发但未触发 → {" / ".join(missed)}')
            lines.append('> 建议: 检查 ob-detector.ts 相关规则阈值是否过高')
    lines.append('')

    # 指纹
    lines.append('## 指纹特征')
    lines.append('')
    if fp:
        for f in fp:
            lines.append(f'- **{f["pattern"]}**: {f["detail"]}')
    else:
        lines.append('- 未匹配任何已知 pattern')
    lines.append('')

    out_md.write_text('\n'.join(lines), encoding='utf-8')


def append_index(symbol, date_str, tags, fp):
    """更新 _index.md"""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text('# OB 案例库索引\n\n按时间倒序排列。\n\n| 日期 | 币 | 标签 | 指纹 | 链接 |\n|------|-----|------|------|------|\n', encoding='utf-8')
    content = INDEX_FILE.read_text(encoding='utf-8')
    fp_short = ', '.join(set(f['pattern'] for f in fp)) if fp else '-'
    case_name = f'{symbol}-{date_str}'
    # 已存在则不重复加
    if f'[{case_name}]' in content:
        return
    new_row = f'| {date_str} | `{symbol}` | {tags or "-"} | {fp_short} | [{case_name}](./{case_name}.md) |\n'
    # 在表头后插入
    if '|------|' in content:
        content = content.replace('|------|------|\n', f'|------|------|\n{new_row}', 1)
    else:
        content += new_row
    INDEX_FILE.write_text(content, encoding='utf-8')


def append_patterns(symbol, date_str, fp):
    """累积到 _patterns.md (按 pattern 桶分类)"""
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PATTERNS_FILE.exists():
        PATTERNS_FILE.write_text('# OB 操盘指纹库\n\n每次 replay 自动 append。当某个 pattern 桶 ≥ 3 个样本时，考虑加入 ob-detector.ts 规则。\n\n', encoding='utf-8')
    content = PATTERNS_FILE.read_text(encoding='utf-8')

    # 按 pattern 分桶
    for f in fp:
        pattern = f['pattern']
        header = f'## {pattern}'
        entry = f'- `{symbol}` ({date_str}): {f["detail"]}\n'
        if header in content:
            # 在该 section 末尾 append
            idx = content.find(header)
            next_h = content.find('\n## ', idx + 1)
            if next_h < 0:
                content = content + entry if content.endswith('\n') else content + '\n' + entry
            else:
                content = content[:next_h] + entry + content[next_h:]
        else:
            content += f'\n{header}\n\n{entry}'
    PATTERNS_FILE.write_text(content, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', required=True)
    ap.add_argument('--from', dest='from_str', help='起始时间 (UTC+8), 如 "2026-05-19 14:00"')
    ap.add_argument('--to', dest='to_str', help='终止时间')
    ap.add_argument('--hours', type=float, help='最近 N 小时')
    ap.add_argument('--auto', action='store_true', help='自动找最大波幅窗口')
    ap.add_argument('--tags', default='')
    ap.add_argument('--look-back', type=float, default=48, help='auto 模式回溯小时数, 默认 48')
    args = ap.parse_args()

    symbol = args.symbol.upper()
    if not symbol.endswith('USDT'):
        symbol += 'USDT'

    # 决定时间窗
    if args.auto:
        from_ms, to_ms = auto_window(symbol, args.look_back)
        if from_ms is None:
            print(f'[ob-replay] {symbol} no significant window found in last {args.look_back}h')
            sys.exit(1)
    elif args.hours:
        to_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        from_ms = to_ms - int(args.hours * 3600_000)
    elif args.from_str and args.to_str:
        from_dt = parse_local_dt(args.from_str).replace(tzinfo=UTC8)
        to_dt_v = parse_local_dt(args.to_str).replace(tzinfo=UTC8)
        from_ms = int(from_dt.timestamp() * 1000)
        to_ms = int(to_dt_v.timestamp() * 1000)
    else:
        ap.error('需要 --auto 或 --hours 或 --from+--to')

    print(f'[ob-replay] {symbol} window {to_dt(from_ms)} → {to_dt(to_ms)}')

    summary, deep, events, shadow = load_data(symbol, from_ms, to_ms)
    print(f'[ob-replay] data: ob_summary={len(summary)}, ob_deep_depth={len(deep)}, events={len(events)}, shadow={len(shadow)}')

    if not summary and not deep:
        print(f'[ob-replay] no data, exit')
        sys.exit(1)

    # 命名
    date_str = to_dt(from_ms).strftime('%Y%m%d')
    case_name = f'{symbol}-{date_str}'
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    out_png = CASES_DIR / f'{case_name}.png'
    out_md = CASES_DIR / f'{case_name}.md'

    render(symbol, from_ms, to_ms, summary, deep, out_png, args.tags)
    bars = build_ohlc(summary, 5)
    fp = extract_fingerprint(summary, deep, bars)
    write_case_md(symbol, from_ms, to_ms, summary, deep, events, shadow, args.tags, fp, out_md, f'{case_name}.png')
    append_index(symbol, date_str, args.tags, fp)
    append_patterns(symbol, date_str, fp)

    print(f'[ob-replay] ✅ saved:')
    print(f'  - {out_png.relative_to(REPO_ROOT)}')
    print(f'  - {out_md.relative_to(REPO_ROOT)}')
    print(f'[ob-replay] fingerprints: {len(fp)} ({", ".join(f["pattern"] for f in fp) if fp else "none"})')


if __name__ == '__main__':
    main()

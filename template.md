# {SYMBOL} 操盘复盘 · {DATE_RANGE}

> 生成时间: {GENERATED_AT}  
> 数据源: ob_summary + ob_deep_depth (本地 SQLite)  
> 图: `{SYMBOL}-{DATE}.png`

## 元数据

| 项 | 值 |
|----|----|
| Symbol | `{SYMBOL}` |
| 时间窗 | {FROM_UTC8} → {TO_UTC8} ({DURATION_H}h) |
| 起价 | ${OPEN} |
| 终价 | ${CLOSE} ({CLOSE_PCT}) |
| 区间最高 | ${HIGH} ({HIGH_PCT}) |
| 区间最低 | ${LOW} ({LOW_PCT}) |
| 总成交量 | {VOLUME_USDT} USDT |
| **标签** | {TAGS} |

## 行情阶段表

| # | 时间 (UTC+8) | mid 价 | 涨幅 | 性质 |
|---|--------------|--------|------|------|
{STAGE_TABLE}

## 关键深度签名

| 指标 | 时刻 | 数值 | 含义 |
|------|------|------|------|
| Peak bid 1% 累计 | {PEAK_BID_TIME} | ${PEAK_BID_USD} | {PEAK_BID_INTERP} |
| Peak ask 1% 累计 | {PEAK_ASK_TIME} | ${PEAK_ASK_USD} | {PEAK_ASK_INTERP} |
| 最大 lopsided | {LOPSIDED_TIME} | ask/bid={LOPSIDED_RATIO}x | {LOPSIDED_INTERP} |
| 最大 bid 单墙 | {MAX_BID_WALL_TIME} | ${MAX_BID_WALL}@{MAX_BID_PRICE} | {MAX_BID_INTERP} |
| 最大 ask 单墙 | {MAX_ASK_WALL_TIME} | ${MAX_ASK_WALL}@{MAX_ASK_PRICE} | {MAX_ASK_INTERP} |

## 操盘剧本

{NARRATIVE}

## 检测器命中诊断

### 实际触发的 ob_events
{ACTUAL_EVENTS}

### 应触发但未触发 (检测器盲区)
{MISSED_EVENTS}

### shadow_signals (价差监控)
{SHADOW_SIGNALS}

## 指纹特征 (已加入 _patterns.md)

{FINGERPRINT}

## 关联案例

可能与下列案例同源:
{RELATED_CASES}

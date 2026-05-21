---
name: ob-replay
description: "Use when user asks to replay / analyze / 复盘 / 拆解 a coin's orderbook movement, manipulation pattern, pump/dump scenario, or wants to see the K-line + depth wall evolution. Keywords: 复盘 / 操盘 / 盘口 / orderbook / 深度图 / 庄家 / 派发 / 拉抽 / case study. Also trigger when user asks to generate a depth chart for a specific symbol, or wants to compare detected patterns across historical cases. NOT for live monitoring or for placing trades."
license: MIT
metadata:
  author: 0xBennie
  version: "1.2.0"
---

# OB Replay — 单币种盘口操盘复盘工具

把任意一个币的某段历史时间窗口转成"K 线 + 1档深度 + 1% 累计深度墙"三层合并图 + 操盘剧本叙事 + 检测器盲区诊断，自动写入案例库供学习和规则优化。

## 数据源
- `data/orderbook.db.ob_summary` (10s 间隔，保留 2 天) — K 线 + 1档深度
- `data/orderbook.db.ob_deep_depth` (30s 间隔，保留 30 天) — 1% 累计深度 + 巨墙
- `data/signals.db.shadow_signals` — 同期价差信号 / 漏推记录
- `data/orderbook.db.ob_events` — 检测器命中事件

## 调用方式

### 1. 自然语言触发 (推荐)
- "复盘 CHIP 今天那段" → 自动找最近 48h 内最大波幅窗口
- "复盘 LAB 上午那一段" → LLM 解析时间
- "拆解一下 FIDA 15:00 那次砸盘" → 精确时间窗

### 2. 显式参数
```bash
python3 replay.py --symbol CHIPUSDT \
  --from "2026-05-20 15:00" \
  --to   "2026-05-21 03:00" \
  --tags "派发铁证,撤墙"
```

### 3. 自动找窗口
```bash
python3 replay.py --symbol LABUSDT --auto
# 扫该币最近 48h 找振幅 > 5% 的最大窗口
```

### 4. 批量回溯 (全部数据)
```bash
python3 backfill.py --days 30 --min-range 0.08 --max-cases 500
# 扫30天内所有振幅>8%的symbol-day，生成案例库
```

## 输出物 (每次跑都生成)

| 文件 | 路径 | 内容 |
|------|------|------|
| **合并图** | `docs/ob-cases/<SYMBOL>-<YYYYMMDD>.png` | K 线 + 1档深度 + 1% 累计墙 三层 |
| **分析 md** | `docs/ob-cases/<SYMBOL>-<YYYYMMDD>.md` | 操盘剧本叙事 + 关键深度签名 + 检测器盲区诊断 + 指纹标签 |
| 索引更新 | `docs/ob-cases/_index.md` | 追加新案例链接 |
| 指纹累积 | `docs/ob-cases/_patterns.md` | 追加该案例的操盘指纹特征 |

## 8 种操盘指纹 (793 案例蒸馏，全部已入检测器)

| Pattern | 触发条件 | 样本数 | 检测器规则 |
|---------|----------|--------|-----------|
| `bid_wall_pull` | bid 1% 累计 5档内降 30%+ | **350** | ✅ `bid_wall_pull` |
| `lopsided_book` | ask > bid × 3 AND ask > $100k | **341** | ✅ `lopsided_book` |
| `flash_dump` | 1min 内跌 > 2.5% | **316** | ✅ `flash_dump` |
| `distribution_wall` | ask 1% 累计 > $200k | **254** | ✅ `distribution_wall` |
| `pump_continuation` | 当前 30min +15% 且 6h 内有过 +20% | 18 | ✅ `pump_continuation` |
| `rapid_pump_distribution` | 1h +20% 后 ask/bid > 3x | 10 | ✅ `rapid_pump_distribution` |
| `consolidation_breakout` | 2h 振幅 < 5% 后 5min 突破 > 5% | 常见 | ✅ `breakout_after_consolidation` |
| `consolidation_then_pump` | 2h 振幅 < 5% 后 +8% | 常见 | ✅ `breakout_after_consolidation` |

**所有 30+ 样本的 pattern 均已进入实时检测器。学习闭环已关闭。**

## 重复作案排行 (793 案例, 30 天)

| 排名 | 符号 | 次数 | 典型手法 |
|------|------|------|---------|
| 1 | LABUSDT | 34 | 派发 + 偏斜 + 闪电砸盘 |
| 2 | JTOUSDT | 28 | 撤墙 + 偏斜 |
| 3 | BILLUSDT | 28 | 派发 + 撤墙 |
| 4 | ONDOUSDT | 25 | 多日持续派发墙 |
| 5 | DOGSUSDT | 24 | 闪电砸盘 + 多段拉升 |

高频出现 = 固定做市商/庄家团队，操盘手法可预测。

## 检测器盲区诊断规则

当案例满足以下条件但 ob_events=0 时，自动标记盲区并给出优化建议：
- 振幅 > 10% 且无任何触发
- 任何已知 pattern 存在但未推送

## 何时将 Pattern 加入检测器

| 条件 | 建议 |
|------|------|
| pattern 桶 ≥ 30 样本 | **立刻**添加规则 |
| 桶 10-29 样本 | 先观察，阈值稍高 |
| 桶 < 10 样本 | 继续收集数据 |
| 重复作案者 ≥ 10 次 | 加入专项监控名单 |

## 边界

- ❌ **不复盘未在 OB 池里的币** — 没有数据
- ❌ **超过 30 天前的窗口** — ob_summary 已 cleanup，只剩 deep_depth
- ✅ 自动从 SQLite 查，不依赖外部 API
- ✅ 不下单、不推送，纯分析

## 何时建议运行

| 场景 | 建议 |
|------|------|
| 系统漏推了一个大波 | 立刻复盘找盲区原因 |
| 看到某币奇怪的盘口动作 | 复盘看是否操盘剧本 |
| 判断当前持仓的阶段 | `--hours 12` 看最近动作 |
| 周日每周回顾 | 跑 `backfill` 补全本周所有大波动 |
| 修改检测器规则前 | 先用历史案例验证规则命中率 |

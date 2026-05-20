---
name: ob-replay
description: "Use when user asks to replay / analyze / 复盘 / 拆解 a coin's orderbook movement, manipulation pattern, pump/dump scenario, or wants to see the K-line + depth wall evolution. Keywords: 复盘 / 操盘 / 盘口 / orderbook / 深度图 / 庄家 / 派发 / 拉抽 / case study. Also trigger when user asks to generate a depth chart for a specific symbol, or wants to compare detected patterns across historical cases. NOT for live monitoring (that's spread-monitor) or for placing trades."
license: MIT
metadata:
  author: BennieArb
  version: "1.1.0"
---

# OB Replay — 单币种盘口操盘复盘工具

把任意一个币的某段历史时间窗口转成"K 线 + 1档深度 + 1% 累计深度墙"三层合并图 + 操盘剧本文字 + 检测器盲区诊断，自动写入案例库供未来学习。

## 数据源
- `data/orderbook.db.ob_summary`(10s 间隔，保留 2 天) — K 线 + 1档深度
- `data/orderbook.db.ob_deep_depth`(30s 间隔，保留 30 天) — 1% 累计深度 + 巨墙
- `data/signals.db.shadow_signals` — 同期价差信号 / 漏推记录
- `data/orderbook.db.ob_events` — 检测器命中事件

## 调用方式

### 1. 自然语言触发 (推荐)
- "复盘 EDEN"  → 自动找最近 24h 内最大波幅窗口
- "复盘 STAR 昨晚那一段" → LLM 解析时间
- "拆解一下 APR 21:18 那次砸盘" → 精确时间窗

### 2. 显式参数
```bash
python3 .agents/skills/ob-replay/replay.py --symbol EDENUSDT \
  --from "2026-05-19T14:00:00+08:00" \
  --to   "2026-05-20T01:30:00+08:00" \
  --tags "多段拉升,派发铁证"
```

### 3. 自动找窗口
```bash
python3 .agents/skills/ob-replay/replay.py --symbol EDENUSDT --auto
# 扫该币最近 48h 找振幅 > 5% 的最大窗口
```

### 4. 批量回溯 (全部数据)
```bash
python3 .agents/skills/ob-replay/backfill.py --days 30 --min-range 0.08 --max-cases 600
# 扫30天内所有振幅>8%的symbol-day, 生成案例库
```

## 输出物 (每次跑都生成)

| 文件 | 路径 | 内容 |
|------|------|------|
| **合并图** | `docs/ob-cases/<SYMBOL>-<YYYYMMDD>.png` | K 线 + 1档深度 + 1% 累计墙 三层 |
| **分析 md** | `docs/ob-cases/<SYMBOL>-<YYYYMMDD>.md` | 操盘剧本 + 关键数据表 + 检测器命中诊断 + 指纹标签 |
| 索引更新 | `docs/ob-cases/_index.md` | 追加新案例链接 |
| 指纹累积 | `docs/ob-cases/_patterns.md` | 追加该案例的操盘指纹特征 |

## 8 种操盘指纹 (从 500+ 案例蒸馏)

| Pattern | 触发条件 | 样本数 | ob-detector 规则 |
|---------|----------|--------|-----------------|
| `闪电砸盘` | 1min 内跌 > 2.5% | **156+** | ✅ `flash_dump` (已加) |
| `lopsided_book` | ask > bid × 3 AND ask > $100k | **150+** | ✅ `lopsided_book` + `distribution_wall` |
| `派发铁证` | ask 1% 累计 > $200k | **112+** | ✅ `distribution_wall` (已加) |
| `撤墙砸盘` | bid 1% 累计 5档内降 30%+ | **42+** | ⚠️ 待加 (>30 样本阈值达到) |
| `多段拉升` | 6-12h 内 ≥2 次 30min +15% | 11+ | ✅ `pump_continuation` |
| `横盘吸筹` | 2h 振幅 < 5% | 常见 | ✅ `breakout_after_consolidation` |
| `横盘后突破` | 横盘 2h 后 +8% | 更有价值 | ✅ `breakout_after_consolidation` |
| `急拉后派发` | 1h +20% 后 ask 墙 > $150k | 中 | ⚠️ 待加 |

## 重复作案嫌疑人 (300+ 案例统计)

基于 `_patterns.md` 统计，最高频出现的操盘标的：

| 排名 | 符号 | 出现次数 | 典型手法 |
|------|------|----------|----------|
| 1 | LABUSDT | 15+ | 派发铁证 + lopsided |
| 2 | DOGSUSDT | 12+ | 闪电砸盘 + 多段拉升 |
| 3 | BSBUSDT | 11+ | 多 pattern 组合 |
| 4 | BUSDT | 10+ | 大额派发墙 |
| 5 | FIDAUSDT | 9+ | 横盘后急拉派发 |
| 6 | BILLUSDT | 8+ | 派发铁证 + lopsided |

重复出现意味着有固定做市商/庄家团队，入场和出货手法可预测。

## 检测器盲区诊断规则

当案例满足以下条件但 ob_events=0 时，自动标记盲区：
- 振幅 > 10% 且无任何触发
- 派发铁证存在但未推送
- 闪电砸盘 > 4% 但未触发
- lopsided_book 比值 > 5x 但未触发

**阈值优化建议** (基于 300+ 案例):
- 闪电砸盘: 当前阈值过高，大量 2.5-4% 的案例未触发 → 建议加 flash_dump 规则到 ob-detector.ts
- 派发铁证: $200k 门槛合理，但中等市值币 $100k 已是警报级别
- lopsided_book: 3x 合理，但需配合绝对金额 $50k+ 过滤噪音

## 何时将 Pattern 加入 ob-detector.ts

| 条件 | 建议 |
|------|------|
| pattern 桶 ≥ 30 样本 | **立刻**添加规则 |
| 桶 10-29 样本 | 先观察，阈值稍高 |
| 桶 < 10 样本 | 继续收集数据 |
| 重复作案者 ≥ 5 次 | 加入专项监控名单 |

**当前待加规则** (基于 500+ 案例统计):
- `flash_dump`: ✅ **已加** (156 样本支持，1min 跌 > 3%)
- `distribution_wall`: ✅ **已加** (112 样本，ask > bid×5 AND > $150k)
- `bid_wall_pull`: ⚠️ **待加** (42 样本，bid 1% 累计快速下降 30%+)

## 历史案例库

参见 `docs/ob-cases/_index.md`。每个案例独立 md。

## 学习闭环

每次复盘后：
1. 自动提取该案例的"操盘指纹"
2. 追加到 `_patterns.md` 对应 pattern 桶
3. 当某 pattern 桶 ≥ 30 个样本时，**提示开发者将其转化为 ob-detector.ts 新规则**
4. 已有规则的命中率反馈到 `_patterns.md` 让 review 时优化阈值
5. 每周运行 backfill 补全历史案例库

## 边界

- ❌ **不复盘未在 OB 池里的币** — 没有数据
- ❌ **不超过 30 天前的窗口** — ob_summary 已 cleanup, 只剩 deep_depth
- ✅ 自动从 SQLite 查，不依赖外部 API
- ✅ 不下单、不推送，纯分析

## 何时建议运行

| 场景 | 建议 |
|------|------|
| 系统漏推了一个大波 | 立刻复盘找原因 |
| 看到某币奇怪的盘口动作 | 复盘看是否操盘剧本 |
| 周日每周回顾 | 跑 backfill 补全本周所有大波动 |
| 修改检测器规则前 | 先用历史案例验证规则命中率 |
| 有持仓需要判断 | replay 最近 12h 看当前 pattern |

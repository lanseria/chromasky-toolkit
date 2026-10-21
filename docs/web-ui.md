# Web UI 设计与接口契约

> 本文件是「Web 界面重构」的权威契约：后端路由、模板上下文、事件数据模型与视觉要求都以本文件为准。
> 后端（`server.py` / `gallery.py`）与前端（`src/templates/` / `src/static/`）必须严格对齐。

## 1. 重构目标

1. 首页**不再展示分时指数图**，也**不再生成/存储**分时指数图（`outputs/maps/individual/**`、`outputs/maps_webp/individual/**`）。
2. 首页重点展示**当前最近的未来**一场日出或日落的火烧云综合图；没有未来预报时优雅回退到「最近一次预报」。
3. 明确提供**未来**与**过去**两个入口，并且可以按日期、事件类型进行**历史查询**。
4. 整体视觉与交互重新设计：暗色天空摄影风格、信息层级清晰、桌面与移动端可用、无外部 CDN 依赖。

## 2. 页面与路由

| 路由 | 模板 | 说明 |
|------|------|------|
| `GET /` | `index.html` | 首页：最近的未来事件 Hero + 接下来列表 + 近日回看 |
| `GET /future` | `future.html` | 未来预报：按天分组列出所有未结束事件 |
| `GET /history` | `history.html` | 历史存档：筛选 + 按月分组 + 日期精确/最近查询 |
| `GET /archive` | — | `307` 重定向到 `/history`（兼容旧链接） |
| `GET /api/events` | JSON | 事件列表查询，供脚本/前端使用 |
| `POST /trigger-job` | JSON | 手动触发一次完整工作流（保留） |
| `GET /api/glow-index` | JSON | 单点指数查询（保留，不改） |
| `/static/*` | 静态 | `outputs/` 目录（WebP/PNG 图片） |
| `/assets/*` | 静态 | `src/static/` 目录（CSS/JS） |

模板根目录：`src/templates/`。所有页面模板继承 `base.html`。

## 3. 时间语义

事件组（Event Group）= **日期 + 事件类型**，两者共同唯一确定一张综合图。

- 时间窗口：`config.event_times_for_date(date, event)`，返回该事件类型的本地时间点列表
  （如春秋季日落 `["18:00", "19:00", "20:00", "21:00"]`）。**必须按目标日期的月份选季节**，
  不能用「当前季节」推断历史日期。
- 窗口开始 `start` = 窗口内最早时间点；窗口结束 `end` = 最晚时间点（均带 `Asia/Shanghai` 时区）。
- 状态：
  - `upcoming`：`now < start`
  - `live`：`start <= now <= end`
  - `past`：`now > end`
- 「未结束」= `now <= end`（包含 `upcoming` 与 `live`）。
- 首页 Hero 选择顺序：
  1. 存在 `live` 事件 → 取 `live` 中 `start` 最早者，`hero_kind="live"`；
  2. 否则取 `upcoming` 中 `start` 最早者，`hero_kind="upcoming"`；
  3. 都没有 → 取 `past` 中 `end` 最晚者，`hero_kind="latest"`，并给出提示；
  4. 一张图都没有 → `hero=None`，`hero_kind="empty"`。

## 4. 事件对象（event dict）

后端构造、前端直接使用。所有时间字符串均按 `Asia/Shanghai`。

| 字段 | 类型 | 示例 | 说明 |
|------|------|------|------|
| `key` | str | `2026-05-12_sunset` | 唯一键 |
| `date` | str | `2026-05-12` | 日期 |
| `date_label` | str | `5月12日 周二` | 展示用短日期 |
| `date_label_full` | str | `2026年5月12日 周二` | 完整日期 |
| `weekday` | str | `周二` | 星期 |
| `day_label` | str | `今天` / `明天` / `5月12日 周二` | 相对日标签 |
| `event` | str | `sunset` | `sunrise` / `sunset` |
| `event_label` | str | `日落` | 中文事件名 |
| `window_text` | str | `19:00 – 22:00` | 时间窗口（endash） |
| `start_iso` | str | `2026-05-12T19:00:00+08:00` | 窗口开始 ISO8601 |
| `end_iso` | str | `2026-05-12T22:00:00+08:00` | 窗口结束 ISO8601 |
| `generated_at` | str | `2026-05-12 16:04` | 图片生成时间（本地） |
| `generated_iso` | str | `2026-05-12T16:04:13+08:00` | 图片生成时间 ISO8601 |
| `generated_ago` | str | `5 个月前` | 生成时间的人类可读描述 |
| `image_url` | str | `/static/maps_webp/composite/glow_index_composite_2026-05-12_sunset.webp` | 图片地址（优先 WebP，回退 PNG） |
| `image_name` | str | `glow_index_composite_2026-05-12_sunset.webp` | 文件名 |
| `image_title` | str | `2026年5月12日 日落 · 19:00 – 22:00` | 图片 alt/标题 |
| `status` | str | `past` | `upcoming` / `live` / `past` |
| `is_upcoming` | bool | `false` | 是否未结束 |
| `relative_days` | int | `-1` | 日期相对今天的天数 |

## 5. 页面上下文

### 5.1 公共字段（所有页面）

| 字段 | 类型 | 说明 |
|------|------|------|
| `request` | Request | Jinja2/FastAPI 必需 |
| `page` | str | `home` / `future` / `history` |
| `now_iso` | str | 当前时间 ISO8601（前端倒计时基准） |
| `now_text` | str | `2026年10月21日 15:13` |
| `last_updated_iso` | str \| None | 最近一张图的生成时间 ISO8601 |
| `last_updated_text` | str \| None | `2026年5月12日 16:04` |
| `data_age_text` | str \| None | `5 个月前` |
| `has_any_maps` | bool | 是否存在任意存档 |
| `total_count` | int | 存档总事件数 |
| `upcoming_count` | int | 未结束事件数 |
| `past_count` | int | 已结束事件数 |

### 5.2 首页 `index.html`

| 字段 | 类型 | 说明 |
|------|------|------|
| `hero` | dict \| None | Hero 事件对象 |
| `hero_kind` | str | `upcoming` / `live` / `latest` / `empty` |
| `hero_notice` | str \| None | Hero 下方的提示（如无未来预报） |
| `next_events` | list[dict] | 除 Hero 外的未结束事件，按时间升序，最多 6 条 |
| `recent_past` | list[dict] | 最近结束的事件，按时间降序，最多 4 条 |

### 5.3 未来页 `future.html`

| 字段 | 类型 | 说明 |
|------|------|------|
| `days` | list[day] | 按日期升序分组，仅包含未结束事件 |
| `future_count` | int | 未来事件总数 |
| `hero_notice` | str \| None | 顶部提示（如暂无未来预报） |

`day` 结构：

| 字段 | 类型 | 示例 |
|------|------|------|
| `date` | str | `2026-10-21` |
| `date_label` | str | `10月21日 周二` |
| `weekday` | str | `周二` |
| `day_label` | str | `今天` |
| `is_today` | bool | `true` |
| `events` | list[dict] | 当天 `sunrise` 在前、`sunset` 在后 |

### 5.4 历史页 `history.html`

| 字段 | 类型 | 说明 |
|------|------|------|
| `filters` | dict | 回填表单：`scope` / `event` / `date_from` / `date_to` / `date` / `sort` |
| `history_total` | int | 当前筛选命中的事件数 |
| `month_groups` | list[month] | 按月份降序分组（`sort=asc` 时升序） |
| `match_note` | str \| None | 日期近似匹配提示 |
| `filters_error` | str \| None | 日期格式错误等友好提示 |
| `scope_counts` | dict | `{"all": int, "past": int, "future": int}` |

`month` 结构：`{"key": "2026-05", "label": "2026年5月", "count": 4, "events": [dict]}`。

### 5.5 历史页查询参数

| 参数 | 取值 | 默认 | 说明 |
|------|------|------|------|
| `scope` | `past` / `all` / `future` | `past` | 历史页默认只看已结束事件 |
| `event` | `all` / `sunrise` / `sunset` | `all` | 事件类型过滤 |
| `from` | `YYYY-MM-DD` | 空 | 起始日期（含） |
| `to` | `YYYY-MM-DD` | 空 | 结束日期（含） |
| `date` | `YYYY-MM-DD` | 空 | 精确日期查询；该日无存档时回退到最接近的一天 |
| `sort` | `desc` / `asc` | `desc` | 日期排序 |

`date` 优先于 `from` / `to`；`date` 非法时不报 4xx，而是忽略并写入 `filters_error`。
`date` 精确命中时 `match_note=None`；回退到最近日期时写入提示文案。

## 6. JSON API `/api/events`

查询参数：`scope`（`all`/`past`/`future`，默认 `all`）、`event`（默认 `all`）、`from`、`to`、`date`、`limit`（默认 50，最大 500）。

响应：

```json
{
  "now": "2026-10-21T15:13:00+08:00",
  "count": 4,
  "events": [ { "...": "同事件对象" } ]
}
```

`count` 为本次响应实际返回的条数（已应用 `limit`），`events` 按日期升序。

## 7. 视觉与交互要求

- **风格**：暗色（近黑蓝底）、暖色日落渐变点缀；地图图片是主角，UI 不抢画面。禁止花哨的玻璃拟态堆叠。
- **布局**：移动端优先的响应式；首页 Hero 大图 + 信息叠加；卡片网格在窄屏单列。
- **地图图片**：`object-fit: contain`（不要裁掉地图边缘），加载前有占位背景；Hero 图 `fetchpriority="high"`，其余 `loading="lazy"`。
- **交互**：图片可点击打开灯箱（原生 `<dialog>`，支持 Esc/点击遮罩关闭）；倒计时由 JS 每 30 秒刷新（无 JS 时显示绝对时间）；「更新预报」按钮调用 `POST /trigger-job` 并显示 toast（触发后不自动刷新页面）。
- **可访问性**：语义化 landmark、跳过导航链接、可见 focus ring、图片 alt 含日期与事件、对比度达标、尊重 `prefers-reduced-motion`。
- **无外部依赖**：不引用 CDN、外部字体或外部图标库；图标使用内联 SVG 或字符。
- **文件**：`src/static/app.css`、`src/static/app.js`；模板 `base.html` / `index.html` / `future.html` / `history.html`。
- **空状态**：无未来预报、无存档、筛选无结果都要有明确文案与操作入口（更新预报 / 清空筛选）。

## 8. 数据与存储约束

- 分时图（`individual`）不再生成、不再转换、不再展示；历史残留通过 `tools/cleanup_legacy_maps.py` 清理。
- 综合图仍为唯一存档产物：`outputs/maps/composite/glow_index_composite_{date}_{event}.png` → `outputs/maps_webp/composite/...webp`。
- XYZ 瓦片仍基于综合图生成，路径规则不变。
- `image_converter` 需要清理「源 PNG 已不存在」的陈旧 WebP，防止旧分时图复活。
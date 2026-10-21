# src/chromasky_toolkit/gallery.py
"""
Web UI 图库数据层。

职责：扫描综合图存档目录，把文件名解析成「事件对象」（event dict），
并提供首页 Hero 选择、未来按天分组、历史筛选、JSON API 查询等纯数据逻辑。

权威契约：docs/web-ui.md 第 3/4/5 节（字段名/语义以该文档为准）。
本模块不依赖 FastAPI，也不读取模板，便于单元测试与复用。
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from . import config

logger = logging.getLogger("ChromaSkyGallery")

# --- 常量 ---

# 中文星期标签，索引对应 date.weekday()（周一=0）
WEEKDAY_LABELS: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 事件中文名与排序权重（同一天 sunrise 在前、sunset 在后）
EVENT_LABELS: dict[str, str] = {"sunrise": "日出", "sunset": "日落"}
EVENT_ORDER: dict[str, int] = {"sunrise": 0, "sunset": 1}

# 允许的筛选枚举值
SCOPES: tuple[str, ...] = ("all", "past", "future")
EVENT_FILTERS: tuple[str, ...] = ("all", "sunrise", "sunset")

# 综合图文件名：glow_index_composite_{YYYY-MM-DD}_{sunrise|sunset}.{webp|png}
_COMPOSITE_PATTERN = re.compile(
    r"^glow_index_composite_(\d{4}-\d{2}-\d{2})_(sunrise|sunset)\.(webp|png)$",
    re.IGNORECASE,
)

# 图片 URL 前缀（/static 挂载到 outputs 目录）
_WEBP_URL_PREFIX = "/static/maps_webp/composite"
_PNG_URL_PREFIX = "/static/maps/composite"


# --- 时区与时间工具 ---


def _local_tz() -> ZoneInfo:
    """返回本地时区（Asia/Shanghai）；每次读取 config，便于测试覆盖。"""
    return ZoneInfo(config.LOCAL_TZ)


def now_local() -> datetime:
    """当前本地时间（带时区）。测试可通过 monkeypatch 本函数固定时间。"""
    return datetime.now(_local_tz())


def _resolve_now(now: datetime | None) -> datetime:
    """把外部传入的 now 规整为带 Asia/Shanghai 时区的 aware datetime。"""
    if now is None:
        return now_local()
    if now.tzinfo is None:
        return now.replace(tzinfo=_local_tz())
    return now.astimezone(_local_tz())


def weekday_label(target: date) -> str:
    """中文星期，如「周二」。"""
    return WEEKDAY_LABELS[target.weekday()]


def date_label(target: date) -> str:
    """展示用短日期，如「5月12日 周二」。"""
    return f"{target.month}月{target.day}日 {weekday_label(target)}"


def date_label_full(target: date) -> str:
    """完整日期，如「2026年5月12日 周二」。"""
    return f"{target.year}年{target.month}月{target.day}日 {weekday_label(target)}"


def _relative_day_label(target: date, today: date) -> str:
    """相对日标签：今天/明天/后天/昨天/前天，其余回退到短日期。"""
    offset = (target - today).days
    labels = {0: "今天", 1: "明天", 2: "后天", -1: "昨天", -2: "前天"}
    return labels.get(offset) or date_label(target)


def humanize_age(delta: timedelta) -> str:
    """
    把时间差转成人类可读描述：刚刚 / N 分钟前 / N 小时前 / N 天前 / N 个月前。

    1 个月按 30 天近似；未来时间（时钟偏差）按「刚刚」处理。
    """
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    days = hours // 24
    if days < 30:
        return f"{days} 天前"
    return f"{days // 30} 个月前"


def _age_text_from_iso(iso_text: str | None, now: datetime) -> str | None:
    """把 ISO 时间字符串转成人类可读的「多久以前」。"""
    if not iso_text:
        return None
    try:
        moment = datetime.fromisoformat(iso_text)
    except ValueError:  # pragma: no cover - 理论上不会出现，防御性处理
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_local_tz())
    return humanize_age(now - moment)


# --- 事件构造 ---


def _event_window(
    target_date: date, event: Literal["sunrise", "sunset"]
) -> tuple[list[str], datetime, datetime]:
    """
    返回 (时间点列表, 窗口开始, 窗口结束)。

    窗口开始 = 该事件类型时间点中最早者，结束 = 最晚者；
    季节按 target_date 自身月份选择（见 config.event_times_for_date）。
    """
    times = config.event_times_for_date(target_date, event)
    tz = _local_tz()
    start = datetime.combine(target_date, time.fromisoformat(times[0]), tzinfo=tz)
    end = datetime.combine(target_date, time.fromisoformat(times[-1]), tzinfo=tz)
    return times, start, end


def _status_for(window_start: datetime, window_end: datetime, now: datetime) -> str:
    """按契约判定状态：upcoming / live / past。"""
    if now < window_start:
        return "upcoming"
    if now <= window_end:
        return "live"
    return "past"


def _event_status(event: dict[str, Any], now: datetime) -> str:
    """基于事件对象内已保存的 ISO 时间重新判定状态。"""
    start = datetime.fromisoformat(event["start_iso"])
    end = datetime.fromisoformat(event["end_iso"])
    return _status_for(start, end, now)


def _is_unfinished(event: dict[str, Any], now: datetime) -> bool:
    """「未结束」= now <= end，即 upcoming 或 live。"""
    return now <= datetime.fromisoformat(event["end_iso"])


def _event_sort_key(event: dict[str, Any]) -> tuple[str, int]:
    """按日期升序、同一天 sunrise 在 sunset 之前排序。"""
    return event["date"], EVENT_ORDER.get(event["event"], 9)


def _event_start_key(event: dict[str, Any]) -> str:
    """按窗口开始时间升序排序用的键（ISO 字符串可直接比较）。"""
    return event["start_iso"]


def _event_end_key(event: dict[str, Any]) -> str:
    """按窗口结束时间排序用的键（ISO 字符串可直接比较）。"""
    return event["end_iso"]


def _build_event(
    target_date: date,
    event: Literal["sunrise", "sunset"],
    image_path: Path,
    url_prefix: str,
    now: datetime,
) -> dict[str, Any]:
    """根据日期、事件类型与图片文件构造契约要求的 event dict。"""
    times, start, end = _event_window(target_date, event)
    tz = _local_tz()

    # 生成时间取文件 mtime，统一转换到本地时区并去掉微秒
    generated = datetime.fromtimestamp(image_path.stat().st_mtime, tz=tz).replace(microsecond=0)
    status = _status_for(start, end, now)
    event_label = EVENT_LABELS[event]
    window_text = f"{times[0]} – {times[-1]}"
    short_date = date_label(target_date)
    full_date = date_label_full(target_date)

    return {
        "key": f"{target_date.isoformat()}_{event}",
        "date": target_date.isoformat(),
        "date_label": short_date,
        "date_label_full": full_date,
        "weekday": weekday_label(target_date),
        "day_label": _relative_day_label(target_date, now.date()),
        "event": event,
        "event_label": event_label,
        "window_text": window_text,
        "start_iso": start.isoformat(),
        "end_iso": end.isoformat(),
        # 图片信息
        "generated_at": generated.strftime("%Y-%m-%d %H:%M"),
        "generated_iso": generated.isoformat(),
        "generated_ago": humanize_age(now - generated),
        "image_url": f"{url_prefix}/{image_path.name}",
        "image_name": image_path.name,
        "image_title": (
            f"{target_date.year}年{target_date.month}月{target_date.day}日 "
            f"{event_label} · {window_text}"
        ),
        # 状态
        "status": status,
        "is_upcoming": status != "past",
        "relative_days": (target_date - now.date()).days,
    }


# --- 扫描存档 ---


def _webp_composite_dir() -> Path:
    """WebP 综合图目录（默认 outputs/maps_webp/composite）。"""
    return config.MAP_WEBP_OUTPUTS_DIR / "composite"


def _png_composite_dir() -> Path:
    """PNG 综合图目录（默认 outputs/maps/composite）。"""
    return config.MAP_OUTPUTS_DIR / "composite"


def scan_event_maps(
    webp_dir: Path | None = None,
    png_dir: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    扫描综合图存档目录，返回按日期升序排列的事件对象列表。

    - 优先 WebP（outputs/maps_webp/composite），缺失时回退 PNG（outputs/maps/composite）；
    - 目录不存在、文件名不合法、日历日期非法时跳过并记录日志，不抛异常；
    - 路径与 now 均可注入，默认读取 config 与当前时间（测试可 monkeypatch config）。
    """
    current = _resolve_now(now)
    directories: tuple[tuple[Path, str, str], ...] = (
        (webp_dir if webp_dir is not None else _webp_composite_dir(), _WEBP_URL_PREFIX, "webp"),
        (png_dir if png_dir is not None else _png_composite_dir(), _PNG_URL_PREFIX, "png"),
    )

    # (date_str, event) -> (path, url_prefix)；先扫 WebP，因此同 key 时 WebP 优先
    chosen: dict[tuple[str, str], tuple[Path, str]] = {}

    for directory, url_prefix, expected_ext in directories:
        if not directory.exists() or not directory.is_dir():
            logger.debug("图库目录不存在或不是目录，已跳过: %s", directory)
            continue
        try:
            entries = sorted(directory.glob("*"), key=lambda p: p.name)
        except OSError as exc:  # pragma: no cover - 权限等极端情况
            logger.warning("扫描图库目录失败 %s: %s", directory, exc)
            continue

        for image_path in entries:
            if not image_path.is_file():
                continue
            matched = _COMPOSITE_PATTERN.match(image_path.name)
            if matched is None:
                logger.debug("忽略无法识别的综合图文件名: %s", image_path.name)
                continue
            date_str, event, ext = matched.group(1), matched.group(2).lower(), matched.group(3).lower()
            if ext != expected_ext:  # 目录与扩展名不一致，保护性跳过
                continue
            key = (date_str, event)
            if key in chosen:  # WebP 已存在，忽略 PNG 兜底
                continue
            chosen[key] = (image_path, url_prefix)

    events: list[dict[str, Any]] = []
    for (date_str, event), (image_path, url_prefix) in sorted(chosen.items()):
        try:
            target_date = date.fromisoformat(date_str)
            event_type: Literal["sunrise", "sunset"] = event  # type: ignore[assignment]
            events.append(_build_event(target_date, event_type, image_path, url_prefix, current))
        except (ValueError, OSError) as exc:
            # 非法日历日期（如 2026-13-45）或文件在扫描后消失：跳过，不影响其他事件
            logger.warning("跳过无法解析的综合图 %s: %s", image_path.name, exc)
            continue

    events.sort(key=_event_sort_key)
    return events


# --- 分类与 Hero ---


def _partition_events(
    events: list[dict[str, Any]], now: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """把事件分成 (live, upcoming, past) 三组，并各自按契约要求排序。"""
    live: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    past: list[dict[str, Any]] = []
    for event in events:
        status = _event_status(event, now)
        if status == "live":
            live.append(event)
        elif status == "upcoming":
            upcoming.append(event)
        else:
            past.append(event)
    live.sort(key=_event_start_key)
    upcoming.sort(key=_event_start_key)
    past.sort(key=_event_end_key, reverse=True)
    return live, upcoming, past


def select_hero(
    events: list[dict[str, Any]], now: datetime | None = None
) -> tuple[dict[str, Any] | None, str, str | None]:
    """
    按契约第 3 节选择首页 Hero。

    返回 (hero, hero_kind, hero_notice)：
    1. 有 live → start 最早者，hero_kind="live"；
    2. 否则有 upcoming → start 最早者，hero_kind="upcoming"；
    3. 否则取 past 中 end 最晚者，hero_kind="latest"，并给出过期提示；
    4. 一张图都没有 → (None, "empty", 提示文案)。
    """
    current = _resolve_now(now)
    live, upcoming, past = _partition_events(events, current)

    if live:
        return live[0], "live", None
    if upcoming:
        return upcoming[0], "upcoming", None
    if past:
        hero = past[0]  # past 已按 end 降序
        notice = (
            f"当前暂无未结束的预报，以下是最近一次存档"
            f"（{hero['date_label_full']} {hero['event_label']}），"
            f"数据生成于 {hero['generated_at']}（{hero['generated_ago']}），仅供参考。"
        )
        return hero, "latest", notice
    return None, "empty", "暂无任何存档图，可点击「更新预报」触发一次完整任务。"


# --- 页面上下文 ---


def build_common_context(events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """契约第 5.1 节：所有页面共用的上下文字段。"""
    current = _resolve_now(now)
    total_count = len(events)
    past_count = sum(1 for event in events if _event_status(event, current) == "past")
    upcoming_count = total_count - past_count

    latest_event: dict[str, Any] | None = None
    if events:
        latest_event = max(events, key=lambda event: event["generated_iso"])

    last_updated_iso = latest_event["generated_iso"] if latest_event else None
    last_updated_text = latest_event["generated_at"] if latest_event else None

    return {
        "now_iso": current.replace(microsecond=0).isoformat(),
        "now_text": (
            f"{current.year}年{current.month}月{current.day}日 "
            f"{current.hour:02d}:{current.minute:02d}"
        ),
        "last_updated_iso": last_updated_iso,
        "last_updated_text": last_updated_text,
        "data_age_text": _age_text_from_iso(last_updated_iso, current),
        "has_any_maps": total_count > 0,
        "total_count": total_count,
        "upcoming_count": upcoming_count,
        "past_count": past_count,
    }


def build_home_context(events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """契约第 5.2 节：首页上下文（hero / next_events / recent_past）。"""
    current = _resolve_now(now)
    hero, hero_kind, hero_notice = select_hero(events, current)
    hero_key = hero["key"] if hero else None

    live, upcoming, past = _partition_events(events, current)
    unfinished = sorted(live + upcoming, key=_event_start_key)
    next_events = [event for event in unfinished if event["key"] != hero_key][:6]

    # 近日回看：排除已作为 Hero 展示的那条，避免同图重复出现
    recent_past = [event for event in past if event["key"] != hero_key][:4]

    return {
        "hero": hero,
        "hero_kind": hero_kind,
        "hero_notice": hero_notice,
        "next_events": next_events,
        "recent_past": recent_past,
    }


def build_future_context(events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """契约第 5.3 节：未来页上下文（按天分组，仅含未结束事件）。"""
    current = _resolve_now(now)
    unfinished = [event for event in events if _is_unfinished(event, current)]
    unfinished.sort(key=_event_sort_key)

    days: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for event in unfinished:
        day = index.get(event["date"])
        if day is None:
            target_date = date.fromisoformat(event["date"])
            day = {
                "date": event["date"],
                "date_label": date_label(target_date),
                "weekday": weekday_label(target_date),
                "day_label": _relative_day_label(target_date, current.date()),
                "is_today": target_date == current.date(),
                "events": [],
            }
            index[event["date"]] = day
            days.append(day)
        day["events"].append(event)

    notice = None
    if not unfinished:
        notice = (
            "当前暂无未来预报存档，可点击「更新预报」触发最新任务，"
            "或前往历史存档查看已有结果。"
        )

    return {
        "days": days,
        "future_count": len(unfinished),
        "hero_notice": notice,
    }


# --- 筛选（历史页与 JSON API 共用） ---


def _normalize_scope(scope: str | None, default: str = "all") -> str:
    """把非法的 scope 规整为默认值，不抛 4xx。"""
    if scope in SCOPES:
        return scope  # type: ignore[return-value]
    return default


def _normalize_event_filter(event: str | None) -> str:
    """把非法的 event 过滤值规整为 all。"""
    if event in EVENT_FILTERS:
        return event  # type: ignore[return-value]
    return "all"


def _normalize_sort(sort: str | None) -> str:
    """排序方向：asc / desc，默认 desc。"""
    return "asc" if sort == "asc" else "desc"


def _parse_date_input(raw: str | None, label: str, errors: list[str]) -> date | None:
    """
    解析 YYYY-MM-DD。空值返回 None 且不报错；非法值记入 errors 并返回 None。
    """
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append(f"{label}格式无效：{text!r}（应为 YYYY-MM-DD），已忽略。")
        return None


def _matches_scope(event: dict[str, Any], scope: str, now: datetime) -> bool:
    """scope 过滤：past=已结束；future=未结束；all=全部。"""
    if scope == "all":
        return True
    is_past = _event_status(event, now) == "past"
    return is_past if scope == "past" else not is_past


def _apply_selection(
    events: list[dict[str, Any]],
    *,
    scope: str,
    event_filter: str,
    date_from: date | None,
    date_to: date | None,
    target_date: date | None,
    now: datetime,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    应用 scope / event / 日期筛选，返回 (按日期升序的事件列表, 日期近似匹配提示)。

    日期优先级：date > from/to。date 精确命中时无提示；无存档时回退到
    当前结果集中最接近的一天并给出提示。
    """
    base = [event for event in events if event_filter == "all" or event["event"] == event_filter]
    base = [event for event in base if _matches_scope(event, scope, now)]

    match_note: str | None = None

    if target_date is not None:
        target_text = target_date.isoformat()
        matched = [event for event in base if event["date"] == target_text]
        if matched:
            selected = matched
        elif base:
            # 回退到最接近的一天（按日期差的绝对值，平局取较早日期）
            available = sorted({event["date"] for event in base})
            nearest = min(
                available,
                key=lambda value: (abs((date.fromisoformat(value) - target_date).days), value),
            )
            selected = [event for event in base if event["date"] == nearest]
            match_note = f"{target_text} 无存档，已为你展示最接近的 {nearest}。"
        else:
            selected = []
    else:
        selected = base
        if date_from is not None:
            from_text = date_from.isoformat()
            selected = [event for event in selected if event["date"] >= from_text]
        if date_to is not None:
            to_text = date_to.isoformat()
            selected = [event for event in selected if event["date"] <= to_text]

    selected.sort(key=_event_sort_key)
    return selected, match_note


def filter_events(
    events: list[dict[str, Any]],
    *,
    scope: str | None = "all",
    event: str | None = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    target_date: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    供 JSON API 使用的筛选入口，返回按日期升序的事件列表。

    非法 scope/event/日期不会抛错：枚举回退默认值，非法日期直接忽略。
    """
    current = _resolve_now(now)
    errors: list[str] = []
    parsed_from = _parse_date_input(date_from, "起始日期", errors)
    parsed_to = _parse_date_input(date_to, "结束日期", errors)
    parsed_target = _parse_date_input(target_date, "查询日期", errors)
    for message in errors:
        logger.debug("筛选参数被忽略: %s", message)

    selected, _ = _apply_selection(
        events,
        scope=_normalize_scope(scope, "all"),
        event_filter=_normalize_event_filter(event),
        date_from=parsed_from,
        date_to=parsed_to,
        target_date=parsed_target,
        now=current,
    )
    return selected


def build_history_context(
    events: list[dict[str, Any]],
    *,
    scope: str | None = None,
    event: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    target_date: str | None = None,
    sort: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """契约第 5.4/5.5 节：历史页上下文（筛选 + 月份分组）。"""
    current = _resolve_now(now)
    normalized_scope = _normalize_scope(scope, "past")  # 历史页默认只看已结束
    normalized_event = _normalize_event_filter(event)
    normalized_sort = _normalize_sort(sort)

    errors: list[str] = []
    parsed_from = _parse_date_input(date_from, "起始日期", errors)
    parsed_to = _parse_date_input(date_to, "结束日期", errors)
    parsed_target = _parse_date_input(target_date, "查询日期", errors)

    selected, match_note = _apply_selection(
        events,
        scope=normalized_scope,
        event_filter=normalized_event,
        date_from=parsed_from,
        date_to=parsed_to,
        target_date=parsed_target,
        now=current,
    )

    # 排序：desc 时整份列表反向（同一天内 sunset 在前）
    if normalized_sort == "desc":
        selected = list(reversed(selected))

    # 按月分组（保持当前排序方向）
    groups: dict[str, dict[str, Any]] = {}
    for item in selected:
        month_key = item["date"][:7]
        group = groups.get(month_key)
        if group is None:
            year, month = int(month_key[:4]), int(month_key[5:7])
            group = {"key": month_key, "label": f"{year}年{month}月", "count": 0, "events": []}
            groups[month_key] = group
        group["count"] += 1
        group["events"].append(item)

    # scope 计数基于全量存档，不受其他筛选影响
    past_total = sum(1 for item in events if _event_status(item, current) == "past")
    scope_counts = {
        "all": len(events),
        "past": past_total,
        "future": len(events) - past_total,
    }

    filters = {
        "scope": normalized_scope,
        "event": normalized_event,
        "date_from": parsed_from.isoformat() if parsed_from else "",
        "date_to": parsed_to.isoformat() if parsed_to else "",
        "date": parsed_target.isoformat() if parsed_target else "",
        "sort": normalized_sort,
    }

    return {
        "filters": filters,
        "history_total": len(selected),
        "month_groups": list(groups.values()),
        "match_note": match_note,
        "filters_error": "".join(errors) if errors else None,
        "scope_counts": scope_counts,
    }
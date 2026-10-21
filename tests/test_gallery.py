# tests/test_gallery.py
"""图库数据层（gallery.py）单元测试。

全部使用 tmp_path + monkeypatch 伪造 outputs 目录与 mtime，不依赖仓库内真实
outputs 数据；now 一律显式注入，避免测试结果随运行日期漂移。
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.chromasky_toolkit import config, gallery

TZ = ZoneInfo("Asia/Shanghai")
# 固定「现在」：2026-10-21 15:13（春秋季，日落窗口 18:00 – 21:00）
FIXED_NOW = datetime(2026, 10, 21, 15, 13, tzinfo=TZ)

# 契约第 4 节要求的事件字段（字段名不可更改）
CONTRACT_EVENT_FIELDS = {
    "key",
    "date",
    "date_label",
    "date_label_full",
    "weekday",
    "day_label",
    "event",
    "event_label",
    "window_text",
    "start_iso",
    "end_iso",
    "generated_at",
    "generated_iso",
    "generated_ago",
    "image_url",
    "image_name",
    "image_title",
    "status",
    "is_upcoming",
    "relative_days",
}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _write_map(
    directory: Path,
    date_str: str,
    event: str,
    *,
    ext: str = "webp",
    mtime: datetime | None = None,
    content: bytes = b"fake-image-bytes",
) -> Path:
    """在指定目录写一个假综合图文件，并可按需设置 mtime。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"glow_index_composite_{date_str}_{event}.{ext}"
    path.write_bytes(content)
    if mtime is not None:
        timestamp = mtime.timestamp()
        os.utime(path, (timestamp, timestamp))
    return path


@pytest.fixture
def outputs_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """把 config 的两个输出根目录指向 tmp_path，返回 (webp 综合图目录, png 综合图目录)。"""
    webp_root = tmp_path / "outputs" / "maps_webp"
    png_root = tmp_path / "outputs" / "maps"
    monkeypatch.setattr(config, "MAP_WEBP_OUTPUTS_DIR", webp_root)
    monkeypatch.setattr(config, "MAP_OUTPUTS_DIR", png_root)
    return webp_root / "composite", png_root / "composite"


def _scan(now: datetime = FIXED_NOW) -> list[dict]:
    return gallery.scan_event_maps(now=now)


def _keys(events: list[dict]) -> list[str]:
    return [event["key"] for event in events]


# ---------------------------------------------------------------------------
# config.event_times_for_date：按目标日期月份选季节
# ---------------------------------------------------------------------------


class TestEventTimesForDate:
    def test_winter_dates(self):
        assert config.event_times_for_date("2026-01-15", "sunrise") == ["06:00", "07:00", "08:00", "09:00"]
        assert config.event_times_for_date("2026-12-01", "sunset") == ["17:00", "18:00", "19:00", "20:00"]

    def test_summer_dates(self):
        assert config.event_times_for_date(date(2026, 7, 15), "sunrise") == ["04:00", "05:00", "06:00", "07:00"]
        assert config.event_times_for_date(date(2026, 7, 15), "sunset") == ["19:00", "20:00", "21:00", "22:00"]

    def test_equinox_dates(self):
        assert config.event_times_for_date(date(2026, 3, 15), "sunrise") == ["05:00", "06:00", "07:00", "08:00"]
        assert config.event_times_for_date(date(2026, 10, 21), "sunset") == ["18:00", "19:00", "20:00", "21:00"]

    def test_independent_of_current_month(self):
        """关键回归：历史/未来日期必须按自身月份选季节，不能用「当前季节」。"""
        assert config.event_times_for_date("2026-01-10", "sunset") == config._SUNSET_TIMES_WINTER
        assert config.event_times_for_date("2026-07-10", "sunset") == config._SUNSET_TIMES_SUMMER
        assert config.event_times_for_date("2026-03-10", "sunset") == config._SUNSET_TIMES_EQUINOX

    def test_returns_copy(self):
        times = config.event_times_for_date("2026-01-10", "sunset")
        times.append("23:00")
        assert config.event_times_for_date("2026-01-10", "sunset") == config._SUNSET_TIMES_WINTER

    def test_rejects_unknown_event(self):
        with pytest.raises(ValueError):
            config.event_times_for_date("2026-01-10", "noon")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# scan_event_maps：扫描、回退、事件对象字段
# ---------------------------------------------------------------------------


class TestScanEventMaps:
    def test_missing_directories_return_empty(self, outputs_dirs):
        assert gallery.scan_event_maps(now=FIXED_NOW) == []

    def test_contract_fields_and_values(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        mtime = datetime(2026, 5, 12, 16, 4, 13, tzinfo=TZ)
        _write_map(webp_dir, "2026-05-12", "sunset", mtime=mtime)

        events = _scan()
        assert len(events) == 1
        event = events[0]
        assert set(event) == CONTRACT_EVENT_FIELDS

        # 5 月按夏季窗口：日落 19:00 – 22:00
        assert event["key"] == "2026-05-12_sunset"
        assert event["date"] == "2026-05-12"
        assert event["date_label"] == "5月12日 周二"
        assert event["date_label_full"] == "2026年5月12日 周二"
        assert event["weekday"] == "周二"
        assert event["event"] == "sunset"
        assert event["event_label"] == "日落"
        assert event["window_text"] == "19:00 – 22:00"
        assert event["start_iso"] == "2026-05-12T19:00:00+08:00"
        assert event["end_iso"] == "2026-05-12T22:00:00+08:00"
        assert event["generated_at"] == "2026-05-12 16:04"
        assert event["generated_iso"] == "2026-05-12T16:04:13+08:00"
        assert event["generated_ago"] == "5 个月前"
        assert event["image_url"] == "/static/maps_webp/composite/glow_index_composite_2026-05-12_sunset.webp"
        assert event["image_name"] == "glow_index_composite_2026-05-12_sunset.webp"
        assert event["image_title"] == "2026年5月12日 日落 · 19:00 – 22:00"
        assert event["status"] == "past"
        assert event["is_upcoming"] is False
        assert event["relative_days"] == (date(2026, 5, 12) - FIXED_NOW.date()).days

    def test_webp_preferred_over_png(self, outputs_dirs):
        webp_dir, png_dir = outputs_dirs
        png_mtime = datetime(2026, 5, 1, 10, 0, tzinfo=TZ)
        webp_mtime = datetime(2026, 5, 2, 11, 30, tzinfo=TZ)
        _write_map(png_dir, "2026-05-12", "sunset", ext="png", mtime=png_mtime)
        _write_map(webp_dir, "2026-05-12", "sunset", ext="webp", mtime=webp_mtime)

        events = _scan()
        assert len(events) == 1  # 同一事件组只保留一条
        event = events[0]
        assert event["image_name"].endswith(".webp")
        assert event["image_url"].startswith("/static/maps_webp/composite/")
        assert event["generated_at"] == "2026-05-02 11:30"  # mtime 取实际使用的 WebP

    def test_png_fallback_when_webp_missing(self, outputs_dirs):
        _, png_dir = outputs_dirs
        _write_map(png_dir, "2026-05-12", "sunrise", ext="png")

        events = _scan()
        assert len(events) == 1
        assert events[0]["image_name"] == "glow_index_composite_2026-05-12_sunrise.png"
        assert events[0]["image_url"] == "/static/maps/composite/glow_index_composite_2026-05-12_sunrise.png"

    def test_ignores_unknown_and_invalid_files(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        webp_dir.mkdir(parents=True)
        (webp_dir / "random.webp").write_bytes(b"x")
        (webp_dir / "glow_index_composite_2026-05-12_sunset.png").write_bytes(b"x")  # 扩展名与目录不符
        (webp_dir / "glow_index_composite_2026-13-45_sunset.webp").write_bytes(b"x")  # 非法日历日期
        _write_map(webp_dir, "2026-05-12", "sunset")

        assert _keys(_scan()) == ["2026-05-12_sunset"]

    def test_sorted_by_date_and_sunrise_first(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-05-13", "sunset")
        _write_map(webp_dir, "2026-05-12", "sunset")
        _write_map(webp_dir, "2026-05-12", "sunrise")

        assert _keys(_scan()) == [
            "2026-05-12_sunrise",
            "2026-05-12_sunset",
            "2026-05-13_sunset",
        ]

    def test_uses_target_month_season_for_window(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-01-15", "sunset")

        event = _scan()[0]
        assert event["window_text"] == "17:00 – 20:00"
        assert event["start_iso"] == "2026-01-15T17:00:00+08:00"
        assert event["end_iso"] == "2026-01-15T20:00:00+08:00"

    @pytest.mark.parametrize(
        ("now", "expected_status"),
        [
            (datetime(2026, 10, 21, 17, 59, tzinfo=TZ), "upcoming"),
            (datetime(2026, 10, 21, 18, 0, tzinfo=TZ), "live"),
            (datetime(2026, 10, 21, 21, 0, tzinfo=TZ), "live"),
            (datetime(2026, 10, 21, 21, 1, tzinfo=TZ), "past"),
        ],
    )
    def test_status_boundaries(self, outputs_dirs, now, expected_status):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-10-21", "sunset")

        event = gallery.scan_event_maps(now=now)[0]
        assert event["status"] == expected_status
        assert event["is_upcoming"] is (expected_status != "past")

    def test_relative_day_labels(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        for date_str in ("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-19"):
            _write_map(webp_dir, date_str, "sunset")

        by_date = {event["date"]: event["day_label"] for event in _scan()}
        assert by_date["2026-10-21"] == "今天"
        assert by_date["2026-10-22"] == "明天"
        assert by_date["2026-10-23"] == "后天"
        assert by_date["2026-10-20"] == "昨天"
        assert by_date["2026-10-19"] == "前天"


# ---------------------------------------------------------------------------
# Hero 选择
# ---------------------------------------------------------------------------


class TestHeroSelection:
    def test_live_preferred(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-10-21", "sunrise")
        _write_map(webp_dir, "2026-10-21", "sunset")
        _write_map(webp_dir, "2026-10-22", "sunset")

        now = datetime(2026, 10, 21, 19, 30, tzinfo=TZ)
        events = gallery.scan_event_maps(now=now)
        home = gallery.build_home_context(events, now=now)

        assert home["hero_kind"] == "live"
        assert home["hero"]["key"] == "2026-10-21_sunset"
        assert home["hero_notice"] is None
        assert _keys(home["next_events"]) == ["2026-10-22_sunset"]
        assert _keys(home["recent_past"]) == ["2026-10-21_sunrise"]

    def test_upcoming_when_no_live(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-10-21", "sunrise")  # 05:00–08:00，已结束
        _write_map(webp_dir, "2026-10-21", "sunset")  # 18:00–21:00，未来
        _write_map(webp_dir, "2026-10-22", "sunrise")

        home = gallery.build_home_context(_scan(), now=FIXED_NOW)
        assert home["hero_kind"] == "upcoming"
        assert home["hero"]["key"] == "2026-10-21_sunset"
        assert home["hero_notice"] is None
        assert _keys(home["next_events"]) == ["2026-10-22_sunrise"]

    def test_latest_fallback_when_no_future(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        mtime = datetime(2026, 5, 12, 16, 4, tzinfo=TZ)
        _write_map(webp_dir, "2026-05-11", "sunset", mtime=mtime)
        _write_map(webp_dir, "2026-05-12", "sunrise", mtime=mtime)
        _write_map(webp_dir, "2026-05-12", "sunset", mtime=mtime)

        home = gallery.build_home_context(_scan(), now=FIXED_NOW)
        assert home["hero_kind"] == "latest"
        # 5/12 日落窗口结束最晚（夏季 22:00），因此是 Hero
        assert home["hero"]["key"] == "2026-05-12_sunset"
        assert home["hero_notice"]
        assert "暂无未结束" in home["hero_notice"]
        assert home["next_events"] == []
        # recent_past 不再重复 Hero，且按结束时间降序
        assert _keys(home["recent_past"]) == ["2026-05-12_sunrise", "2026-05-11_sunset"]

    def test_empty_archive(self, outputs_dirs):
        hero, kind, notice = gallery.select_hero([], now=FIXED_NOW)
        assert hero is None
        assert kind == "empty"
        assert notice

        common = gallery.build_common_context([], now=FIXED_NOW)
        assert common["has_any_maps"] is False
        assert common["total_count"] == 0
        assert common["upcoming_count"] == 0
        assert common["past_count"] == 0
        assert common["last_updated_iso"] is None
        assert common["data_age_text"] is None

    def test_next_events_capped_and_past_capped(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        # 造 5 个已结束事件 + 8 个未来事件
        for day in range(10, 15):
            _write_map(webp_dir, f"2026-10-{day:02d}", "sunset")
        for day in range(22, 30):
            _write_map(webp_dir, f"2026-10-{day:02d}", "sunset")

        home = gallery.build_home_context(_scan(), now=FIXED_NOW)
        assert home["hero_kind"] == "upcoming"
        assert len(home["next_events"]) == 6
        assert len(home["recent_past"]) == 4
        # next_events 升序，recent_past 降序
        assert _keys(home["next_events"]) == sorted(_keys(home["next_events"]))
        assert _keys(home["recent_past"]) == sorted(_keys(home["recent_past"]), reverse=True)


# ---------------------------------------------------------------------------
# 未来页分组
# ---------------------------------------------------------------------------


class TestFutureContext:
    def test_no_future(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-05-12", "sunset")

        future = gallery.build_future_context(_scan(), now=FIXED_NOW)
        assert future["days"] == []
        assert future["future_count"] == 0
        assert future["hero_notice"]

    def test_groups_by_day(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        _write_map(webp_dir, "2026-10-21", "sunset")
        _write_map(webp_dir, "2026-10-21", "sunrise")  # 已结束，应被排除
        _write_map(webp_dir, "2026-10-22", "sunrise")
        _write_map(webp_dir, "2026-10-22", "sunset")
        _write_map(webp_dir, "2026-10-23", "sunset")

        future = gallery.build_future_context(_scan(), now=FIXED_NOW)
        assert future["future_count"] == 4
        assert future["hero_notice"] is None
        assert [day["date"] for day in future["days"]] == ["2026-10-21", "2026-10-22", "2026-10-23"]

        today = future["days"][0]
        assert today["is_today"] is True
        assert today["day_label"] == "今天"
        assert today["weekday"] == "周三"
        assert today["date_label"] == "10月21日 周三"
        assert [event["event"] for event in today["events"]] == ["sunset"]

        tomorrow = future["days"][1]
        assert tomorrow["is_today"] is False
        assert tomorrow["day_label"] == "明天"
        assert [event["event"] for event in tomorrow["events"]] == ["sunrise", "sunset"]


# ---------------------------------------------------------------------------
# 历史筛选
# ---------------------------------------------------------------------------


@pytest.fixture
def archive(outputs_dirs) -> list[dict]:
    """历史测试用存档：4 条已结束（5 月）+ 2 条未来（10 月）。"""
    webp_dir, _ = outputs_dirs
    mtime = datetime(2026, 5, 12, 16, 4, tzinfo=TZ)
    for date_str in ("2026-05-11", "2026-05-12"):
        _write_map(webp_dir, date_str, "sunrise", mtime=mtime)
        _write_map(webp_dir, date_str, "sunset", mtime=mtime)
    _write_map(webp_dir, "2026-10-21", "sunset")  # 今天 18:00–21:00，未结束
    _write_map(webp_dir, "2026-10-22", "sunrise")
    return _scan()


class TestHistoryContext:
    def test_default_scope_is_past(self, archive):
        history = gallery.build_history_context(archive, now=FIXED_NOW)
        assert history["filters"] == {
            "scope": "past",
            "event": "all",
            "date_from": "",
            "date_to": "",
            "date": "",
            "sort": "desc",
        }
        assert history["history_total"] == 4
        assert history["match_note"] is None
        assert history["filters_error"] is None
        assert history["scope_counts"] == {"all": 6, "past": 4, "future": 2}
        assert [(group["key"], group["count"]) for group in history["month_groups"]] == [("2026-05", 4)]
        # 默认降序：5/12 在 5/11 之前
        dates = [event["date"] for event in history["month_groups"][0]["events"]]
        assert dates == sorted(dates, reverse=True)

    def test_scope_all_and_month_order(self, archive):
        history = gallery.build_history_context(archive, scope="all", now=FIXED_NOW)
        assert history["history_total"] == 6
        assert [group["key"] for group in history["month_groups"]] == ["2026-10", "2026-05"]

        ascending = gallery.build_history_context(archive, scope="all", sort="asc", now=FIXED_NOW)
        assert [group["key"] for group in ascending["month_groups"]] == ["2026-05", "2026-10"]

    def test_event_filter(self, archive):
        history = gallery.build_history_context(archive, scope="all", event="sunset", now=FIXED_NOW)
        assert history["history_total"] == 3
        assert {event["event"] for event in history["month_groups"][0]["events"]} == {"sunset"}
        assert history["filters"]["event"] == "sunset"

    def test_scope_future(self, archive):
        history = gallery.build_history_context(archive, scope="future", now=FIXED_NOW)
        assert history["history_total"] == 2
        assert all(event["is_upcoming"] for event in history["month_groups"][0]["events"])

    def test_from_to_range(self, archive):
        history = gallery.build_history_context(
            archive, scope="all", date_from="2026-05-12", date_to="2026-05-12", now=FIXED_NOW
        )
        assert history["history_total"] == 2
        assert history["filters"]["date_from"] == "2026-05-12"
        assert history["filters"]["date_to"] == "2026-05-12"

    def test_exact_date(self, archive):
        history = gallery.build_history_context(archive, scope="all", target_date="2026-05-12", now=FIXED_NOW)
        assert history["history_total"] == 2
        assert history["filters"]["date"] == "2026-05-12"
        assert history["match_note"] is None

    def test_date_fallback_to_nearest(self, archive):
        history = gallery.build_history_context(archive, scope="all", target_date="2026-06-01", now=FIXED_NOW)
        assert history["history_total"] == 2
        assert history["match_note"]
        assert "2026-05-12" in history["match_note"]
        assert history["filters_error"] is None

    def test_date_precedence_over_range(self, archive):
        history = gallery.build_history_context(
            archive,
            scope="all",
            date_from="2026-10-01",
            date_to="2026-10-31",
            target_date="2026-05-12",
            now=FIXED_NOW,
        )
        assert history["history_total"] == 2
        assert history["filters"]["date"] == "2026-05-12"

    def test_invalid_date_is_reported_not_raised(self, archive):
        history = gallery.build_history_context(archive, scope="all", target_date="2026-13-40", now=FIXED_NOW)
        assert history["filters_error"]
        assert "2026-13-40" in history["filters_error"]
        assert history["filters"]["date"] == ""
        assert history["history_total"] == 6  # 非法日期被忽略

    def test_invalid_from_to_ignored(self, archive):
        history = gallery.build_history_context(
            archive, scope="all", date_from="not-a-date", date_to="2026/05/12", now=FIXED_NOW
        )
        assert history["filters_error"]
        assert history["filters"]["date_from"] == ""
        assert history["filters"]["date_to"] == ""
        assert history["history_total"] == 6

    def test_invalid_scope_event_sort_fall_back(self, archive):
        history = gallery.build_history_context(
            archive, scope="whatever", event="clouds", sort="random", now=FIXED_NOW
        )
        assert history["filters"]["scope"] == "past"
        assert history["filters"]["event"] == "all"
        assert history["filters"]["sort"] == "desc"
        assert history["history_total"] == 4

    def test_no_matches(self, archive):
        history = gallery.build_history_context(
            archive, scope="past", date_from="2025-01-01", date_to="2025-12-31", now=FIXED_NOW
        )
        assert history["history_total"] == 0
        assert history["month_groups"] == []


# ---------------------------------------------------------------------------
# JSON API 复用的 filter_events
# ---------------------------------------------------------------------------


class TestFilterEvents:
    def test_scope_event_and_ascending_order(self, archive):
        selected = gallery.filter_events(archive, scope="all", event="sunset", now=FIXED_NOW)
        assert _keys(selected) == ["2026-05-11_sunset", "2026-05-12_sunset", "2026-10-21_sunset"]

    def test_invalid_date_ignored(self, archive):
        selected = gallery.filter_events(archive, scope="all", target_date="oops", now=FIXED_NOW)
        assert len(selected) == 6

    def test_date_fallback(self, archive):
        selected = gallery.filter_events(archive, scope="all", target_date="2026-10-20", now=FIXED_NOW)
        assert {event["date"] for event in selected} == {"2026-10-21"}


# ---------------------------------------------------------------------------
# 人类可读时间
# ---------------------------------------------------------------------------


class TestHumanizeAge:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(seconds=5), "刚刚"),
            (timedelta(seconds=-30), "刚刚"),
            (timedelta(minutes=5), "5 分钟前"),
            (timedelta(minutes=59), "59 分钟前"),
            (timedelta(hours=3), "3 小时前"),
            (timedelta(hours=23), "23 小时前"),
            (timedelta(days=2), "2 天前"),
            (timedelta(days=29), "29 天前"),
            (timedelta(days=45), "1 个月前"),
            (timedelta(days=162), "5 个月前"),
        ],
    )
    def test_humanize(self, delta, expected):
        assert gallery.humanize_age(delta) == expected

    def test_common_context_uses_latest_mtime(self, outputs_dirs):
        webp_dir, _ = outputs_dirs
        older = datetime(2026, 3, 1, 9, 0, tzinfo=TZ)
        newer = datetime(2026, 5, 12, 16, 4, tzinfo=TZ)
        _write_map(webp_dir, "2026-03-01", "sunset", mtime=older)
        _write_map(webp_dir, "2026-05-12", "sunset", mtime=newer)

        common = gallery.build_common_context(_scan(), now=FIXED_NOW)
        assert common["now_iso"] == "2026-10-21T15:13:00+08:00"
        assert common["now_text"] == "2026年10月21日 15:13"
        assert common["last_updated_iso"] == "2026-05-12T16:04:00+08:00"
        assert common["last_updated_text"] == "2026-05-12 16:04"
        assert common["data_age_text"] == "5 个月前"
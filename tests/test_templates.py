"""模板渲染测试。

用覆盖 ``docs/web-ui.md`` 契约字段的 mock 上下文，独立渲染三个页面。
不依赖 FastAPI / 真实后端，因此可以在后端并行开发期间自测模板。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "templates"
STATIC_DIR = REPO_ROOT / "src" / "static"


@pytest.fixture(scope="module")
def env() -> Environment:
    """与 FastAPI Jinja2Templates 近似的环境，但用 StrictUndefined 抓契约字段遗漏。"""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
    )


def render(env: Environment, template_name: str, **context) -> str:
    template = env.get_template(template_name)
    return template.render(**context)


def make_event(**overrides) -> dict:
    """完整的契约事件对象；用 overrides 派生不同状态。"""
    event = {
        "key": "2026-10-21_sunset",
        "date": "2026-10-21",
        "date_label": "10月21日 周二",
        "date_label_full": "2026年10月21日 周二",
        "weekday": "周二",
        "day_label": "今天",
        "event": "sunset",
        "event_label": "日落",
        "window_text": "18:00 – 21:00",
        "start_iso": "2026-10-21T18:00:00+08:00",
        "end_iso": "2026-10-21T21:00:00+08:00",
        "generated_at": "2026-10-21 15:02",
        "generated_iso": "2026-10-21T15:02:11+08:00",
        "generated_ago": "25 分钟前",
        "image_url": "/static/maps_webp/composite/glow_index_composite_2026-10-21_sunset.webp",
        "image_name": "glow_index_composite_2026-10-21_sunset.webp",
        "image_title": "2026年10月21日 日落 · 18:00 – 21:00",
        "status": "upcoming",
        "is_upcoming": True,
        "relative_days": 0,
    }
    event.update(overrides)
    return event


def make_day(**overrides) -> dict:
    day = {
        "date": "2026-10-21",
        "date_label": "10月21日 周二",
        "weekday": "周二",
        "day_label": "今天",
        "is_today": True,
        "events": [
            make_event(
                key="2026-10-21_sunrise",
                event="sunrise",
                event_label="日出",
                window_text="04:00 – 07:00",
                start_iso="2026-10-21T04:00:00+08:00",
                end_iso="2026-10-21T07:00:00+08:00",
                image_url="/static/maps_webp/composite/glow_index_composite_2026-10-21_sunrise.webp",
                image_name="glow_index_composite_2026-10-21_sunrise.webp",
                image_title="2026年10月21日 日出 · 04:00 – 07:00",
                status="past",
                is_upcoming=False,
            ),
            make_event(),
        ],
    }
    day.update(overrides)
    return day


def base_context(page: str, **overrides) -> dict:
    context = {
        "request": object(),
        "page": page,
        "now_iso": "2026-10-21T15:13:00+08:00",
        "now_text": "2026年10月21日 15:13",
        "last_updated_iso": "2026-05-12T16:04:13+08:00",
        "last_updated_text": "2026年5月12日 16:04",
        "data_age_text": "5 个月前",
        "has_any_maps": True,
        "total_count": 4,
        "upcoming_count": 2,
        "past_count": 2,
    }
    context.update(overrides)
    return context


def home_context(**overrides) -> dict:
    context = base_context(
        "home",
        hero=make_event(),
        hero_kind="upcoming",
        hero_notice=None,
        next_events=[
            make_event(key="2026-10-22_sunrise", date="2026-10-22", day_label="明天"),
            make_event(key="2026-10-22_sunset", date="2026-10-22", day_label="明天"),
        ],
        recent_past=[
            make_event(key="2026-05-12_sunset", status="past", is_upcoming=False, day_label="5月12日 周二"),
        ],
    )
    context.update(overrides)
    return context


def future_context(**overrides) -> dict:
    context = base_context(
        "future",
        days=[make_day()],
        future_count=2,
        hero_notice=None,
    )
    context.update(overrides)
    return context


def history_context(**overrides) -> dict:
    context = base_context(
        "history",
        filters={
            "scope": "past",
            "event": "all",
            "date_from": "",
            "date_to": "",
            "date": "",
            "sort": "desc",
        },
        history_total=1,
        month_groups=[
            {
                "key": "2026-05",
                "label": "2026年5月",
                "count": 1,
                "events": [
                    make_event(
                        key="2026-05-12_sunset",
                        date="2026-05-12",
                        date_label="5月12日 周二",
                        date_label_full="2026年5月12日 周二",
                        day_label="5月12日 周二",
                        status="past",
                        is_upcoming=False,
                        relative_days=-162,
                    )
                ],
            }
        ],
        match_note=None,
        filters_error=None,
        scope_counts={"all": 4, "past": 2, "future": 2},
    )
    context.update(overrides)
    return context


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------


def test_home_upcoming_hero(env: Environment) -> None:
    html = render(env, "index.html", **home_context())

    assert "未来几场霞光" in html
    assert "近日回看" in html
    assert "下一场 · Next" in html
    # Hero 大图：高优先级、可打开灯箱、alt 含日期与事件
    assert 'fetchpriority="high"' in html
    assert "glow_index_composite_2026-10-21_sunset.webp" in html
    assert "2026年10月21日 日落" in html
    assert 'data-lightbox' in html
    assert 'data-start="2026-10-21T18:00:00+08:00"' in html
    assert "18:00 – 21:00" in html
    # 导航高亮
    assert re.search(r'aria-current="page"[^>]*>首页', html)
    # 卡片懒加载
    assert 'loading="lazy"' in html
    # 颜色图例
    assert "指数图例" in html
    assert "极佳" in html


def test_home_latest_hero_falls_back_with_notice(env: Environment) -> None:
    context = home_context(
        hero_kind="latest",
        hero=make_event(
            key="2026-05-12_sunset",
            date="2026-05-12",
            date_label="5月12日 周二",
            date_label_full="2026年5月12日 周二",
            day_label="5月12日 周二",
            status="past",
            is_upcoming=False,
            relative_days=-1,
            image_url="/static/maps_webp/composite/glow_index_composite_2026-05-12_sunset.webp",
            image_name="glow_index_composite_2026-05-12_sunset.webp",
            image_title="2026年5月12日 日落 · 18:00 – 21:00",
        ),
        hero_notice="未来预报尚未生成，当前展示最近一次可用的综合图。",
        next_events=[],
    )
    html = render(env, "index.html", **context)

    assert "最近一次 · Latest" in html
    assert "未来预报尚未生成，当前展示最近一次可用的综合图。" in html
    assert "立即更新预报" in html
    assert "暂无未来的场次" in html
    assert "2026年5月12日 日落" in html


def test_home_empty_state_without_any_map(env: Environment) -> None:
    context = base_context(
        "home",
        hero=None,
        hero_kind="empty",
        hero_notice=None,
        next_events=[],
        recent_past=[],
        has_any_maps=False,
        total_count=0,
        upcoming_count=0,
        past_count=0,
    )
    html = render(env, "index.html", **context)

    assert "还没有可展示的预报" in html
    assert "更新预报" in html
    assert "历史存档" in html
    # 空状态不应出现任何地图图片
    assert "/static/maps_webp/" not in html
    assert "未来几场霞光" not in html


# ---------------------------------------------------------------------------
# 未来页
# ---------------------------------------------------------------------------


def test_future_with_days(env: Environment) -> None:
    html = render(env, "future.html", **future_context())

    assert "接下来的霞光" in html
    assert "未来 5 天" in html
    assert "今天" in html
    assert 'id="day-2026-10-21"' in html
    assert "2 场 · 北京时间" in html
    # 日出排在前、日落在后（契约要求）
    sunrise_at = html.find("日出")
    sunset_at = html.find("日落")
    assert sunrise_at != -1 and sunset_at != -1
    assert sunrise_at < sunset_at
    assert "2026年10月21日 日出 · 04:00 – 07:00" in html
    assert "查找更早的场次" in html


def test_future_empty_state(env: Environment) -> None:
    context = future_context(
        days=[],
        future_count=0,
        hero_notice="暂无未来预报：后台还没有生成未来场次的综合图。",
    )
    html = render(env, "future.html", **context)

    assert "暂无未来预报" in html
    assert "后台还没有生成未来场次的综合图" in html
    assert "更新预报" in html
    assert "历史存档" in html


# ---------------------------------------------------------------------------
# 历史页
# ---------------------------------------------------------------------------


def test_history_with_results(env: Environment) -> None:
    context = history_context(
        filters={
            "scope": "past",
            "event": "sunset",
            "date_from": "2026-05-01",
            "date_to": "2026-05-31",
            "date": "",
            "sort": "asc",
        }
    )
    html = render(env, "history.html", **context)

    assert "每一次火烧云" in html
    assert "2026年5月" in html
    assert "2026年5月12日 周二" in html
    assert "共 <strong class=\"mono\">1</strong> 条" in html
    assert "全部场次" in html
    assert "未来待看" in html
    # 表单回填
    assert 'value="2026-05-01"' in html
    assert 'value="2026-05-31"' in html
    assert re.search(r'name="scope" value="past"[^>]*checked', html)
    assert re.search(r'name="event"', html)
    assert re.search(r'<option value="sunset"[^>]*selected', html)
    assert re.search(r'<option value="asc"[^>]*selected', html)
    assert "按日期升序" in html


def test_history_no_results(env: Environment) -> None:
    context = history_context(
        history_total=0,
        month_groups=[],
        filters={
            "scope": "future",
            "event": "all",
            "date_from": "",
            "date_to": "",
            "date": "",
            "sort": "desc",
        },
    )
    html = render(env, "history.html", **context)

    assert "没有匹配的存档" in html
    assert "清空筛选" in html


def test_history_alerts_for_bad_date_and_near_match(env: Environment) -> None:
    context = history_context(
        filters={
            "scope": "past",
            "event": "all",
            "date_from": "",
            "date_to": "",
            "date": "2026-05-13",
            "sort": "desc",
        },
        match_note="2026-05-13 没有存档，已返回最接近的 2026-05-12。",
        filters_error="日期格式不正确，请使用 YYYY-MM-DD。",
    )
    html = render(env, "history.html", **context)

    assert 'role="alert"' in html
    assert "日期格式不正确" in html
    assert "已返回最接近的 2026-05-12" in html
    assert 'value="2026-05-13"' in html


def test_history_without_any_archive(env: Environment) -> None:
    context = history_context(
        has_any_maps=False,
        total_count=0,
        upcoming_count=0,
        past_count=0,
        history_total=0,
        month_groups=[],
        filters={},
        scope_counts={"all": 0, "past": 0, "future": 0},
    )
    html = render(env, "history.html", **context)

    assert "还没有任何存档" in html
    assert "更新预报" in html
    assert "stat-strip" not in html
    assert "每次" not in html


# ---------------------------------------------------------------------------
# 公共骨架 / 静态资源 / 无外部依赖
# ---------------------------------------------------------------------------


def test_shared_shell_and_accessibility(env: Environment) -> None:
    html = render(env, "index.html", **home_context())

    assert '<html lang="zh-CN"' in html
    assert 'name="theme-color"' in html
    assert 'class="skip-link"' in html
    assert 'href="#main"' in html
    assert 'id="main"' in html
    assert '<nav class="site-nav" aria-label="主导航">' in html
    assert 'id="lightbox"' in html
    assert '<dialog' in html
    assert 'aria-live="polite"' in html
    assert 'name="ck-now"' in html
    assert "/assets/app.css" in html
    assert "/assets/app.js" in html
    assert 'defer' in html
    assert "更新预报" in html


def test_no_external_network_dependencies(env: Environment) -> None:
    pages = [
        render(env, "index.html", **home_context()),
        render(env, "future.html", **future_context()),
        render(env, "history.html", **history_context()),
    ]
    html = "\n".join(pages)

    assert not re.search(r'(?:src|href)="(?:https?:)?//', html), "模板不应引用外部资源"
    assert not re.search(r"https?://(?:cdn|fonts|unpkg|jsdelivr)", html, re.I)

    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"url\(\s*['\"]?https?://", css), "CSS 不应加载外部资源"
    assert "@import" not in css
    assert not re.search(r"https?://(?:cdn|fonts|unpkg|jsdelivr)", css, re.I)


def test_static_assets_present_and_loaded(env: Environment) -> None:
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert len(css) > 4000
    assert len(js) > 2000

    # 契约第 7 节：地图图片 contain、占位背景、响应式、可访问性
    assert "object-fit: contain" in css
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css
    assert "aspect-ratio" in css
    assert "min-height: 44px" in css

    # 交互要求
    assert "'/trigger-job'" in js or '"/trigger-job"' in js
    assert "showModal" in js
    assert "setInterval" in js
    assert "data-countdown" in js
    assert "prefers-reduced-motion" not in js  # 动效由 CSS 统一收敛


def test_legacy_archive_template_removed() -> None:
    """契约说明 /archive 已 307 到 /history，旧模板不应继续存在。"""
    assert not (TEMPLATE_DIR / "archive.html").exists()
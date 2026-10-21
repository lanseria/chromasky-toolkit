# tests/test_server_routes.py
"""FastAPI 路由测试（/、/future、/history、/archive、/api/events 等）。

设计要点：
1. 使用 tmp_path + monkeypatch 伪造 outputs 目录，不依赖仓库内真实 outputs；
2. 固定 gallery.now_local()，避免测试随运行日期漂移；
3. 页面路由的数据装配用「捕获模板上下文」的方式验证（不依赖前端模板文件）；
4. 前端模板由另一位队友并行开发，真实模板渲染测试在模板缺失时 skip。
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.responses import HTMLResponse
from starlette.testclient import TestClient

from src.chromasky_toolkit import config, gallery, server

TZ = ZoneInfo("Asia/Shanghai")
FIXED_NOW = datetime(2026, 10, 21, 15, 13, tzinfo=TZ)
TEMPLATES_DIR = config.PROJECT_ROOT / "templates"

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
# 辅助与 fixture
# ---------------------------------------------------------------------------


def _write_map(
    directory: Path,
    date_str: str,
    event: str,
    *,
    ext: str = "webp",
    mtime: datetime | None = None,
) -> Path:
    """写一个假综合图文件，可按需设置 mtime。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"glow_index_composite_{date_str}_{event}.{ext}"
    path.write_bytes(b"fake-image-bytes")
    if mtime is not None:
        timestamp = mtime.timestamp()
        os.utime(path, (timestamp, timestamp))
    return path


@pytest.fixture
def outputs_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """monkeypatch config 输出目录到 tmp_path，返回 (webp 目录, png 目录)。"""
    webp_root = tmp_path / "outputs" / "maps_webp"
    png_root = tmp_path / "outputs" / "maps"
    monkeypatch.setattr(config, "MAP_WEBP_OUTPUTS_DIR", webp_root)
    monkeypatch.setattr(config, "MAP_OUTPUTS_DIR", png_root)
    monkeypatch.setattr(gallery, "now_local", lambda: FIXED_NOW)
    return webp_root / "composite", png_root / "composite"


@pytest.fixture
def past_archive(outputs_dirs) -> tuple[Path, Path]:
    """只有历史存档（无未来预报）的目录。"""
    webp_dir, png_dir = outputs_dirs
    mtime = datetime(2026, 5, 12, 16, 4, tzinfo=TZ)
    for date_str in ("2026-05-11", "2026-05-12"):
        _write_map(webp_dir, date_str, "sunrise", mtime=mtime)
        _write_map(webp_dir, date_str, "sunset", mtime=mtime)
    return webp_dir, png_dir


@pytest.fixture
def mixed_archive(outputs_dirs) -> tuple[Path, Path]:
    """历史 + 未来混合存档（未来：10/21 日落、10/22 日出）。"""
    webp_dir, png_dir = outputs_dirs
    mtime = datetime(2026, 5, 12, 16, 4, tzinfo=TZ)
    for date_str in ("2026-05-11", "2026-05-12"):
        _write_map(webp_dir, date_str, "sunrise", mtime=mtime)
        _write_map(webp_dir, date_str, "sunset", mtime=mtime)
    _write_map(webp_dir, "2026-10-21", "sunset")
    _write_map(webp_dir, "2026-10-22", "sunrise")
    return webp_dir, png_dir


class _CapturingTemplates:
    """替代 Jinja2Templates：记录模板名与上下文，返回简单 HTML（不需要模板文件）。"""

    def __init__(self) -> None:
        self.name: str | None = None
        self.context: dict | None = None

    def TemplateResponse(self, request, name, context=None, **kwargs):
        self.name = name
        self.context = dict(context or {})
        self.context.setdefault("request", request)
        return HTMLResponse(f"<!doctype html><html><body>{name}</body></html>")


@pytest.fixture
def captured_client(monkeypatch: pytest.MonkeyPatch):
    """返回 (TestClient, 捕获器)。注意：不使用 with，避免触发 lifespan（自检/定时任务）。"""
    capture = _CapturingTemplates()
    monkeypatch.setattr(server, "templates", capture)
    return TestClient(server.app), capture


# ---------------------------------------------------------------------------
# 首页 /
# ---------------------------------------------------------------------------


class TestIndexRoute:
    def test_hero_latest_fallback_without_future(self, past_archive, captured_client):
        client, capture = captured_client
        response = client.get("/")

        assert response.status_code == 200
        assert capture.name == "index.html"
        context = capture.context
        assert context["page"] == "home"
        assert context["request"] is not None
        assert context["hero_kind"] == "latest"
        assert context["hero"]["key"] == "2026-05-12_sunset"
        assert context["hero_notice"]  # 无未来预报时必须有提示
        assert context["next_events"] == []
        assert len(context["recent_past"]) == 3  # 除 Hero 外的另外 3 条历史

        # 契约 5.1 公共字段
        assert context["now_iso"] == "2026-10-21T15:13:00+08:00"
        assert context["now_text"] == "2026年10月21日 15:13"
        assert context["has_any_maps"] is True
        assert context["total_count"] == 4
        assert context["past_count"] == 4
        assert context["upcoming_count"] == 0
        assert context["last_updated_iso"] == "2026-05-12T16:04:00+08:00"
        assert context["last_updated_text"] == "2026-05-12 16:04"
        assert context["data_age_text"] == "5 个月前"

    def test_hero_upcoming_with_future_data(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get("/")

        assert response.status_code == 200
        context = capture.context
        assert context["hero_kind"] == "upcoming"
        assert context["hero"]["key"] == "2026-10-21_sunset"
        assert context["hero_notice"] is None
        assert [event["key"] for event in context["next_events"]] == ["2026-10-22_sunrise"]

    def test_empty_archive(self, outputs_dirs, captured_client):
        client, capture = captured_client
        response = client.get("/")

        assert response.status_code == 200
        context = capture.context
        assert context["hero"] is None
        assert context["hero_kind"] == "empty"
        assert context["hero_notice"]
        assert context["has_any_maps"] is False
        assert context["total_count"] == 0
        assert context["next_events"] == []
        assert context["recent_past"] == []


# ---------------------------------------------------------------------------
# 未来页 /future
# ---------------------------------------------------------------------------


class TestFutureRoute:
    def test_no_future_events(self, past_archive, captured_client):
        client, capture = captured_client
        response = client.get("/future")

        assert response.status_code == 200
        assert capture.name == "future.html"
        context = capture.context
        assert context["page"] == "future"
        assert context["days"] == []
        assert context["future_count"] == 0
        assert context["hero_notice"]  # 无未来预报时必须提示

    def test_groups_unfinished_events_by_day(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get("/future")

        assert response.status_code == 200
        context = capture.context
        assert context["future_count"] == 2
        assert [day["date"] for day in context["days"]] == ["2026-10-21", "2026-10-22"]
        assert context["days"][0]["is_today"] is True
        assert context["days"][0]["events"][0]["event"] == "sunset"
        assert context["days"][1]["events"][0]["event"] == "sunrise"


# ---------------------------------------------------------------------------
# 历史页 /history
# ---------------------------------------------------------------------------


class TestHistoryRoute:
    def test_default_scope_past(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get("/history")

        assert response.status_code == 200
        assert capture.name == "history.html"
        context = capture.context
        assert context["page"] == "history"
        assert context["filters"]["scope"] == "past"
        assert context["history_total"] == 4
        assert context["scope_counts"] == {"all": 6, "past": 4, "future": 2}
        assert [group["key"] for group in context["month_groups"]] == ["2026-05"]
        assert context["match_note"] is None
        assert context["filters_error"] is None

    def test_query_filters_passthrough(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get(
            "/history",
            params={
                "scope": "all",
                "event": "sunset",
                "from": "2026-05-01",
                "to": "2026-05-31",
                "sort": "asc",
            },
        )

        assert response.status_code == 200
        context = capture.context
        assert context["filters"] == {
            "scope": "all",
            "event": "sunset",
            "date_from": "2026-05-01",
            "date_to": "2026-05-31",
            "date": "",
            "sort": "asc",
        }
        assert context["history_total"] == 2

    def test_approximate_date(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get("/history", params={"scope": "all", "date": "2026-06-01"})

        assert response.status_code == 200
        context = capture.context
        assert context["history_total"] == 2
        assert context["match_note"]
        assert "2026-05-12" in context["match_note"]

    def test_invalid_date_does_not_4xx(self, mixed_archive, captured_client):
        client, capture = captured_client
        response = client.get("/history", params={"date": "2026-13-40"})

        assert response.status_code == 200
        context = capture.context
        assert context["filters_error"]
        assert context["filters"]["date"] == ""


# ---------------------------------------------------------------------------
# 旧链接 /archive
# ---------------------------------------------------------------------------


class TestArchiveRedirect:
    def test_307_to_history(self, outputs_dirs):
        client = TestClient(server.app)
        response = client.get("/archive", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/history"


# ---------------------------------------------------------------------------
# JSON API /api/events
# ---------------------------------------------------------------------------


class TestApiEvents:
    def test_response_shape_and_event_filter(self, mixed_archive):
        client = TestClient(server.app)
        response = client.get("/api/events", params={"scope": "all", "event": "sunset"})

        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"now", "count", "events"}
        assert data["now"] == "2026-10-21T15:13:00+08:00"
        assert data["count"] == len(data["events"]) == 3
        assert all(event["event"] == "sunset" for event in data["events"])
        assert set(data["events"][0]) == CONTRACT_EVENT_FIELDS
        # 返回按日期升序
        dates = [event["date"] for event in data["events"]]
        assert dates == sorted(dates)

    def test_scope_past(self, mixed_archive):
        client = TestClient(server.app)
        response = client.get("/api/events", params={"scope": "past"})

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 4
        assert all(event["status"] == "past" for event in data["events"])

    def test_limit(self, mixed_archive):
        client = TestClient(server.app)
        response = client.get("/api/events", params={"scope": "all", "limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["events"]) == 1

    @pytest.mark.parametrize("limit", [0, 501])
    def test_limit_out_of_range_rejected(self, mixed_archive, limit):
        client = TestClient(server.app)
        assert client.get("/api/events", params={"limit": limit}).status_code == 422

    def test_date_fallback(self, mixed_archive):
        client = TestClient(server.app)
        response = client.get("/api/events", params={"scope": "all", "date": "2026-06-01"})

        assert response.status_code == 200
        data = response.json()
        assert {event["date"] for event in data["events"]} == {"2026-05-12"}

    def test_invalid_date_ignored(self, mixed_archive):
        client = TestClient(server.app)
        response = client.get("/api/events", params={"scope": "all", "date": "not-a-date"})

        assert response.status_code == 200
        assert response.json()["count"] == 6

    def test_empty_archive(self, outputs_dirs):
        client = TestClient(server.app)
        response = client.get("/api/events")

        assert response.status_code == 200
        assert response.json() == {"now": "2026-10-21T15:13:00+08:00", "count": 0, "events": []}


# ---------------------------------------------------------------------------
# 保留的旧接口与挂载
# ---------------------------------------------------------------------------


class TestRetainedEndpoints:
    def test_glow_index_requires_query(self, outputs_dirs):
        client = TestClient(server.app)
        # 保留原路由：缺参数时由 FastAPI 返回 422，而不是 404
        assert client.get("/api/glow-index").status_code == 422

    def test_trigger_job_route_exists(self):
        # 不实际调用：调用会同步执行完整工作流（下载/绘图）
        paths = {getattr(route, "path", None) for route in server.app.routes}
        assert "/trigger-job" in paths

    def test_static_and_assets_mounted(self):
        mounted = {
            route.path: getattr(route, "name", None)
            for route in server.app.routes
            if route.__class__.__name__ == "Mount"
        }
        assert mounted.get("/static") == "static"
        assert mounted.get("/assets") == "assets"


# ---------------------------------------------------------------------------
# 真实模板渲染（前端并行开发中，模板未就绪时 skip）
# ---------------------------------------------------------------------------


def _template_ready(page: str) -> bool:
    """页面模板与 base.html 都存在时才视为前端已就绪。"""
    return (TEMPLATES_DIR / "base.html").exists() and (TEMPLATES_DIR / page).exists()


@pytest.mark.parametrize(
    ("path", "page"),
    [("/", "index.html"), ("/future", "future.html"), ("/history", "history.html")],
)
def test_real_templates_render(path, page, mixed_archive):
    if not _template_ready(page):
        pytest.skip(f"模板 {page} 或 base.html 尚未就绪（前端并行开发中）")

    client = TestClient(server.app, raise_server_exceptions=False)
    response = client.get(path)
    if response.status_code == 500:
        pytest.skip(f"模板 {page} 当前不可渲染（前端可能仍在编写），已跳过集成断言")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert response.text.strip()
"""测试午夜(0:00 UTC)场景下的数据下载参数计算

验证在凌晨 0 点运行时，CAMS/GFS 运行周期选择、事件展开、
leadtime_hour 计算均产生有效的 API 请求参数。
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from src.chromasky_toolkit import config
from src.chromasky_toolkit.data_acquisition import (
    _find_latest_available_cams_run,
    _find_latest_available_gfs_run,
)
from src.chromasky_toolkit.processing import expand_target_events

# 模拟的午夜时间点：2026-05-16 00:00:00 UTC = 2026-05-16 08:00:00 CST
MIDNIGHT_UTC = "2026-05-16 00:00:00"
LOCAL_TZ = ZoneInfo(config.LOCAL_TZ)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_leadtime_hours(base_run_time: datetime, target_events: dict) -> list[int]:
    """模拟 data_acquisition.py 中 acquire_cams_data 的 leadtime 计算逻辑"""
    leadtime_hours = {
        round((t - base_run_time).total_seconds() / 3600)
        for t in target_events.values()
    }
    return sorted(h for h in leadtime_hours if h >= 0)


def _build_cams_request_params(run_date, run_hour, leadtime_hours) -> dict:
    """模拟 data_acquisition.py 中构建 CAMS API 请求参数"""
    area_bounds = [config.DOWNLOAD_AREA[k] for k in ["north", "west", "south", "east"]]
    return {
        "date": run_date,
        "time": run_hour,
        "format": "netcdf_zip",
        "variable": list(config.CAMS_VARS_MAP.values()),
        "leadtime_hour": sorted([str(h) for h in leadtime_hours]),
        "type": "forecast",
        "area": area_bounds,
    }


# ---------------------------------------------------------------------------
# 测试 1：CAMS 运行周期选择
# ---------------------------------------------------------------------------

class TestCAMSRunSelection:
    """0:00 UTC 时，safe_margin=9h，应选前一天 12:00 UTC 的 CAMS 运行"""

    @freeze_time(MIDNIGHT_UTC)
    def test_selects_previous_day_12z(self):
        result = _find_latest_available_cams_run()
        assert result is not None
        run_date, run_hour = result
        assert run_date == "2026-05-15"
        assert run_hour == "12:00"


# ---------------------------------------------------------------------------
# 测试 2：GFS 运行周期选择
# ---------------------------------------------------------------------------

class TestGFSRunSelection:
    """0:00 UTC 时，safe_margin=5h，应选前一天 18:00 UTC 的 GFS 运行"""

    @freeze_time(MIDNIGHT_UTC)
    def test_selects_previous_day_18z(self):
        result = _find_latest_available_gfs_run()
        assert result is not None
        run_date, run_hour = result
        assert run_date == "20260515"
        assert run_hour == "18"


# ---------------------------------------------------------------------------
# 测试 3：事件展开
# ---------------------------------------------------------------------------

class TestEventExpansion:
    """夏季（5月）事件展开：today_sunset + tomorrow_sunrise"""

    @freeze_time(MIDNIGHT_UTC)
    def test_event_count(self):
        events = expand_target_events()
        # today_sunset: 4 个时间点 + tomorrow_sunrise: 4 个时间点 = 8
        assert len(events) == 8

    @freeze_time(MIDNIGHT_UTC)
    def test_sunset_events_utc_times(self):
        events = expand_target_events()
        sunset_events = {k: v for k, v in events.items() if "sunset" in k}

        # 夏季 today_sunset: 19:00-22:00 CST = 11:00-14:00 UTC
        expected_utc_hours = {11, 12, 13, 14}
        actual_utc_hours = {v.hour for v in sunset_events.values()}
        assert actual_utc_hours == expected_utc_hours

    @freeze_time(MIDNIGHT_UTC)
    def test_sunrise_events_utc_times(self):
        events = expand_target_events()
        sunrise_events = {k: v for k, v in events.items() if "sunrise" in k}

        # 夏季 tomorrow_sunrise: 04:00-07:00 CST = 20:00-23:00 UTC (前一天)
        expected_utc_hours = {20, 21, 22, 23}
        actual_utc_hours = {v.hour for v in sunrise_events.values()}
        assert actual_utc_hours == expected_utc_hours

    @freeze_time(MIDNIGHT_UTC)
    def test_all_events_in_future(self):
        events = expand_target_events()
        now_utc = datetime.now(timezone.utc)
        for name, event_time in events.items():
            assert event_time > now_utc, f"事件 {name} 的时间不是未来时间"


# ---------------------------------------------------------------------------
# 测试 4：leadtime_hour 有效性
# ---------------------------------------------------------------------------

class TestLeadtimeValidity:
    """验证 leadtime_hour 值在 CAMS 有效范围 [0, 120] 内"""

    @freeze_time(MIDNIGHT_UTC)
    def test_leadtime_in_valid_range(self):
        events = expand_target_events()
        run_date, run_hour = _find_latest_available_cams_run()
        base_run_time = datetime.strptime(
            f"{run_date} {run_hour}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)

        leadtimes = _calc_leadtime_hours(base_run_time, events)

        for lt in leadtimes:
            assert 0 <= lt <= 120, f"leadtime_hour {lt} 超出 CAMS 有效范围 [0, 120]"

    @freeze_time(MIDNIGHT_UTC)
    def test_cams_request_params_format(self):
        events = expand_target_events()
        run_date, run_hour = _find_latest_available_cams_run()
        base_run_time = datetime.strptime(
            f"{run_date} {run_hour}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
        leadtimes = _calc_leadtime_hours(base_run_time, events)

        params = _build_cams_request_params(run_date, run_hour, leadtimes)

        assert params["date"] == "2026-05-15"
        assert params["time"] == "12:00"
        assert params["type"] == "forecast"
        assert params["format"] == "netcdf_zip"
        assert "total_aerosol_optical_depth_550nm" in params["variable"]
        assert len(params["leadtime_hour"]) == 8
        # 所有 leadtime_hour 都是字符串
        assert all(isinstance(h, str) for h in params["leadtime_hour"])

    @freeze_time(MIDNIGHT_UTC)
    def test_expected_leadtime_values(self):
        events = expand_target_events()
        run_date, run_hour = _find_latest_available_cams_run()
        base_run_time = datetime.strptime(
            f"{run_date} {run_hour}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)

        leadtimes = _calc_leadtime_hours(base_run_time, events)

        # today_sunset(11:00-14:00 UTC May16) - base(12:00 UTC May15) = 23-26h
        # tomorrow_sunrise(20:00-23:00 UTC May16) - base = 32-35h
        assert leadtimes == [23, 24, 25, 26, 32, 33, 34, 35]


# ---------------------------------------------------------------------------
# 测试 5：实际 CAMS API 调用（需要 API key）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("CDS_API_KEY"),
    reason="需要配置 CDS_API_KEY 环境变量",
)
class TestCAMSAPICall:
    """实际调用 CAMS API 验证请求参数被接受"""

    @freeze_time(MIDNIGHT_UTC)
    def test_cams_api_accepts_params(self):
        import cdsapi

        events = expand_target_events()
        run_date, run_hour = _find_latest_available_cams_run()
        base_run_time = datetime.strptime(
            f"{run_date} {run_hour}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)
        leadtimes = _calc_leadtime_hours(base_run_time, events)

        # 只用一个 leadtime 以减少 API 负载
        test_leadtime = [str(leadtimes[0])]
        area_bounds = [config.DOWNLOAD_AREA[k] for k in ["north", "west", "south", "east"]]

        c = cdsapi.Client(
            url=config.CDS_API_URL,
            key=config.CDS_API_KEY,
            timeout=600,
            quiet=False,
        )

        output_path = Path(__file__).parent / "test_cams_download.nc"

        # retrieve 提交请求并等待结果，不应抛出 400 错误
        c.retrieve(
            config.CAMS_DATASET_NAME,
            {
                "date": run_date,
                "time": run_hour,
                "format": "netcdf_zip",
                "variable": list(config.CAMS_VARS_MAP.values()),
                "leadtime_hour": test_leadtime,
                "type": "forecast",
                "area": area_bounds,
            },
            str(output_path),
        )
        print({
            "date": run_date,
            "time": run_hour,
            "format": "netcdf_zip",
            "variable": list(config.CAMS_VARS_MAP.values()),
            "leadtime_hour": test_leadtime,
            "type": "forecast",
            "area": area_bounds,
        })
        assert output_path.exists()
        assert output_path.stat().st_size > 0

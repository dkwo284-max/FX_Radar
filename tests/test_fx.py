import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fx  # noqa: E402


def fake_rates(n=600, end_val=900.0):
    d0 = date(2025, 1, 1)
    out = {}
    for i in range(n):
        v = 780 + (end_val - 780) * i / (n - 1)
        out[(d0 + timedelta(days=i)).isoformat()] = {"KRW": v, "USD": 0.6, "AUD": 0.9}
    return out


def test_summary_and_signal():
    r = fake_rates()
    data = fx.build(r, None, {"alerts": {"nzd_krw_at_or_above": 880}}, None, datetime(2026, 8, 24, tzinfo=timezone.utc))
    k = data["pairs"]["KRW"]
    assert k["last"] == 900.0 and k["pct1y"] == 100.0 and k["hi52"] == 900.0
    assert data["signal"]["to_kr"] == "아주 유리" and data["signal"]["to_nz"] == "아주 불리"
    assert any("880" in a for a in data["new_alerts"]) and any("상위 10%" in a for a in data["new_alerts"])
    # 다음 날 같은 상태면 알림을 다시 보내지 않는다
    again = fx.build(r, data, {"alerts": {"nzd_krw_at_or_above": 880}}, None, datetime(2026, 8, 25, tzinfo=timezone.utc))
    assert again["new_alerts"] == []
    assert len(data["series"]["d"]) == len(data["series"]["KRW"])


# ── 방향 신호 ──
import math  # noqa: E402

import forecast as fc  # noqa: E402


def series(n=520, start=800.0, drift=0.0, wobble=0.0):
    d0 = date(2025, 1, 1)
    return [((d0 + timedelta(days=i)).isoformat(), start * (1 + drift) ** i * (1 + wobble * math.sin(i / 7))) for i in range(n)]


def test_forecast_uptrend_and_missing_factors():
    k = series(drift=0.0006)
    out = fc.build(k, {})
    s = out["horizons"]["mid"]
    assert s["label"] in ("상승 우세", "약한 상승") and s["score"] > 0  # 추세(+)가 1년 최고 위치(−)보다 무겁다
    mom = next(f for f in s["factors"] if f["id"] == "momentum")
    assert mom["score"] > 0 and "추세" in mom["why"]
    # 보조 데이터가 없으면 그 요인은 빠지고 missing 에 남는다
    assert {"usd", "risk", "rates"} <= set(s["missing"]) and next(f for f in s["factors"] if f["id"] == "usd")["score"] is None
    # 장기: 2년 최고 근처라 위치 요인은 되돌림(하락) 쪽
    pos = next(f for f in out["horizons"]["long"]["factors"] if f["id"] == "position")
    assert pos["score"] < 0
    w = series(wobble=0.01)
    b = fc.band(w, 63)
    assert b["lo90"] < b["lo68"] < w[-1][1] < b["hi68"] < b["hi90"]


def test_forecast_rates_and_linked_factor_sign_from_history():
    k = series(wobble=0.01)
    rates = {"NZ": [(f"2026-{m:02d}", 4.0 + 0.1 * m) for m in range(1, 10)], "KR": [(f"2026-{m:02d}", 3.0) for m in range(1, 10)]}
    r = fc.f_rates(rates)
    assert r["score"] == 2 and "뉴질랜드달러에 유리" in r["why"]
    assert fc.f_rates({"NZ": rates["NZ"]}) is None
    # NZD/KRW 와 반대로 움직이는 지표가 최근 올랐으면 하락 쪽 점수
    inv = [(d, 100 / v * 800 * (1 + 0.0005 * i)) for i, (d, v) in enumerate(k)]
    f = fc.f_linked(k, inv, "지표", 20, 2.0)
    assert f["corr"] < -0.15
    assert (f["score"] < 0) == (f["value"] > 0) or f["score"] == 0
    flat = [(d, 100.0 + (i % 3) * 0.01) for i, (d, _) in enumerate(k)]
    assert fc.f_linked(k, flat, "지표", 20, 2.0)["score"] == 0  # 관계가 약하면 중립


def test_forecast_log_scores_matured_signals():
    k = series(drift=0.0006)
    out = fc.build(k[:-70], {})
    log = out["log"]
    assert any(e["hz"] == "mid" and e["ok"] is None for e in log)
    out2 = fc.build(k, {}, log)
    live = out2["horizons"]["mid"]["live"]
    assert live["n"] == 1 and live["hit"] == 1  # 상승 신호 뒤 실제로 올랐음
    bt = out2["horizons"]["mid"]["backtest"]
    assert bt and bt["n"] >= 12 and bt["rate"] > 60


def test_build_includes_forecast_and_survives_bad_extra():
    r = fake_rates()
    data = fx.build(r, None, {}, None, datetime(2026, 8, 24, tzinfo=timezone.utc), {"usd": [("x", 1.0)], "rates": None})
    assert set(data["forecast"]["horizons"]) == {"short", "mid", "long"}


def test_forecast_hist_and_decomp():
    r = fake_rates()
    d1 = fx.build(r, None, {}, None, datetime(2026, 8, 24, tzinfo=timezone.utc), {})
    f = d1["forecast"]
    assert len(f["hist"]) == 1 and set(f["hist"][0]["h"]) == {"short", "mid", "long"}
    dc = f["decomp"]["1개월"]
    assert abs((1 + dc["nzdusd"] / 100) * (1 + dc["usdkrw"] / 100) - (1 + dc["nzdkrw"] / 100)) < 0.002
    d2 = fx.build(r, d1, {}, None, datetime(2026, 8, 25, tzinfo=timezone.utc), {})
    assert len(d2["forecast"]["hist"]) == 1  # 같은 기준일은 한 줄만

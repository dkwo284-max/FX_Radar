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

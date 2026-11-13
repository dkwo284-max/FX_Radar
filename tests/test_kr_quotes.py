import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import kr_quotes as q  # noqa: E402

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def yahoo_ok(price, ts=1794546000):
    return lambda url: {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": ts}}]}}


def test_yahoo_parse_uses_kst_date():
    p, d = q.from_yahoo("086280", fetch=yahoo_ok(190500.0))
    assert p == 190500 and d == "2026-11-13"


def test_naver_parse():
    f = lambda url: {"datas": [{"closePrice": "190,500", "localTradedAt": "2026-11-13T15:30:00+09:00"}]}  # noqa: E731
    assert q.from_naver("086280", fetch=f) == (190500, "2026-11-13")


def test_fallback_to_second_source_and_keep_old_on_failure():
    def bad(code):
        raise RuntimeError("blocked")
    n = {"086280": 111, "004020": None}

    def good(code):
        v = n.get(code)
        if v is None:
            raise RuntimeError("no price")
        return v, "2026-11-13"
    old = {"prices": {"innocean": 16000}, "dates": {"innocean": "2026-11-12"}, "src": {"innocean": "yahoo"}}
    out = q.collect(old, sources=(("yahoo", bad), ("naver", good)), now=NOW)
    assert out["prices"] == {"innocean": 16000, "glovis": 111} and out["dates"]["innocean"] == "2026-11-12"
    assert out["partial"] is True and out["asOf"] == "2026-11-13" and out["src"]["glovis"] == "naver"


def test_all_fail_returns_none():
    def bad(code):
        raise RuntimeError("x")
    assert q.collect({}, sources=(("a", bad),), now=NOW) is None


def test_with_fx(tmp_path):
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"pairs": {"KRW": {"last": 741.31, "date": "2026-11-12"}}}))
    out = q.with_fx({"prices": {}}, p)
    assert out["fx"] == 741.31 and out["fxDate"] == "2026-11-12"
    assert "fx" not in q.with_fx({}, tmp_path / "none.json")

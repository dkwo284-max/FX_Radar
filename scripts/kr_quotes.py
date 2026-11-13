"""한국 주식 종가 3종목 + NZD/KRW 환율을 web/data/kr-quotes.json 으로 저장 (AI 0회).

- 배당·세금·건보료 대시보드(비공개 아티팩트)의 '현재 주가' 입력칸을 자동으로 채우는 데 쓰입니다.
  아티팩트는 외부 사이트를 직접 읽을 수 없어서, 이 파일을 예약 작업이 읽어 앱 DB로 옮깁니다.
- 주가: Yahoo Finance 차트 API(KRX 종목은 .KS) → 안 되면 네이버 증권 공개 시세 API. 종목별로 따로 시도.
- 못 받은 종목은 이전 파일의 값을 그대로 두고(날짜도 그대로), 하나도 못 받으면 파일을 건드리지 않습니다.
- 환율은 같은 저장소의 fx.json(ECB 기준환율)에서 가져옵니다.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "kr-quotes.json"
FX = ROOT / "web" / "data" / "fx.json"
UA = "FXRadarBot/1.0 (+https://github.com/dkwo284-max/FX_Radar)"
STOCKS = {"glovis": "086280", "steel": "004020", "innocean": "214320"}
KST = timezone(timedelta(hours=9))


def get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(v) -> int | None:
    try:
        n = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(round(n)) if n > 0 else None


def from_yahoo(code: str, fetch=get_json):
    j = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.KS?range=5d&interval=1d")
    meta = j["chart"]["result"][0]["meta"]
    price, ts = _num(meta.get("regularMarketPrice")), meta.get("regularMarketTime")
    if not price or not ts:
        raise ValueError("yahoo: 가격 없음")
    return price, datetime.fromtimestamp(int(ts), KST).date().isoformat()


def from_naver(code: str, fetch=get_json):
    j = fetch(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}")
    row = (j.get("datas") or [{}])[0]
    price = _num(row.get("closePrice"))
    when = str(row.get("localTradedAt") or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", when)
    if not price or not m:
        raise ValueError("naver: 가격 없음")
    return price, m.group(1)


def collect(old: dict, sources=(("yahoo", from_yahoo), ("naver", from_naver)), now: datetime | None = None) -> dict | None:
    """종목별로 소스를 순서대로 시도. 하나도 새로 못 받으면 None."""
    now = now or datetime.now(timezone.utc)
    prices = dict(old.get("prices") or {})
    dates = dict(old.get("dates") or {})
    src = dict(old.get("src") or {})
    errors, got = {}, 0
    for sid, code in STOCKS.items():
        for name, fn in sources:
            try:
                p, d = fn(code)
                prices[sid], dates[sid], src[sid] = p, d, name
                got += 1
                break
            except Exception as e:  # noqa: BLE001
                errors[f"{sid}/{name}"] = str(e)[:120]
    if not got:
        print("주가를 하나도 받지 못함:", errors, file=sys.stderr)
        return None
    if errors:
        print("일부 실패:", errors, file=sys.stderr)
    out = {"asOf": max(dates.values()), "fetchedAt": now.replace(microsecond=0).isoformat(), "prices": prices, "dates": dates, "src": src}
    if len(prices) < len(STOCKS):
        out["partial"] = True
    return out


def with_fx(out: dict, fx_path: Path = FX) -> dict:
    try:
        k = json.loads(fx_path.read_text(encoding="utf-8"))["pairs"]["KRW"]
        out["fx"], out["fxDate"] = round(float(k["last"]), 2), k.get("date")
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            old = {}
    out = collect(old)
    if out is None:
        return 1
    out = with_fx(out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("저장:", out["prices"], out["asOf"], "fx", out.get("fx"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

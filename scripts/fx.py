"""FX Radar 데이터 만들기: NZD/KRW 환율 추이·위치·송금 타이밍 신호 (AI 0회).

- 환율: frankfurter(ECB 기준환율, 평일 하루 1회) 2년치 일별. 실패하면 이전 데이터를 그대로 두고 종료(화면은 '갱신 실패'를 표시).
- 송금 비교: Wise 공개 비교 API(로그인 불필요)가 응답하면 업체별 견적을 함께 저장. 실패해도 나머지는 정상.
- 목표 환율 알림: config.json 의 목표에 닿았거나 1년 중 상위·하위 10% 구간에 처음 들어간 날 알림 문구를 남김
  (TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 비밀값이 있으면 텔레그램으로도 보냄).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "fx.json"
CFG = ROOT / "config.json"
UA = "FXRadarBot/1.0 (+https://github.com/dkwo284-max/FX_Radar)"
PAIRS = ["KRW", "USD", "AUD"]  # NZD 1 기준


def get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_series(start: str) -> dict[str, dict[str, float]]:
    """{날짜: {KRW: .., USD: .., AUD: ..}} — 두 주소 중 되는 쪽."""
    syms = ",".join(PAIRS)
    urls = [f"https://api.frankfurter.dev/v1/{start}..?base=NZD&symbols={syms}",
            f"https://api.frankfurter.app/{start}..?from=NZD&to={syms}"]
    last = None
    for u in urls:
        try:
            j = get_json(u)
            rates = j.get("rates") or {}
            if len(rates) > 100:
                return {d: {k: float(v) for k, v in r.items()} for d, r in sorted(rates.items())}
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"환율 데이터를 받지 못함: {last}")


def wise_quotes(amount: int = 1000) -> dict | None:
    """Wise 공개 비교 API: NZD amount → KRW, 업체별 받는 금액. 실패하면 None."""
    try:
        j = get_json(f"https://api.wise.com/v4/comparisons/?sourceCurrency=NZD&targetCurrency=KRW&sendAmount={amount}", timeout=20)
    except Exception:  # noqa: BLE001
        return None
    rows = []
    for p in j.get("providers", []) or []:
        q = (p.get("quotes") or [{}])[0]
        recv, fee, rate = q.get("receivedAmount"), q.get("fee"), q.get("rate")
        if recv is None:
            continue
        rows.append({"name": p.get("name") or p.get("alias") or "?", "received": round(float(recv)),
                     "fee": None if fee is None else round(float(fee), 2), "rate": None if rate is None else round(float(rate), 3),
                     "type": p.get("type", "")})
    if not rows:
        return None
    rows.sort(key=lambda r: -r["received"])
    return {"amount": amount, "from": "NZD", "to": "KRW", "providers": rows[:8],
            "source": "Wise 비교(공개 API) — Wise 가 수집한 업체 견적이며 실제 송금 시점과 다를 수 있음",
            "fetched": datetime.now(timezone.utc).isoformat(timespec="minutes")}


def get_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def _try(fn, name: str):
    """보조 데이터는 못 받아도 환율 갱신을 막지 않는다(그 요인만 화면에서 '데이터 없음')."""
    try:
        v = fn()
        if v:
            return v
        print(f"::warning::{name}: 빈 응답")
    except Exception as e:  # noqa: BLE001
        print(f"::warning::{name}: {str(e)[:120]}")
    return None


def usd_basket(start: str):
    """달러 지수 대용: 유로·엔·파운드 대비 달러 가치의 기하평균(시작일 = 100)."""
    j = get_json(f"https://api.frankfurter.dev/v1/{start}..?base=USD&symbols=EUR,JPY,GBP")
    rows = sorted(j.get("rates", {}).items())
    base = rows[0][1]
    return [(d, 100 * (r["EUR"] / base["EUR"] * r["JPY"] / base["JPY"] * r["GBP"] / base["GBP"]) ** (1 / 3)) for d, r in rows if len(r) == 3]


def yahoo_series(symbol: str):
    j = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=2y&interval=1d")
    res = j["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    return [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), float(c)) for t, c in zip(res["timestamp"], closes) if c]


def fred_monthly(series_id: str):
    """FRED 공개 CSV(키 불필요): 월별 값 [(YYYY-MM, 값)]."""
    out = []
    for line in get_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={date.today().year - 3}-01-01").splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            out.append((d[:7], float(v)))
        except ValueError:
            continue
    return out


def fetch_extra(start: str) -> dict:
    """방향 신호용 보조 데이터. 하나씩 따로 시도한다."""
    rates = {c: _try(lambda sid=sid: fred_monthly(sid), f"fred {c}") for c, sid in (("NZ", "IR3TIB01NZM156N"), ("KR", "IR3TIB01KRM156N"), ("US", "IR3TIB01USM156N"))}
    return {"usd": _try(lambda: usd_basket(start), "usd basket"), "spx": _try(lambda: yahoo_series("^GSPC"), "yahoo spx"),
            "kospi": _try(lambda: yahoo_series("^KS11"), "yahoo kospi"), "milk": _try(lambda: yahoo_series("DC=F"), "yahoo milk"),
            "rates": rates if rates["NZ"] and rates["KR"] else None}


def pct_rank(xs: list[float], v: float) -> float:
    return round(100 * sum(1 for x in xs if x <= v) / len(xs), 1) if xs else 50.0


def chg(series: list[tuple[str, float]], days: int) -> float | None:
    if not series:
        return None
    d0 = date.fromisoformat(series[-1][0]) - timedelta(days=days)
    past = [v for d, v in series if date.fromisoformat(d) <= d0]
    return round((series[-1][1] / past[-1] - 1) * 100, 2) if past else None


def summarize(rates: dict[str, dict[str, float]], sym: str) -> dict:
    s = [(d, r[sym]) for d, r in rates.items() if sym in r]
    last_d, last = s[-1]
    yr = [v for d, v in s if date.fromisoformat(d) > date.fromisoformat(last_d) - timedelta(days=365)]
    ma = lambda n: round(statistics.fmean(v for _, v in s[-n:]), 3)  # noqa: E731
    return {"last": round(last, 3), "date": last_d, "chg": {"1w": chg(s, 7), "1m": chg(s, 30), "3m": chg(s, 91), "1y": chg(s, 365)},
            "hi52": round(max(yr), 3), "lo52": round(min(yr), 3), "pct1y": pct_rank(yr, last), "ma30": ma(21), "ma90": ma(63)}


def signal(k: dict) -> dict:
    """송금 타이밍: 1년 분포에서 지금 위치(백분위). NZD→KRW(한국으로 보낼 때)는 높을수록 유리, KRW→NZD 는 반대."""
    p = k["pct1y"]
    to_kr = "아주 유리" if p >= 90 else "유리" if p >= 70 else "보통" if p >= 30 else "불리" if p >= 10 else "아주 불리"
    to_nz = {"아주 유리": "아주 불리", "유리": "불리", "보통": "보통", "불리": "유리", "아주 불리": "아주 유리"}[to_kr]
    trend = "오르는 중" if k["last"] > k["ma30"] > k["ma90"] else "내리는 중" if k["last"] < k["ma30"] < k["ma90"] else "횡보"
    return {"to_kr": to_kr, "to_nz": to_nz, "trend": trend,
            "text": f"1년 중 {f'상위 {max(1, round(100 - p))}%' if p >= 50 else f'하위 {max(1, round(p))}%'} 수준 · 30일 평균 대비 {(k['last'] / k['ma30'] - 1) * 100:+.1f}% · {trend}"}


def alerts(k: dict, prev: dict | None, cfg: dict) -> list[str]:
    out, last = [], k["last"]
    pk = (prev or {}).get("pairs", {}).get("KRW", {}) if prev else {}
    plast, ppct = pk.get("last"), pk.get("pct1y")
    hi, lo = (cfg.get("alerts") or {}).get("nzd_krw_at_or_above"), (cfg.get("alerts") or {}).get("nzd_krw_at_or_below")
    if hi and last >= hi and not (plast and plast >= hi):
        out.append(f"NZD/KRW {last:.2f}원 — 목표 {hi}원 이상 도달 (한국 송금 유리)")
    if lo and last <= lo and not (plast and plast <= lo):
        out.append(f"NZD/KRW {last:.2f}원 — 목표 {lo}원 이하 도달 (뉴질랜드로 송금 유리)")
    if k["pct1y"] >= 90 and not (ppct and ppct >= 90):
        out.append(f"NZD/KRW {last:.2f}원 — 1년 중 상위 10% 구간 진입")
    if k["pct1y"] <= 10 and not (ppct is not None and ppct <= 10):
        out.append(f"NZD/KRW {last:.2f}원 — 1년 중 하위 10% 구간 진입")
    return out


def notify(lines: list[str]) -> None:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat and lines):
        return
    body = json.dumps({"chat_id": chat, "text": "💱 FX Radar\n" + "\n".join(lines) + "\nhttps://dkwo284-max.github.io/FX_Radar/"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                                      headers={"Content-Type": "application/json"}), timeout=20)
    except Exception as e:  # noqa: BLE001
        print("telegram failed:", e, file=sys.stderr)


def build(rates: dict, prev: dict | None, cfg: dict, quotes: dict | None, now: datetime, extra: dict | None = None) -> dict:
    pairs = {sym: summarize(rates, sym) for sym in PAIRS}
    k = pairs["KRW"]
    sig = signal(k)
    new_alerts = alerts(k, prev, cfg)
    hist = [a for a in (prev or {}).get("alerts", []) if a.get("date", "") >= (now.date() - timedelta(days=60)).isoformat()]
    hist += [{"date": now.date().isoformat(), "text": t} for t in new_alerts]
    one_year = (date.fromisoformat(k["date"]) - timedelta(days=730)).isoformat()
    series = {"d": [d for d in rates if d >= one_year], **{sym: [rates[d].get(sym) for d in rates if d >= one_year] for sym in PAIRS}}
    return {"generated_at": now.isoformat(timespec="minutes"), "source": "ECB 기준환율 (frankfurter.dev, 평일 하루 1회 고시)",
            "pairs": pairs, "signal": sig, "alerts": hist[-20:], "new_alerts": new_alerts,
            "targets": cfg.get("alerts") or {}, "quotes": quotes or (prev or {}).get("quotes"), "series": series,
            "forecast": _forecast(rates, extra, prev)}


def _forecast(rates: dict, extra: dict | None, prev: dict | None) -> dict | None:
    """방향 신호(규칙 기반). 계산이 실패해도 환율 데이터는 그대로 내보낸다."""
    try:
        import forecast as fc
        k = [(d, r["KRW"]) for d, r in rates.items() if "KRW" in r]
        if len(k) < 300:
            return (prev or {}).get("forecast")
        pf = (prev or {}).get("forecast") or {}
        out = fc.build(k, extra or {}, pf.get("log"), pf.get("hist"))
        # NZD/KRW 변화 = NZD/USD 변화(뉴질랜드달러 쪽) + USD/KRW 변화(원화 쪽)
        u = [(d, r["USD"]) for d, r in rates.items() if "USD" in r and "KRW" in r]
        uk = [(d, r["KRW"] / r["USD"]) for d, r in rates.items() if "USD" in r and "KRW" in r]
        out["decomp"] = {name: {"nzdkrw": round(fc.pct_change(k, n) or 0, 2), "nzdusd": round(fc.pct_change(u, n) or 0, 2), "usdkrw": round(fc.pct_change(uk, n) or 0, 2)}
                         for name, n in (("1주", 5), ("1개월", 21), ("3개월", 63), ("1년", 250)) if len(u) > n}
        out["usdkrw"] = round(uk[-1][1], 1)
        ex = extra or {}
        out["inputs"] = {n: (ex[n][-1][0] if ex.get(n) else None) for n in ("usd", "spx", "kospi", "milk")}
        out["inputs"]["rates"] = ex["rates"]["NZ"][-1][0] if ex.get("rates") else None
        return out
    except Exception as e:  # noqa: BLE001
        print(f"::warning::forecast: {str(e)[:160]}")
        return (prev or {}).get("forecast")


def main() -> int:
    now = datetime.now(timezone.utc)
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
    start = (now.date() - timedelta(days=760)).isoformat()
    try:
        rates = fetch_series(start)
    except Exception as e:  # noqa: BLE001
        print(f"::warning::{e}")
        return 0  # 이전 데이터 유지
    data = build(rates, prev, cfg, wise_quotes(int(cfg.get("send_amount", 1000))), now, fetch_extra(start))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    notify(data["new_alerts"])
    k = data["pairs"]["KRW"]
    fcst = data.get("forecast") or {}
    print("forecast:", {h: (v["label"], v["score"], v["missing"]) for h, v in (fcst.get("horizons") or {}).items()})
    print(f"NZD/KRW {k['last']} ({k['date']}) · 1y pct {k['pct1y']} · alerts {len(data['new_alerts'])} · quotes {'yes' if data['quotes'] else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

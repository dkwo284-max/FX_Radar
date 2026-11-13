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


def build(rates: dict, prev: dict | None, cfg: dict, quotes: dict | None, now: datetime) -> dict:
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
            "targets": cfg.get("alerts") or {}, "quotes": quotes or (prev or {}).get("quotes"), "series": series}


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
    data = build(rates, prev, cfg, wise_quotes(int(cfg.get("send_amount", 1000))), now)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    notify(data["new_alerts"])
    k = data["pairs"]["KRW"]
    print(f"NZD/KRW {k['last']} ({k['date']}) · 1y pct {k['pct1y']} · alerts {len(data['new_alerts'])} · quotes {'yes' if data['quotes'] else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

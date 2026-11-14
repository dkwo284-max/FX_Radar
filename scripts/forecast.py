"""NZD/KRW 방향 신호: 요인별 점수(규칙 기반, AI 0회)를 기간별로 합산한다.

- 예측이 아니라 '지금 요인들이 어느 쪽을 가리키는지'의 요약이다. 목표 환율은 내지 않는다.
- 요인 점수는 -2 ~ +2 (+ = NZD/KRW 상승 쪽 = 원화 대비 뉴질랜드달러 강세).
- 달러·위험선호처럼 방향이 고정돼 있지 않은 요인은 최근 1년의 실제 관계(주간 수익률 상관)로 부호를 정하고,
  관계가 약하면(|상관| < 0.15) 중립으로 둔다.
- 받지 못한 보조 데이터의 요인은 빼고 계산한다(화면에 '데이터 없음').
"""
from __future__ import annotations

import math
import statistics

Series = list[tuple[str, float]]

HORIZONS = {"short": {"label": "1–2주", "days": 10}, "mid": {"label": "1–3개월", "days": 63}, "long": {"label": "6–12개월", "days": 250}}
# 기간별 요인 가중치 (0 = 그 기간에는 쓰지 않음)
WEIGHTS = {
    "momentum": {"short": 3, "mid": 2, "long": 1},
    "position": {"short": 1, "mid": 1, "long": 3},
    "rates":    {"short": 0, "mid": 3, "long": 3},
    "usd":      {"short": 2, "mid": 2, "long": 0},
    "risk":     {"short": 2, "mid": 1, "long": 0},
    "dairy":    {"short": 0, "mid": 1, "long": 1},
    "korea":    {"short": 0, "mid": 1, "long": 1},
}
GROUPS = {"momentum": "추세·위치", "position": "추세·위치", "rates": "금리 차와 중앙은행", "usd": "달러·위험 선호",
          "risk": "달러·위험 선호", "dairy": "원자재·교역", "korea": "원자재·교역"}


def clamp(v: float, lo: float = -2, hi: float = 2) -> float:
    return max(lo, min(hi, v))


def pct_change(s: Series, n: int) -> float | None:
    """n 거래일 전 대비 변화율(%)."""
    return (s[-1][1] / s[-1 - n][1] - 1) * 100 if len(s) > n and s[-1 - n][1] else None


def ma(s: Series, n: int) -> float:
    return statistics.fmean(v for _, v in s[-n:])


def pct_rank(xs: list[float], v: float) -> float:
    return 100 * sum(1 for x in xs if x <= v) / len(xs) if xs else 50.0


def weekly_corr(a: Series, b: Series, weeks: int = 52) -> float | None:
    """두 계열의 주간(5거래일) 수익률 상관. 날짜가 겹치는 부분만 쓴다."""
    bm = dict(b)
    pts = [(d, v, bm[d]) for d, v in a if d in bm][-(weeks * 5 + 1):]
    ra, rb = [], []
    for i in range(5, len(pts), 5):
        if pts[i - 5][1] and pts[i - 5][2]:
            ra.append(pts[i][1] / pts[i - 5][1] - 1)
            rb.append(pts[i][2] / pts[i - 5][2] - 1)
    if len(ra) < 20:
        return None
    try:
        return statistics.correlation(ra, rb)
    except statistics.StatisticsError:
        return None


# ── 요인 ──────────────────────────────────────────────────────

def f_momentum(k: Series, hz: str) -> dict:
    last = k[-1][1]
    if hz == "short":
        c5, c20 = pct_change(k, 5) or 0, pct_change(k, 20) or 0
        s = clamp(c5 / 0.8) * 0.5 + clamp(c20 / 1.5) * 0.5
        why = f"최근 1주 {c5:+.1f}%, 1개월 {c20:+.1f}%"
    elif hz == "mid":
        m21, m63 = ma(k, 21), ma(k, 63)
        s = (1 if m21 > m63 else -1) + (1 if last > m63 else -1)
        why = f"30일 평균이 90일 평균 {'위' if m21 > m63 else '아래'}, 현재가는 90일 평균 대비 {(last / m63 - 1) * 100:+.1f}%"
    else:
        m200 = ma(k, min(200, len(k)))
        d = (last / m200 - 1) * 100
        s = clamp(d / 3)
        why = f"200일 평균 대비 {d:+.1f}%"
    return {"score": round(clamp(s), 2), "why": why + (" → 추세가 이어지는 쪽" if abs(s) >= 0.5 else " → 뚜렷한 추세 없음")}


def f_position(k: Series, hz: str) -> dict:
    """평균 회귀: 범위의 끝에 가까울수록 반대 방향 점수."""
    n = 250 if hz != "long" else len(k)
    p = pct_rank([v for _, v in k[-n:]], k[-1][1])
    s = 2 if p <= 5 else 1 if p <= 20 else -2 if p >= 95 else -1 if p >= 80 else 0
    span = "1년" if hz != "long" else "2년"
    side = f"하위 {max(1, round(p))}%" if p < 50 else f"상위 {max(1, round(100 - p))}%"
    return {"score": s, "why": f"{span} 범위에서 {side} 위치" + (" → 되돌림(반등) 여지" if s > 0 else " → 되돌림(하락) 여지" if s < 0 else " → 범위 중간"), "value": round(p, 1)}


def f_rates(rates: dict | None) -> dict | None:
    """3개월 금리 차(뉴질랜드 − 한국). 금리가 높고 차이가 벌어지는 통화가 대체로 강하다."""
    nz, kr = (rates or {}).get("NZ"), (rates or {}).get("KR")
    if not nz or not kr:
        return None
    km = dict(kr)
    diff = [(d, v - km[d]) for d, v in nz if d in km]
    if len(diff) < 7:
        return None
    now, ago = diff[-1][1], diff[-7][1]
    s = (1 if now > 0.5 else -1 if now < -0.5 else 0) + (1 if now - ago > 0.25 else -1 if now - ago < -0.25 else 0)
    return {"score": s, "value": round(now, 2), "asof": diff[-1][0],
            "why": f"3개월 금리 뉴질랜드 {nz[-1][1]:.2f}% − 한국 {km[diff[-1][0]]:.2f}% = {now:+.2f}%p, 6개월 전보다 {now - ago:+.2f}%p"
                   + (" → 뉴질랜드달러에 유리" if s > 0 else " → 원화에 유리" if s < 0 else " → 차이 작음")}


def f_linked(k: Series, other: Series | None, name: str, days: int, scale: float) -> dict | None:
    """다른 지표의 최근 움직임 × 최근 1년 NZD/KRW 와의 실제 관계."""
    if not other or len(other) <= days:
        return None
    c = weekly_corr(k, other)
    mv = pct_change(other, days)
    if c is None or mv is None:
        return None
    if abs(c) < 0.15:
        return {"score": 0, "value": round(mv, 2), "corr": round(c, 2), "why": f"{name} {days}거래일 {mv:+.1f}% · 최근 1년 NZD/KRW 와의 관계가 약함(상관 {c:+.2f}) → 중립"}
    s = clamp(mv / scale) * (1 if c > 0 else -1)
    rel = "같은 방향" if c > 0 else "반대 방향"
    return {"score": round(s, 2), "value": round(mv, 2), "corr": round(c, 2),
            "why": f"{name} {days}거래일 {mv:+.1f}% · 최근 1년 NZD/KRW 와 {rel}(상관 {c:+.2f})"}


def factors(k: Series, extra: dict, hz: str) -> dict:
    d = 20 if hz == "short" else 60
    out = {
        "momentum": f_momentum(k, hz),
        "position": f_position(k, hz),
        "rates": f_rates(extra.get("rates")),
        "usd": f_linked(k, extra.get("usd"), "달러 지수(유로·엔·파운드 대비)", d, 2.0),
        "risk": f_linked(k, extra.get("spx"), "미국 주식(S&P 500)", d, 4.0),
        "dairy": f_linked(k, extra.get("milk"), "유제품 선물(미국 Class III, 참고 지표)", 60, 8.0),
        "korea": f_linked(k, extra.get("kospi"), "코스피", 60, 8.0),
    }
    return {name: f for name, f in out.items() if WEIGHTS[name][hz]}


def label(x: float) -> str:
    return "상승 우세" if x >= 0.35 else "약한 상승" if x >= 0.12 else "하락 우세" if x <= -0.35 else "약한 하락" if x <= -0.12 else "중립"


def combine(fs: dict, hz: str) -> dict:
    live = {n: f for n, f in fs.items() if f}
    wsum = sum(WEIGHTS[n][hz] * 2 for n in live)
    x = sum(WEIGHTS[n][hz] * f["score"] for n, f in live.items()) / wsum if wsum else 0.0
    up = sum(1 for f in live.values() if f["score"] >= 0.5)
    dn = sum(1 for f in live.values() if f["score"] <= -0.5)
    return {"score": round(x, 3), "label": label(x), "up": up, "down": dn, "neutral": len(live) - up - dn,
            "missing": [n for n, f in fs.items() if not f]}


def band(k: Series, days: int) -> dict:
    """과거 1년 일간 변동성으로 본 앞으로의 범위(68%·90%). 방향이 아니라 불확실성의 크기."""
    vals = [v for _, v in k[-251:]]
    rets = [math.log(b / a) for a, b in zip(vals, vals[1:]) if a and b]
    sd = statistics.pstdev(rets) * math.sqrt(days) if len(rets) > 20 else 0.0
    last = k[-1][1]
    return {"days": days, "lo68": round(last * math.exp(-sd), 1), "hi68": round(last * math.exp(sd), 1),
            "lo90": round(last * math.exp(-1.645 * sd), 1), "hi90": round(last * math.exp(1.645 * sd), 1)}


def backtest(k: Series, hz: str, step: int = 5) -> dict | None:
    """가격만으로 계산되는 요인(추세·위치)의 과거 적중률. 중립 신호는 세지 않는다."""
    h = HORIZONS[hz]["days"]
    hit = n = 0
    for i in range(260, len(k) - h, step):
        past = k[: i + 1]
        fs = {"momentum": f_momentum(past, hz), "position": f_position(past, hz)}
        x = sum(WEIGHTS[m][hz] * f["score"] for m, f in fs.items()) / sum(WEIGHTS[m][hz] * 2 for m in fs)
        if abs(x) < 0.12:
            continue
        n += 1
        hit += (k[i + h][1] > k[i][1]) == (x > 0)
    return {"n": n, "hit": hit, "rate": round(100 * hit / n, 1)} if n >= 12 else None


def update_log(log: list, today: str, k: Series, result: dict) -> tuple[list, dict]:
    """실제 신호 기록: 오늘 신호를 남기고, 기간이 지난 기록을 채점한다."""
    dates = [d for d, _ in k]
    price = dict(k)
    log = [dict(e) for e in log][-600:]
    for e in log:
        if e.get("ok") is None and e["date"] in price:
            i = dates.index(e["date"])
            if i + e["days"] < len(dates):
                e["ok"] = (k[i + e["days"]][1] > e["rate"]) == (e["dir"] > 0)
    if today in price and not any(e["date"] == today for e in log):
        for hz, r in result.items():
            if r["label"] != "중립":
                log.append({"date": today, "hz": hz, "days": HORIZONS[hz]["days"], "dir": 1 if r["score"] > 0 else -1, "rate": k[-1][1], "ok": None})
    stats = {}
    for hz in HORIZONS:
        done = [e for e in log if e["hz"] == hz and e.get("ok") is not None]
        stats[hz] = {"n": len(done), "hit": sum(1 for e in done if e["ok"]), "open": sum(1 for e in log if e["hz"] == hz and e.get("ok") is None)}
    return log, stats


def build(k: Series, extra: dict, prev_log: list | None = None) -> dict:
    out, res = {}, {}
    for hz, meta in HORIZONS.items():
        fs = factors(k, extra, hz)
        c = combine(fs, hz)
        res[hz] = c
        out[hz] = {"name": meta["label"], "days": meta["days"], **c, "band": band(k, meta["days"]), "backtest": backtest(k, hz) if hz != "long" else None,
                   "factors": [{"id": n, "group": GROUPS[n], "weight": WEIGHTS[n][hz], **(f or {"score": None, "why": "데이터를 받지 못해 계산에서 뺐습니다"})} for n, f in fs.items()]}
    log, stats = update_log(prev_log or [], k[-1][0], k, res)
    for hz in out:
        out[hz]["live"] = stats[hz]
    return {"asof": k[-1][0], "horizons": out, "log": log}

"""Indicatori di analisi tecnica su serie giornaliere (liste semplici, nessuna libreria esterna).

Tutto descrittivo: medie, RSI, MACD, ATR, livelli pivot, volumi. Nessun consiglio di acquisto/vendita.
"""
from __future__ import annotations

import datetime as dt
import math


def sma(x: list[float], n: int) -> float | None:
    return sum(x[-n:]) / n if len(x) >= n else None


def ema_series(x: list[float], n: int) -> list[float]:
    if not x:
        return []
    k = 2 / (n + 1)
    out = [x[0]]
    for v in x[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(c: list[float], n: int = 14) -> float | None:
    """RSI di Wilder."""
    if len(c) <= n:
        return None
    gains = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd(c: list[float]) -> tuple[float | None, int]:
    """Istogramma MACD(12,26,9) e incrocio negli ultimi 3 giorni (+1 al rialzo, -1 al ribasso, 0)."""
    if len(c) < 35:
        return None, 0
    e12, e26 = ema_series(c, 12), ema_series(c, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = ema_series(line, 9)
    hist = [a - b for a, b in zip(line, sig)]
    cross = 0
    for i in range(len(hist) - 3, len(hist)):
        if hist[i - 1] <= 0 < hist[i]:
            cross = 1
        elif hist[i - 1] >= 0 > hist[i]:
            cross = -1
    return hist[-1], cross


def atr(h: list[float], l: list[float], c: list[float], n: int = 14) -> float | None:
    if len(c) <= n:
        return None
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def chg(c: list[float], n: int) -> float | None:
    return (c[-1] / c[-1 - n] - 1) * 100 if len(c) > n and c[-1 - n] else None


def r4(x: float | None) -> float | None:
    """Arrotonda a 4 cifre significative (file piu' piccoli)."""
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return 0.0
    d = max(0, 3 - int(math.floor(math.log10(abs(x)))))
    return round(x, d)


def session_complete(ts: int, meta: dict, now: float) -> bool:
    """L'ultima barra e' una seduta chiusa? (altrimenti e' la giornata in corso)."""
    per = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    end = per.get("end")
    start = per.get("start")
    if start and end and start <= now < end and ts >= start - 86400 // 2:
        return False
    return True


def analyze(s: dict, now: float, keep_open_bar: bool = False) -> dict | None:
    """Riassunto tecnico di una serie {meta,t,o,h,l,c,v}.

    Se la seduta di oggi e' ancora aperta l'ultima barra viene esclusa dai volumi
    (sarebbe parziale) ma resta per prezzo e variazione se keep_open_bar=True.
    """
    t, o, h, l, c, v = s["t"], s["o"], s["h"], s["l"], s["c"], s["v"]
    if len(c) < 30:
        return None
    meta = s.get("meta", {})
    live = not session_complete(t[-1], meta, now)
    if live and not keep_open_bar:
        t, o, h, l, c, v = t[:-1], o[:-1], h[:-1], l[:-1], c[:-1], v[:-1]
        live = False
    # volumi: ultima seduta CHIUSA contro la media delle 60 precedenti
    vc = v[:-1] if live else v
    vol_last = vc[-1] if vc else 0
    prev = [x for x in vc[-61:-1] if x]
    vavg60 = sum(prev) / len(prev) if len(prev) >= 40 else None
    vr = vol_last / vavg60 if vavg60 and vol_last else None

    last = c[-1]
    s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
    s50_prev = sum(c[-55:-5]) / 50 if len(c) >= 55 else None
    a = atr(h, l, c)
    hist, cross = macd(c)
    r = rsi(c)
    # pivot classici calcolati sull'ultima seduta chiusa (valgono per la seduta successiva)
    k = -2 if live else -1
    H, L, C = h[k], l[k], c[k]
    P = (H + L + C) / 3
    piv = {"p": r4(P), "r1": r4(2 * P - L), "s1": r4(2 * P - H), "r2": r4(P + (H - L)), "s2": r4(P - (H - L))}

    up = s50 is not None and last > s50 and (s200 is None or s50 > s200) and (s50_prev is None or s50 >= s50_prev)
    down = s50 is not None and last < s50 and (s200 is None or s50 < s200) and (s50_prev is None or s50 <= s50_prev)
    trend = "rialzo" if up else "ribasso" if down else "laterale"
    score = 0
    for ref in (s20, s50, s200):
        if ref is not None:
            score += 1 if last > ref else -1
    if hist is not None:
        score += 1 if hist > 0 else -1
    if r is not None:
        score += -1 if r > 70 else 1 if r < 30 else 0

    return {
        "d": dt.datetime.fromtimestamp(t[-1], dt.timezone.utc).strftime("%Y-%m-%d"),
        "live": live,
        "cur": meta.get("currency"),
        "c": r4(last), "ch1": r4(chg(c, 1)), "ch5": r4(chg(c, 5)), "ch21": r4(chg(c, 21)), "ch63": r4(chg(c, 63)),
        "hi52": r4(max(h[-252:])), "lo52": r4(min(l[-252:])),
        "sma20": r4(s20), "sma50": r4(s50), "sma200": r4(s200),
        "rsi": r4(r), "macd_h": r4(hist), "macd_x": cross,
        "atr": r4(a), "atr_pct": r4(a / last * 100) if a else None,
        "piv": piv, "sup": r4(min(l[-20:])), "res": r4(max(h[-20:])),
        "trend": trend, "score": score,
        "vol": vol_last, "vavg60": round(vavg60) if vavg60 else None, "vr": r4(vr),
        "h": [r4(x) for x in c[-30:]],
    }

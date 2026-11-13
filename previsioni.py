"""Quadro del mattino: mercati esteri, future e stima (indicativa) dell'apertura di Piazza Affari.

Regole semplici e trasparenti, verificate a posteriori (storico.json): non sono consigli.
"""
from __future__ import annotations

from fonti import chart, charts
from tecnica import r4

MACRO = [
    ("^GSPC", "S&P 500", "usa"), ("^IXIC", "Nasdaq", "usa"), ("^DJI", "Dow Jones", "usa"),
    ("ES=F", "Future S&P 500", "fut"), ("NQ=F", "Future Nasdaq", "fut"),
    ("^N225", "Nikkei (Tokyo)", "asia"), ("^HSI", "Hang Seng (Hong Kong)", "asia"), ("000001.SS", "Shanghai", "asia"),
    ("FTSEMIB.MI", "FTSE MIB (Milano)", "eu"), ("^STOXX50E", "Euro Stoxx 50", "eu"), ("^GDAXI", "DAX (Francoforte)", "eu"),
    ("^VIX", "VIX (indice della paura)", "vol"), ("EURUSD=X", "Euro / Dollaro", "fx"),
    ("BZ=F", "Petrolio Brent", "comm"), ("GC=F", "Oro", "comm"), ("^TNX", "Tasso USA a 10 anni", "rate"),
    ("BTC-USD", "Bitcoin", "crypto"),
]


def macro(now: float) -> list[dict]:
    data = charts([s for s, _, _ in MACRO], rng="1d", interval="15m")
    out = []
    for s, name, grp in MACRO:
        d = data.get(s)
        if not d:
            continue
        m = d["meta"]
        last, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose")
        if not last or not prev:
            continue
        out.append({"s": s, "n": name, "g": grp, "c": r4(last), "ch": r4((last / prev - 1) * 100),
                    "ts": m.get("regularMarketTime"), "cur": m.get("currency")})
    return out


def _price_at(series: dict, ts: float) -> float | None:
    p = None
    for t, c in zip(series["t"], series["c"]):
        if t <= ts:
            p = c
        else:
            break
    return p


def outlook(now: float, mac: list[dict], mib_ta: dict | None, events: list[dict]) -> dict:
    """Stima della direzione d'apertura del FTSE MIB dai movimenti che l'Europa non ha ancora "visto"."""
    by = {m["s"]: m for m in mac}
    why: list[str] = []
    parts: list[float] = []

    # 1) Wall Street dopo la chiusura europea di ieri
    us_after = None
    sp = chart("^GSPC", "5d", "5m")
    mib = chart("FTSEMIB.MI", "5d", "5m")
    if sp and mib and sp["t"] and mib["t"]:
        eu_close_ts = mib["t"][-1]
        same_day = abs(sp["t"][-1] - eu_close_ts) < 12 * 3600
        p0 = _price_at(sp, eu_close_ts)
        if same_day and p0:
            us_after = (sp["c"][-1] / p0 - 1) * 100
            parts.append(0.7 * us_after)
            why.append(f"Dopo la chiusura delle borse europee Wall Street si è mossa del {fmt(us_after)}.")

    # 2) future USA nella notte (dalla chiusura di Wall Street a ora)
    fut = None
    es = chart("ES=F", "5d", "15m")
    if es and sp and sp["t"]:
        p_close = _price_at(es, sp["t"][-1] + 300)
        if p_close and es["c"]:
            fut = (es["c"][-1] / p_close - 1) * 100
            parts.append(0.7 * fut)
            why.append(f"Nella notte i future sull'S&P 500 sono a {fmt(fut)} dalla chiusura di Wall Street.")

    # 3) Asia (pesata poco: in parte riflette gia' Wall Street)
    asia = [by[s]["ch"] for s in ("^N225", "^HSI") if s in by and by[s]["ch"] is not None]
    if asia:
        a = sum(asia) / len(asia)
        parts.append(0.15 * a)
        why.append(f"Le borse asiatiche segnano in media {fmt(a)}.")

    gap = sum(parts) if parts else None
    if gap is None:
        label = "Dati insufficienti per una stima"
    elif abs(gap) < 0.25:
        label = "Apertura prevista vicina alla parità"
    elif abs(gap) < 0.6:
        label = "Apertura prevista leggermente " + ("positiva" if gap > 0 else "negativa")
    else:
        label = "Apertura prevista " + ("positiva" if gap > 0 else "negativa")

    vix = by.get("^VIX")
    vix_label = None
    if vix:
        v = vix["c"]
        vix_label = ("mercati calmi" if v < 15 else "nervosismo nella norma" if v < 20
                     else "mercati nervosi: movimenti ampi" if v < 30 else "mercati molto nervosi: possibili movimenti violenti")
        why.append(f"VIX a {v:.1f}: {vix_label}.".replace(".", ",", 1))

    fm = None
    if mib_ta:
        c = mib_ta["c"]
        open_est = c * (1 + (gap or 0) / 100)
        half = (mib_ta.get("atr") or 0) / 2
        fm = {"close": c, "open_est": r4(open_est), "range": [r4(open_est - half), r4(open_est + half)],
              "piv": mib_ta["piv"], "trend": mib_ta["trend"], "rsi": mib_ta["rsi"],
              "sma50": mib_ta["sma50"], "sma200": mib_ta["sma200"], "atr_pct": mib_ta["atr_pct"]}
    hi = [e for e in events if e["impatto"] == "High"]
    if hi:
        why.append(f"Oggi {len(hi)} dati macro importanti: possibili scossoni agli orari indicati.")
    return {"gap_pct": r4(gap), "label": label, "why": why, "us_after_eu": r4(us_after), "fut_night": r4(fut),
            "vix": {"v": vix["c"], "label": vix_label} if vix else None, "ftsemib": fm}


def fmt(x: float) -> str:
    return ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.2f}".replace(".", ",") + "%"

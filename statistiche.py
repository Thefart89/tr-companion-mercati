"""Statistiche storiche per gli scenari degli avvisi veloci (avvisi/script).

    python statistiche.py [--out data]      -> data/statistiche.json

Per ogni strumento sorvegliato (e per classe: azioni italiane, USA, materie prime...) misura cosa e' successo
DOPO situazioni simili a quelle che fanno scattare un avviso:
- giornata: il prezzo arriva a k volte il movimento tipico (ATR 14 gg) rispetto alla chiusura di ieri (k = 1, 1,5, 2;
  barre da 1 ora, 2 anni). Continua fino alla chiusura? Di quanto? E il giorno dopo?
- scatto: movimento in 30 minuti >= 0,6 ATR (barre da 15 min, 60 giorni: pochi casi, solo per classe).
- tendenza: stesse regole dello script (chiusura < media 20 < media 50, 10 gg oltre 2,5 ATR, 4 punti peggio
  dell'indice; 5 anni giornalieri): 5 e 10 sedute dopo?
- avverso: in quanti giorni il prezzo va contro di d volte l'ATR (d = 0,5..2) rispetto alla chiusura di ieri.
- tecnici (avvisi tecnici sulle posizioni, 5 anni giornalieri): RSI 14 sotto 30 / sopra 70, chiusura che rompe la
  media a 50 giorni, nuovo minimo / massimo di 6 mesi. "mov" = 5 sedute dopo, "dopo" = 10 sedute dopo, nel verso
  del segnale (positivo = il prezzo ha continuato nello stesso verso).
Solo dati pubblici di mercato: nessun dato personale.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import figure
from fonti import charts, rome

HERE = Path(__file__).parent
MONDO = ["BZ=F", "CL=F", "GC=F", "SI=F", "NG=F", "ES=F", "NQ=F", "FTSEMIB.MI", "^STOXX50E", "^GDAXI", "^GSPC",
         "EURUSD=X", "BTC-USD", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]
KS = (1.0, 1.5, 2.0)
DS = (0.5, 1.0, 1.5, 2.0)


def classe(s: str) -> str:
    if s in ("ES=F", "NQ=F") or s.startswith("^") or s == "FTSEMIB.MI":
        return "indici"
    if s.endswith("=F"):
        return "materie"
    if s.endswith("=X"):
        return "valute"
    if s.endswith("-USD"):
        return "cripto"
    if s.endswith(".MI"):
        return "azioni_it"
    if "." in s:
        return "azioni_eu"
    return "azioni_usa"


def indice(s: str) -> str | None:
    c = classe(s)
    return {"azioni_it": "FTSEMIB.MI", "azioni_eu": "^STOXX50E", "azioni_usa": "^GSPC"}.get(c)


def atr_serie(d: dict) -> list[float | None]:
    """ATR % a 14 giorni calcolato fino al giorno PRIMA di ogni indice (quello noto al mattino)."""
    h, l, c = d["h"], d["l"], d["c"]
    out = [None] * len(c)
    for i in range(15, len(c)):
        tr = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) / c[k - 1] * 100 for k in range(i - 14, i)]
        out[i] = sum(tr) / len(tr)
    return out


def r(x, n=2):
    return None if x is None else round(x, n)


def riassumi(casi: list[dict]) -> dict:
    """casi: {mov (nel verso), dopo (nel verso, giorno dopo, facoltativo)}"""
    if not casi:
        return {"n": 0}
    cont = [c for c in casi if c["mov"] > 0]
    rev = [c for c in casi if c["mov"] <= 0]
    out = {"n": len(casi), "cont": r(len(cont) / len(casi) * 100, 0),
           "m_cont": r(sum(c["mov"] for c in cont) / len(cont)) if cont else None,
           "m_rev": r(sum(c["mov"] for c in rev) / len(rev)) if rev else None,
           "media": r(sum(c["mov"] for c in casi) / len(casi))}
    nx = [c["dopo"] for c in casi if c.get("dopo") is not None]
    if nx:
        out["dopo"] = r(sum(1 for x in nx if x > 0) / len(nx) * 100, 0)
        out["m_dopo"] = r(sum(nx) / len(nx))
    return out


def casi_giornata(s, D, H) -> dict:
    d, h = D.get(s), H.get(s)
    if not d or not h or len(d["c"]) < 60:
        return {}
    atr = atr_serie(d)
    idx = {rome(t): i for i, t in enumerate(d["t"])}
    bars = defaultdict(list)
    for t, c in zip(h["t"], h["c"]):
        bars[rome(t)].append(c)
    out = {k: [] for k in KS}
    for day, bb in bars.items():
        i = idx.get(day)
        if not i or i < 16 or not atr[i] or len(bb) < 3:
            continue
        pc, close = d["c"][i - 1], d["c"][i]
        nxt = d["c"][i + 1] if i + 1 < len(d["c"]) else None
        for k in KS:
            for j, c in enumerate(bb[:-1]):          # non l'ultima barra: serve tempo per vedere il seguito
                m0 = (c / pc - 1) * 100
                if abs(m0) >= k * atr[i]:
                    sgn = 1 if m0 > 0 else -1
                    out[k].append({"mov": ((close / pc - 1) * 100 - m0) * sgn,
                                   "dopo": ((nxt / close - 1) * 100 * sgn) if nxt else None})
                    break
    return out


def casi_scatto(s, D, Q) -> list:
    d, q = D.get(s), Q.get(s)
    if not d or not q:
        return []
    atr = atr_serie(d)
    idx = {rome(t): i for i, t in enumerate(d["t"])}
    bars = defaultdict(list)
    for t, c in zip(q["t"], q["c"]):
        bars[rome(t)].append((t, c))
    out = []
    for day, bb in bars.items():
        i = idx.get(day)
        if not i or not atr[i]:
            continue
        close = d["c"][i]
        for j in range(2, len(bb) - 1):
            if bb[j][0] - bb[j - 2][0] > 45 * 60:
                continue
            f = (bb[j][1] / bb[j - 2][1] - 1) * 100
            if abs(f) >= 0.6 * atr[i]:
                sgn = 1 if f > 0 else -1
                out.append({"mov": (close / bb[j][1] - 1) * 100 * sgn})
                break                                   # un caso per giorno
    return out


def casi_tendenza(s, D5) -> dict:
    d = D5.get(s)
    if not d or len(d["c"]) < 80:
        return {"giu": [], "su": []}
    c, atr = d["c"], atr_serie(d)
    ri = indice(s)
    rc = D5.get(ri) if ri and ri != s else None
    ridx = {t: k for k, t in enumerate(rc["t"])} if rc else {}
    out = {"giu": [], "su": []}
    last = {"giu": -99, "su": -99}
    for i in range(60, len(c) - 10):
        a = atr[i + 1] if i + 1 < len(atr) else None        # ATR noto il giorno dopo il segnale
        if not a:
            continue
        m20, m50 = sum(c[i - 19:i + 1]) / 20, sum(c[i - 49:i + 1]) / 50
        ch10 = (c[i] / c[i - 10] - 1) * 100
        rel = None
        if rc:
            k = ridx.get(d["t"][i])
            if k and k >= 10:
                rel = ch10 - (rc["c"][k] / rc["c"][k - 10] - 1) * 100
        for verso, ok, sgn in (("giu", c[i] < m20 < m50 and ch10 <= -2.5 * a and (rel is None or rel <= -4), -1),
                               ("su", c[i] > m20 > m50 and ch10 >= 2.5 * a and (rel is None or rel >= 4), 1)):
            if ok and i - last[verso] > 5:
                last[verso] = i
                out[verso].append({"mov": (c[i + 10] / c[i] - 1) * 100 * sgn, "dopo": (c[i + 5] / c[i] - 1) * 100 * sgn})
    return out


def rsi_serie(c: list[float], n: int = 14) -> list[float | None]:
    """RSI di Wilder a 14 giorni (come il Worker)."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    p = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(p[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + p[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


TECNICI = ("rsi30", "rsi70", "m50giu", "m50su", "min6m", "max6m")


def casi_tecnici(s, D5) -> dict:
    d = D5.get(s)
    out = {k: [] for k in TECNICI}
    if not d or len(d["c"]) < 200:
        return out
    c, h, l = d["c"], d["h"], d["l"]
    rsi = rsi_serie(c)
    last = {k: -99 for k in TECNICI}
    for i in range(130, len(c) - 10):
        m50, m50p = sum(c[i - 49:i + 1]) / 50, sum(c[i - 50:i]) / 50
        segnali = (("rsi30", rsi[i] is not None and rsi[i - 1] is not None and rsi[i] < 30 <= rsi[i - 1], -1),
                   ("rsi70", rsi[i] is not None and rsi[i - 1] is not None and rsi[i] > 70 >= rsi[i - 1], 1),
                   ("m50giu", c[i] < m50 and c[i - 1] >= m50p, -1),
                   ("m50su", c[i] > m50 and c[i - 1] <= m50p, 1),
                   ("min6m", c[i] < min(l[i - 126:i]), -1),
                   ("max6m", c[i] > max(h[i - 126:i]), 1))
        for k, ok, sgn in segnali:
            if ok and i - last[k] > 5:
                last[k] = i
                out[k].append({"mov": (c[i + 5] / c[i] - 1) * 100 * sgn, "dopo": (c[i + 10] / c[i] - 1) * 100 * sgn})
    return out


def avverso(s, D) -> dict:
    d = D.get(s)
    if not d or len(d["c"]) < 60:
        return {}
    atr = atr_serie(d)
    giu = {x: 0 for x in DS}
    su = {x: 0 for x in DS}
    n = 0
    for i in range(16, len(d["c"])):
        if not atr[i]:
            continue
        n += 1
        pc = d["c"][i - 1]
        for x in DS:
            giu[x] += (d["l"][i] / pc - 1) * 100 <= -x * atr[i]
            su[x] += (d["h"][i] / pc - 1) * 100 >= x * atr[i]
    return {"n": n, **{str(x): [r(giu[x] / n * 100, 1), r(su[x] / n * 100, 1)] for x in DS}}


def run(out: Path) -> None:
    t0 = time.time()
    uni = json.loads((HERE / "universo.json").read_text(encoding="utf-8"))
    syms = list(dict.fromkeys(MONDO + [m["s"] for m in uni["FTSEMIB"]["members"]]))
    D2 = charts(syms, "2y", "1d")
    H = charts(syms, "2y", "1h")
    Q = charts(syms, "60d", "15m")
    D5 = charts(syms + ["^STOXX50E"], "5y", "1d")
    print(f"Serie: {len(D2)} giornaliere, {len(H)} orarie, {len(Q)} da 15 min, {len(D5)} a 5 anni ({time.time() - t0:.0f}s)")
    simboli, per_classe = {}, defaultdict(lambda: {"giornata": {k: [] for k in KS}, "scatto": [], "tendenza": {"giu": [], "su": []},
                                                  "tecnici": {k: [] for k in TECNICI}})
    for s in syms:
        cl = classe(s)
        g = casi_giornata(s, D2, H)
        sc = casi_scatto(s, D2, Q)
        te = casi_tendenza(s, D5)
        av = avverso(s, D2)
        tc = casi_tecnici(s, D5)
        for k in TECNICI:
            per_classe[cl]["tecnici"][k] += tc[k]
        for k in KS:
            per_classe[cl]["giornata"][k] += g.get(k, [])
        per_classe[cl]["scatto"] += sc
        for v in ("giu", "su"):
            per_classe[cl]["tendenza"][v] += te[v]
        simboli[s] = {"classe": cl, "giornata": {str(k): riassumi(g.get(k, [])) for k in KS}, "scatto": riassumi(sc),
                      "tendenza": {v: riassumi(te[v]) for v in ("giu", "su")}, "avverso": av,
                      "tecnici": {k: riassumi(tc[k]) for k in TECNICI}}
    classi = {cl: {"giornata": {str(k): riassumi(x["giornata"][k]) for k in KS}, "scatto": riassumi(x["scatto"]),
                   "tendenza": {v: riassumi(x["tendenza"][v]) for v in ("giu", "su")},
                   "tecnici": {k: riassumi(x["tecnici"][k]) for k in TECNICI}}
              for cl, x in per_classe.items()}
    # figure grafiche: prova storica su tutti i titoli dei tre indici (5 anni, giornaliero)
    gruppo = {m["s"]: g for g, v in uni.items() if isinstance(v, dict) and "members" in v for m in v["members"]}
    t1 = time.time()
    DF = {**{s: D5[s] for s in gruppo if s in D5}, **charts([s for s in gruppo if s not in D5], "5y", "1d")}
    fig = figure.misura({s: d for s, d in DF.items() if d.get("c")}, gruppo)
    print(f"Figure grafiche: {fig['tutte']['n'] if fig.get('tutte') else 0} rotture su {len(DF)} titoli ({time.time() - t1:.0f}s)")
    out.mkdir(parents=True, exist_ok=True)
    (out / "statistiche.json").write_text(json.dumps({
        "generated": time.time(), "periodo": {"giornata": "2 anni, barre da 1 ora", "scatto": "60 giorni, barre da 15 minuti",
                                             "tendenza": "5 anni, dati giornalieri", "avverso": "2 anni, dati giornalieri",
                                             "tecnici": "5 anni, dati giornalieri",
                                             "figure": "5 anni, dati giornalieri, titoli di FTSE MIB, Euro Stoxx 50 e S&P 500"},
        "classi": classi, "simboli": simboli, "figure": fig}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Fatto: {len(simboli)} strumenti in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = sys.argv[1:]
    run(Path(a[a.index("--out") + 1]) if "--out" in a else HERE / "data")

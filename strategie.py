"""Strategie con un vantaggio statistico che regge sui dati (prove del 25/11 su 30-55 anni di dati giornalieri):

1. RIMBALZO DI BREVE SUGLI INDICI ("mean reversion" lato rialzo). Regola fissata PRIMA della prova (dalla letteratura):
   indice sopra la sua media a 200 sedute e RSI a 2 sedute sotto 10 alla chiusura -> si entra all'APERTURA del giorno dopo;
   si esce all'apertura del giorno dopo la prima chiusura sopra la media a 5 sedute (al massimo dopo 10 sedute).
   Su 11 indici dal 1971: 69% di operazioni positive contro 57% di giorni presi a caso, +0,29% contro +0,17% a operazione
   (~4 sedute). Stabile con RSI a 2-3 sedute e soglie 5-20, in ogni periodo (1990-2004, 2005-2015, 2016-2026) e su ogni
   indice (il FTSE MIB e' il piu' debole). Rischio: rare discese forti durante l'operazione (crolli del 1987, 2008, 2020).
2. TENDENZA DI FONDO (trend following): sopra / sotto la media a 200 sedute. Stare fuori sotto la media ha ridotto i
   crolli peggiori di ~20 punti in 16 strumenti su 18, ma ha reso 2-3 punti l'anno in meno di "compra e tieni": protegge,
   non fa guadagnare di piu'. Qui e' solo un'indicazione.

    python strategie.py [--out data]   -> data/strategie.json

Nessun consiglio d'investimento: segnali di una regola fissa con la loro statistica. Solo dati pubblici, nessun dato personale.
"""
from __future__ import annotations

import json
import statistics as stt
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fonti import get, rome
import turbo_sim
from tecnica import session_complete

HERE = Path(__file__).parent
INDICI = {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^DJI": "Dow Jones", "^GDAXI": "DAX", "^STOXX50E": "Euro Stoxx 50",
          "FTSEMIB.MI": "FTSE MIB", "^FCHI": "CAC 40"}
K, SOGLIA, MAX_SED = 2, 10, 10
INIZIO_VERIFICA = "2026-11-25"       # da qui in poi le operazioni contano come "verifica dal vivo"


def serie(s: str) -> dict | None:
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?period1=0&period2={int(time.time())}"
         "&interval=1d&includePrePost=false")
    try:
        r = json.loads(get(u))["chart"]["result"][0]
    except Exception:
        return None
    q = r["indicators"]["quote"][0]
    out = {"meta": r.get("meta", {}), "t": [], "o": [], "h": [], "l": [], "c": []}
    for i, t in enumerate(r.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        out["t"].append(t)
        out["c"].append(c)
        for k, src in (("o", "open"), ("h", "high"), ("l", "low")):
            x = q[src][i]
            out[k].append(x if x is not None else c)
    return out if len(out["c"]) > 400 else None


def sma_s(c, n):
    out, s = [None] * len(c), 0.0
    for i, x in enumerate(c):
        s += x
        if i >= n:
            s -= c[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi_s(c, k):
    """RSI di Wilder + medie di rialzi/ribassi (servono per dire a che prezzo scatterebbe il segnale)."""
    out, AG, AL = [None] * len(c), [None] * len(c), [None] * len(c)
    ag = al = 0.0
    for i in range(1, len(c)):
        g, l = max(c[i] - c[i - 1], 0), max(c[i - 1] - c[i], 0)
        if i <= k:
            ag += g / k
            al += l / k
        else:
            ag, al = (ag * (k - 1) + g) / k, (al * (k - 1) + l) / k
        if i >= k:
            out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
            AG[i], AL[i] = ag, al
    return out, AG, AL


def operazioni(d: dict) -> tuple[list[dict], dict | None]:
    """Tutte le operazioni della regola (ingresso e uscita alle aperture vere) e quella eventualmente ancora aperta."""
    c, o, l = d["c"], d["o"], d["l"]
    r, _, _ = rsi_s(c, K)
    m200, m5 = sma_s(c, 200), sma_s(c, 5)
    n, ops, aperta, i = len(c), [], None, 200
    while i < n:
        if r[i] is not None and r[i] < SOGLIA and c[i] > m200[i]:
            if i + 1 >= n:                                       # segnale all'ultima chiusura: si entra domani
                aperta = {"segnale": i, "ingresso": None}
                break
            if o[i + 1] == c[i]:                                 # apertura non vera (dati vecchi): non si conta
                i += 1
                continue
            e, j = o[i + 1], i + 1
            while j < min(n - 1, i + MAX_SED) and c[j] <= m5[j]:
                j += 1
            esce = c[j] > m5[j] or j >= i + MAX_SED
            if j + 1 >= n or not esce:                           # ancora in corso (o esce all'apertura di domani)
                aperta = {"segnale": i, "ingresso": i + 1, "e": e, "esce_domani": esce, "fino": j}
                break
            u = o[j + 1]
            ops.append({"segnale": i, "ingresso": i + 1, "uscita": j + 1, "e": e, "u": u, "ris": u / e - 1,
                        "sed": j + 1 - (i + 1), "mae": min(l[i + 1:j + 2]) / e - 1})
            i = j + 1
        else:
            i += 1
    return ops, aperta


def riassunto(ops: list[dict], base: tuple[float, float] | None = None) -> dict | None:
    if not ops:
        return None
    x = {"n": len(ops), "pos": round(sum(o["ris"] > 0 for o in ops) / len(ops) * 100, 1),
         "media": round(stt.mean(o["ris"] for o in ops) * 100, 2), "sed": round(stt.mean(o["sed"] for o in ops), 1),
         "peggiore": round(min(o["ris"] for o in ops) * 100, 1)}
    if base:
        x["caso_media"], x["caso_pos"] = round(base[0] * 100, 2), round(base[1] * 100, 1)
    return x


def a_caso(d: dict, sed: int = 4) -> tuple[float, float]:
    """Stessa durata, ingresso all'apertura di un giorno qualsiasi con l'indice sopra la media a 200."""
    c, o = d["c"], d["o"]
    m = sma_s(c, 200)
    R = [o[i + 1 + sed] / o[i + 1] - 1 for i in range(200, len(c) - sed - 2) if c[i] > m[i] and o[i + 1] != c[i]]
    return (stt.mean(R), sum(v > 0 for v in R) / len(R)) if R else (0.0, 0.0)


def con_leva(D: dict, OPS: dict, tassi: dict, L: float, fs: float | None = None, solo_future: bool = False, dal: str | None = None,
             solo_usa: bool = False) -> dict | None:
    """Simulazione del turbo (turbo_sim): strike che sale ogni giorno di calendario con il tasso storico + spread,
    barriera sul minimo dal giorno d'ingresso, margine 0,5%. solo_future: indici USA con la barriera sul future (24 ore)."""
    vecchio = turbo_sim.FS
    if fs is not None:
        turbo_sim.FS = fs
    R = []
    try:
        for s, ops in OPS.items():
            if (solo_future or solo_usa) and s not in turbo_sim.FUTURE:
                continue
            fl = turbo_sim.minimi_future(D[s], D.get(turbo_sim.FUTURE[s])) if solo_future else None
            for op in ops:
                if dal and turbo_sim.giorno(D[s]["t"][op["ingresso"]]) < dal:
                    continue
                R.append(turbo_sim.simula(D[s], op, L, tassi["EUR" if s in turbo_sim.EURO else "USD"], turbo_sim.BUF, fl))
    finally:
        turbo_sim.FS = vecchio
    return turbo_sim.riassumi(R, L)


def trend_prova(d: dict) -> dict:
    """Compra e tieni contro 'dentro solo sopra la media a 200' (dal giorno dopo, 0,1% a ogni cambio)."""
    c = d["c"]
    m = sma_s(c, 200)

    def st(r):
        eq = pk = 1.0
        mdd = 0.0
        for x in r:
            eq *= 1 + x
            pk = max(pk, eq)
            mdd = min(mdd, eq / pk - 1)
        return round((eq ** (252 / len(r)) - 1) * 100, 1), round(mdd * 100)
    rb, rt = [], []
    for i in range(201, len(c) - 1):
        x = c[i + 1] / c[i] - 1
        rb.append(x)
        p, p0 = c[i - 1] > m[i - 1], c[i - 2] > m[i - 2] if m[i - 2] else False
        rt.append((x if p else 0) - (0.001 if p != p0 else 0))
    (a, b), (t1, t2) = st(rb), st(rt)
    return {"anni": round(len(rb) / 252), "tieni_rend": a, "tieni_calo": b, "trend_rend": t1, "trend_calo": t2}


def stato(s: str, d: dict, now: float) -> dict:
    if not session_complete(d["t"][-1], d.get("meta") or {}, now):      # seduta in corso: si guarda solo l'ultima chiusa
        d = {k: (v[:-1] if isinstance(v, list) else v) for k, v in d.items()}
    c = d["c"]
    n = len(c)
    r, AG, AL = rsi_s(c, K)
    m200, m5 = sma_s(c, 200), sma_s(c, 5)
    ops, aperta = operazioni(d)
    x = {"s": s, "nome": INDICI[s], "d": rome(d["t"][-1]), "c": round(c[-1], 2), "m200": round(m200[-1], 2), "m5": round(m5[-1], 2),
         "rsi2": round(r[-1], 1), "sopra200": c[-1] > m200[-1], "dist200": round((c[-1] / m200[-1] - 1) * 100, 1)}
    # a che chiusura di domani scatterebbe il segnale (RSI2 < 10): serve un ribasso d > 9*ag - al (formula di Wilder con k=2)
    need = 9 * AG[-1] - AL[-1]
    soglia = c[-1] - max(0.0, need)
    x["scatta_sotto"] = round(soglia, 2) if soglia > m200[-1] else None
    x["scatta_pct"] = round((soglia / c[-1] - 1) * 100, 1)
    if aperta and aperta["ingresso"] is None:
        x["stato"] = "segnale"
    elif aperta:
        i0 = aperta["ingresso"]
        x.update(stato="uscita" if aperta["esce_domani"] else "in corso", ingresso_d=rome(d["t"][i0]), ingresso=round(aperta["e"], 2),
                 sedute=n - 1 - i0 + 1, ora=round((c[-1] / aperta["e"] - 1) * 100, 2))
    else:
        x["stato"] = "nessuno"
    if aperta:
        x["segnale_d"] = rome(d["t"][aperta["segnale"]])
    x["prova"] = riassunto(ops, a_caso(d, 4))
    x["trend"] = trend_prova(d)
    vive = [o for o in ops if rome(d["t"][o["segnale"]]) >= INIZIO_VERIFICA]
    x["dal_vivo"] = [{"segnale": rome(d["t"][o["segnale"]]), "e": round(o["e"], 2), "u": round(o["u"], 2), "ris": round(o["ris"] * 100, 2),
                      "sed": o["sed"]} for o in vive]
    x["_ops"] = ops
    return x


def run(out: Path) -> None:
    now = time.time()
    with ThreadPoolExecutor(4) as ex:
        D = dict(zip(INDICI, ex.map(serie, INDICI)))
    with ThreadPoolExecutor(4) as ex:
        X = dict(zip(["^IRX"] + list(turbo_sim.FUTURE.values()), ex.map(serie, ["^IRX"] + list(turbo_sim.FUTURE.values()))))
    usd = turbo_sim.tassi_usd(X.get("^IRX"))
    tassi = {"USD": turbo_sim.Tassi(usd), "EUR": turbo_sim.Tassi(turbo_sim.tassi_eur(get), usd)}
    righe = [stato(s, d, now) for s, d in D.items() if d]
    OPS = {x["s"]: x["_ops"] for x in righe}
    DD = {**{s: d for s, d in D.items() if d}, **{s: d for s, d in X.items() if d}}
    tutte = [o for x in righe for o in x.pop("_ops")]
    base = [a_caso(D[x["s"]], 4) for x in righe]
    res = {"generated": now, "regola": {"k": K, "soglia": SOGLIA, "max_sedute": MAX_SED, "inizio_verifica": INIZIO_VERIFICA},
           "indici": righe,
           "prova": riassunto(tutte, (stt.mean(b[0] for b in base), stt.mean(b[1] for b in base))),
           "leva": [x for x in (con_leva(DD, OPS, tassi, L) for L in (3, 5, 8, 10)) if x],
           "leva_costosa": [x for x in (con_leva(DD, OPS, tassi, L, fs=0.08) for L in (3, 5, 8, 10)) if x],
           "usa_dal_2000": {"indice": [con_leva(DD, OPS, tassi, L, dal="2000-10-01", solo_usa=True) for L in (5, 8, 10)],
                            "future": [con_leva(DD, OPS, tassi, L, solo_future=True, dal="2000-10-01") for L in (5, 8, 10)]},
           "sim": {"fs": turbo_sim.FS, "buf": turbo_sim.BUF, "costi": turbo_sim.COSTI}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "strategie.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Strategie: {len(righe)} indici, {len(tutte)} operazioni storiche; segnali: "
          + (", ".join(f"{x['nome']} {x['stato']}" for x in righe if x["stato"] != "nessuno") or "nessuno"))


if __name__ == "__main__":
    a = sys.argv[1:]
    run(Path(a[a.index("--out") + 1]) if "--out" in a else HERE / "data")

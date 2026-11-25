"""Simulazione di un Turbo Open-End Long (tipo Vontobel) sui dati giornalieri OHLC, con le regole prudenti:

- strike d'ingresso K0 = S0 * (1 - 1/L), con S0 = apertura del giorno d'ingresso;
- lo strike sale a ogni seduta dei costi di finanziamento sui GIORNI DI CALENDARIO (Actual/360):
  K_t = K_{t-1} * (1 + (r + FS) * n / 360), n = giorni tra le due sedute (venerdi' -> lunedi' = 3);
  r = tasso storico (USA: T-bill a 13 settimane ^IRX dal 1970; euro: EONIA 1999-2019 poi EUR STR, BCE; prima del
  1999 per gli indici europei si usa il tasso USA, che in quegli anni era simile); FS = spread dell'emittente (4%);
- barriera = strike, osservata sul MINIMO di ogni seduta GIA' DAL GIORNO D'INGRESSO; il giorno d'uscita (all'apertura)
  conta solo l'apertura (gap); se nella stessa seduta c'e' sia il tocco sia il resto, vince il knock-out;
- margine di sicurezza BUF sopra lo strike (premio dell'emittente, leva non esatta): knock-out se minimo <= K*(1+BUF);
- "quasi knock-out": distanza minima toccata dalla barriera (sotto l'1% lo spread del market maker esplode);
- per i turbo sul FUTURE (frequenti sugli indici USA) la barriera e' osservata quasi 24 ore: si usa il minimo del future
  (ES=F, NQ=F, YM=F) riportato all'indice con il rapporto delle chiusure del giorno prima.
I dividendi sono trascurati (operazioni di pochi giorni: indice e strike scendono insieme).
"""
from __future__ import annotations

import datetime as dt
import statistics as stt

FS, BUF, COSTI = 0.04, 0.005, 0.005     # spread di finanziamento, margine sulla barriera, spread + 2 commissioni (~0,5%)
FUTURE = {"^GSPC": "ES=F", "^NDX": "NQ=F", "^DJI": "YM=F"}
EURO = {"^GDAXI", "^STOXX50E", "FTSEMIB.MI", "^FCHI"}


def giorno(t: int) -> str:
    return dt.datetime.utcfromtimestamp(t + 7200).strftime("%Y-%m-%d")


def tassi_usd(irx: dict | None) -> dict:
    """{data: tasso decimale} dal T-bill a 13 settimane (Yahoo ^IRX, in punti percentuali)."""
    if not irx:
        return {}
    return {giorno(t): c / 100 for t, c in zip(irx["t"], irx["c"]) if c is not None}


def tassi_eur(get) -> dict:
    """EONIA (1999-2019) e EUR STR (dal 2019) dalla BCE. get(url) -> bytes. Se la BCE non risponde: vuoto (si usa l'USD)."""
    out = {}
    for key in ("EON/D.EONIA_TO.RATE", "EST/B.EU000A2X2A25.WT"):
        try:
            txt = get(f"https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata&detail=dataonly").decode()
        except Exception:
            continue
        for riga in txt.splitlines()[1:]:
            p = riga.split(",")
            try:
                out[p[4]] = float(p[5]) / 100
            except (IndexError, ValueError):
                pass
    return out


class Tassi:
    """Tasso del giorno (o dell'ultimo giorno disponibile prima)."""
    def __init__(self, *serie: dict, fisso: float = 0.03):
        self.d = {}
        for s in reversed(serie):            # la prima serie ha la precedenza
            self.d.update(s)
        self.k = sorted(self.d)
        self.fisso = fisso

    def __call__(self, data: str) -> float:
        import bisect
        i = bisect.bisect_right(self.k, data) - 1
        return self.d[self.k[i]] if i >= 0 else self.fisso


def minimi_future(d: dict, f: dict | None) -> dict:
    """{data: minimo del future riportato all'indice} con il rapporto delle chiusure del giorno prima."""
    if not f:
        return {}
    fc = {giorno(t): (l, c) for t, l, c in zip(f["t"], f["l"], f["c"])}
    out, date = {}, [giorno(t) for t in d["t"]]
    for i in range(1, len(date)):
        a, b = fc.get(date[i - 1]), fc.get(date[i])
        if a and b and a[1] and b[0]:
            out[date[i]] = d["c"][i - 1] * b[0] / a[1]
    return out


def simula(d: dict, op: dict, L: float, tasso, buf: float = BUF, fut_low: dict | None = None) -> dict | None:
    """Un'operazione: ingresso all'apertura di op['ingresso'], uscita all'apertura di op['uscita'].
    Restituisce {ris (frazione, -1 = knock-out), ko, vicino (distanza minima dalla barriera, frazione)} o None se mancano dati."""
    o, l, t = d["o"], d["l"], d["t"]
    a, b = op["ingresso"], op["uscita"]
    date = [giorno(x) for x in t[a:b + 1]]
    S0 = o[a]
    K = S0 * (1 - 1 / L)
    C0 = S0 - K
    vicino = 1.0
    for k, i in enumerate(range(a, b + 1)):
        if k:
            n = (dt.date.fromisoformat(date[k]) - dt.date.fromisoformat(date[k - 1])).days
            K *= 1 + (tasso(date[k - 1]) + FS) * n / 360
        barr = K * (1 + buf)
        if i < b:
            lo = l[i]
            if fut_low is not None:
                if date[k] not in fut_low:
                    return None                  # periodo senza dati del future: non si conta
                lo = min(lo, fut_low[date[k]])
        else:
            lo = o[i]                            # giorno d'uscita: conta solo l'apertura
        vicino = min(vicino, lo / K - 1)
        if lo <= barr:
            return {"ris": -1.0, "ko": True, "vicino": vicino}
    return {"ris": (o[b] - K) / C0 - 1 - COSTI, "ko": False, "vicino": vicino}


def riassumi(R: list[dict], L: float) -> dict | None:
    R = [x for x in R if x]
    if not R:
        return None
    v = [x["ris"] * 100 for x in R]
    return {"leva": L, "n": len(R), "media": round(stt.mean(v), 2), "pos": round(sum(x > 0 for x in v) / len(v) * 100, 1),
            "ko": sum(x["ko"] for x in R), "quasi": sum((not x["ko"]) and x["vicino"] < 0.01 for x in R),
            "mediana": round(stt.median(v), 2)}

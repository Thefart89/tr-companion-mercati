"""Radar dei titoli piu' forti ("momento"): ogni mattina, per FTSE MIB, Euro Stoxx 50 e S&P 500, i titoli saliti di piu'
negli ultimi 12 mesi SENZA contare l'ultimo mese (la misura classica della ricerca finanziaria), con la prova storica.

    python radar.py [--out data]   -> data/radar.json (classifica e prova) e data/radar_storico.json (verifica dal vivo)

Perche' questo e non i segnali tecnici (23/11): provati "senza sbirciare il futuro" sugli ultimi 2 anni (~600 titoli),
RSI 30/70, media a 50 giorni, minimi/massimi di 6 mesi, tendenza di 2 settimane, rimbalzo dei peggiori della settimana o
del mese avevano esito come lanciare una moneta (49-52%), anche scegliendo solo quelli con buone statistiche passate sullo
stesso titolo. Il "momento" a 6-12 mesi invece ha battuto la mediana del proprio indice nella maggior parte degli anni
(+1/+4 punti al mese in media), con mesi e anni in perdita (es. Euro Stoxx 2026).
Misura usata: rendimento a 21 sedute (circa un mese) RISPETTO ALLA MEDIANA del proprio gruppo: "piu' forte degli altri",
non "sale". Se tutto il mercato scende, di solito scendono anche loro.
Non e' un consiglio d'investimento. Solo dati pubblici di mercato, nessun dato personale.
"""
from __future__ import annotations

import json
import statistics as stt
import sys
import time
from collections import defaultdict
from pathlib import Path

from fonti import charts

HERE = Path(__file__).parent
GRUPPI = {"FTSEMIB": "Italia (FTSE MIB)", "SX5E": "Europa (Euro Stoxx 50)", "SPX": "USA (S&P 500)"}
MOSTRA = {"FTSEMIB": 5, "SX5E": 5, "SPX": 10}
ORIZ, LUNGO, SALTA = 21, 252, 21        # un mese dopo; 12 mesi escluso l'ultimo


def r(x, n=1):
    return None if x is None else round(x, n)


def allinea(L: list[str], D: dict) -> tuple[dict, list[int]]:
    """Chiusure per giorno (numero di giorni dal 1970) e giorni in cui c'e' almeno l'80% dei titoli."""
    per = defaultdict(dict)
    for s in L:
        d = D.get(s)
        if not d:
            continue
        for t, c in zip(d["t"], d["c"]):
            per[int((t + 7200) // 86400)][s] = c
    giorni = sorted(g for g, x in per.items() if len(x) >= len(L) * 0.8)
    return per, giorni


def forza(per, giorni, k, s) -> float | None:
    if k - LUNGO < 0:
        return None
    a, b = per[giorni[k - LUNGO]].get(s), per[giorni[k - SALTA]].get(s)
    return (b / a - 1) * 100 if a and b else None


def classifica(per, giorni, k) -> list[tuple[str, float]]:
    f = {s: forza(per, giorni, k, s) for s in per[giorni[k]]}
    return sorted(((s, x) for s, x in f.items() if x is not None), key=lambda z: -z[1])


def scarti(per, giorni, k, scelti) -> list[float] | None:
    """Rendimento a ORIZ sedute dei titoli scelti meno la mediana del gruppo (in punti %)."""
    if k + ORIZ >= len(giorni):
        return None
    g0, g1 = per[giorni[k]], per[giorni[k + ORIZ]]
    fut = {s: (g1[s] / g0[s] - 1) * 100 for s in g0 if s in g1}
    if len(fut) < 10:
        return None
    med = stt.median(fut.values())
    return [fut[s] - med for s in scelti if s in fut]


def prova_storica(per, giorni) -> dict:
    """Ogni mese degli ultimi 3 anni: il 10% piu' forte di allora, un mese dopo, rispetto alla mediana."""
    tutti, mesi, anni = [], [], defaultdict(list)
    for k in range(max(LUNGO + 5, len(giorni) - 756), len(giorni) - ORIZ, ORIZ):
        cl = classifica(per, giorni, k)
        if len(cl) < 20:
            continue
        scelti = [s for s, _ in cl[:max(3, len(cl) // 10)]]
        sc = scarti(per, giorni, k, scelti)
        if not sc:
            continue
        tutti += sc
        mesi.append(stt.mean(sc))
        anni[time.strftime("%Y", time.gmtime(giorni[k] * 86400))].append(stt.mean(sc))
    if not tutti:
        return {}
    return {"idee": len(tutti), "batte": round(sum(1 for x in tutti if x > 0) / len(tutti) * 100), "media": r(stt.mean(tutti)),
            "mediana": r(stt.median(tutti)), "mesi": len(mesi), "mesi_buoni": round(sum(1 for x in mesi if x > 0) / len(mesi) * 100),
            "peggior_mese": r(min(mesi)), "miglior_mese": r(max(mesi)),
            "anni": {a: r(stt.mean(v)) for a, v in sorted(anni.items())}}


def verifica(storico: dict, gruppi_dati: dict) -> None:
    for x in storico["liste"]:
        if x.get("esito") or x["gruppo"] not in gruppi_dati:
            continue
        per, giorni = gruppi_dati[x["gruppo"]]
        if x["giorno"] not in giorni:
            continue
        k = giorni.index(x["giorno"])
        sc = scarti(per, giorni, k, x["scelti"])
        if sc:
            x["esito"] = {"media": r(stt.mean(sc)), "batte": sum(1 for v in sc if v > 0), "n": len(sc)}
    chiuse = [x for x in storico["liste"] if x.get("esito")]
    if chiuse:
        n = sum(x["esito"]["n"] for x in chiuse)
        storico["riepilogo"] = {"liste": len(chiuse), "idee": n, "batte": round(sum(x["esito"]["batte"] for x in chiuse) / n * 100),
                                "media": r(stt.mean(x["esito"]["media"] for x in chiuse)), "dal": chiuse[0]["data"]}


def run(out: Path) -> None:
    t0 = time.time()
    uni = json.loads((HERE / "universo.json").read_text(encoding="utf-8"))
    membri = {g: uni[g]["members"] for g in GRUPPI}
    nomi = {m["s"]: m.get("n") or m["s"] for L in membri.values() for m in L}
    settori = {m["s"]: m.get("sec") for L in membri.values() for m in L}
    D = charts(list(nomi), "5y", "1d", workers=8)
    print(f"Serie a 5 anni: {len(D)} su {len(nomi)} ({time.time() - t0:.0f}s)")
    oggi = int((time.time() + 7200) // 86400)

    pst = out / "radar_storico.json"
    storico = json.loads(pst.read_text(encoding="utf-8")) if pst.exists() else {"liste": []}
    res, gd = {}, {}
    for g, nome in GRUPPI.items():
        per, giorni = allinea([m["s"] for m in membri[g]], D)
        if giorni and giorni[-1] >= oggi:                       # seduta di oggi ancora aperta: si usa l'ultima chiusa
            giorni = [x for x in giorni if x < oggi]
        gd[g] = (per, giorni)
        k = len(giorni) - 1
        cl = classifica(per, giorni, k)
        top = cl[:MOSTRA[g]]
        n10 = max(3, len(cl) // 10)
        righe = []
        for pos, (s, f) in enumerate(top, 1):
            d = D[s]
            c = d["c"]
            hi = max(d["h"][-252:])
            m200 = sum(c[-200:]) / 200 if len(c) >= 200 else None
            righe.append({"s": s, "nome": nomi[s], "settore": settori.get(s), "pos": pos, "forza": r(f),
                          "m1": r((c[-1] / c[-22] - 1) * 100), "m6": r((c[-1] / c[-127] - 1) * 100) if len(c) > 127 else None,
                          "dal_max": r((c[-1] / hi - 1) * 100), "sopra_m200": (c[-1] > m200) if m200 else None,
                          "c": round(c[-1], 4), "cur": d["meta"].get("currency")})
        res[g] = {"nome": nome, "titoli": len(cl), "top10": n10, "idee": righe, "prova": prova_storica(per, giorni),
                  "giorno": giorni[k] if giorni else None}
        # verifica dal vivo: una lista a settimana per gruppo (il 10% piu' forte di quel giorno)
        ult = max((x["giorno"] for x in storico["liste"] if x["gruppo"] == g), default=0)
        if giorni and giorni[k] - ult >= 7:
            storico["liste"].append({"gruppo": g, "giorno": giorni[k], "data": time.strftime("%Y-%m-%d", time.gmtime(giorni[k] * 86400)),
                                     "scelti": [s for s, _ in cl[:n10]]})
        p = res[g]["prova"]
        print(f"{nome}: primi {', '.join(nomi[s] for s, _ in top[:5])} | prova 3 anni: batte {p.get('batte')}% delle volte, "
              f"media {p.get('media')} punti al mese, mesi buoni {p.get('mesi_buoni')}%")
    verifica(storico, gd)
    storico["liste"] = storico["liste"][-200:]
    out.mkdir(parents=True, exist_ok=True)
    data = max((x["giorno"] for x in res.values() if x.get("giorno")), default=None)
    (out / "radar.json").write_text(json.dumps({
        "generated": time.time(), "data": time.strftime("%Y-%m-%d", time.gmtime(data * 86400)) if data else None,
        "oriz": ORIZ, "gruppi": res, "verifica": storico.get("riepilogo")}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pst.write_text(json.dumps(storico, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Fatto in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = sys.argv[1:]
    run(Path(a[a.index("--out") + 1]) if "--out" in a else HERE / "data")

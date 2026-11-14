"""Lavoro giornaliero dei dati di mercato per l'app TR-Companion (gira su GitHub Actions).

    python lavoro.py mattina      tutto: titoli, volumi, notizie, previsioni, commento IA (se c'e' la chiave)
    python lavoro.py sera         dopo la chiusura europea: titoli europei, notizie, verifica della previsione
    opzioni: --no-ia  --out <cartella>  (predefinita: data)
             --se-manca  (mattina: non fa nulla se le previsioni di oggi ci sono gia')

Scrive (pubblici, senza dati personali):
    data/titoli.json    analisi tecnica di ~600 titoli e degli indici
    data/mercato.json   quadro del mattino, notizie, volumi anomali, calendario, commento IA
    data/storico.json   previsioni passate e risultato reale (per misurarne l'affidabilita')
    data/eventi.json    prossimi conti trimestrali e stacchi di dividendo (solo mattina)
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ia
import notizie
import previsioni
from fonti import calendario_titoli, charts, giorno_di_borsa, rome
from tecnica import analyze, r4

HERE = Path(__file__).resolve().parent
SOGLIA_VOLUMI = 5.0       # volume >= 5 volte la media dei 60 giorni = +400%
MAX_ANOMALIE = 40


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(p: Path, data) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def short_name(n: str) -> str:
    """'Apple Inc.' -> 'Apple' (per cercare le notizie)."""
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\b(Inc|Corp|Corporation|Company|Co|Ltd|plc|PLC|N\.V|NV|S\.p\.A|SpA|SE|AG|SA|S\.A|Group|Holdings?|Class [A-C])\.?\b", "", n)
    return re.sub(r"[\s,.&]+$", "", re.sub(r"\s+", " ", n)).strip() or n


def run(kind: str, out: Path, use_ia: bool) -> None:
    now = time.time()
    out.mkdir(parents=True, exist_ok=True)
    uni = json.loads((HERE / "universo.json").read_text(encoding="utf-8"))
    groups = list(uni) if kind == "mattina" else ["FTSEMIB", "SX5E"]

    # ---------- titoli e indici ----------
    prev = load(out / "titoli.json", {})
    stocks: dict = prev.get("symbols", {}) if kind == "sera" else {}
    syms, info = [], {}
    for g in groups:
        for m in uni[g]["members"]:
            if m["s"] in info:      # titolo in piu' indici (es. Ferrari): vale il primo (FTSE MIB)
                continue
            syms.append(m["s"])
            info[m["s"]] = {"n": m["n"], "g": g, "isin": m.get("isin"), "sec": m.get("sec")}
    idx = [uni[g]["index"] for g in uni] + ["^IXIC", "^GDAXI", "^DJI"]
    t0 = time.time()
    raw = charts(syms + idx, rng="1y", interval="1d")
    print(f"Serie scaricate: {len(raw)}/{len(syms) + len(idx)} in {time.time() - t0:.0f}s")
    indices = prev.get("indices", {}) if kind == "sera" else {}
    for s, d in raw.items():
        a = analyze(d, now)
        if not a:
            continue
        if s in info:
            stocks[s] = {**{k: v for k, v in info[s].items() if v}, **a}
        else:
            indices[s] = a
    gmeta = {g: {"name": uni[g]["name"], "index": uni[g]["index"], "cur": uni[g]["cur"]} for g in uni}
    save(out / "titoli.json", {"generated": now, "run": kind, "groups": gmeta, "indices": indices, "symbols": stocks})

    # ---------- volumi anomali (ultima seduta chiusa) ----------
    anom = sorted((dict(s=s, **{k: x.get(k) for k in ("n", "g", "vr", "vol", "vavg60", "ch1", "c", "d", "cur")})
                   for s, x in stocks.items() if (x.get("vr") or 0) >= SOGLIA_VOLUMI), key=lambda x: -x["vr"])[:MAX_ANOMALIE]

    # ---------- conti trimestrali e dividendi in arrivo (solo mattina) ----------
    if kind == "mattina":
        t0 = time.time()
        cal = calendario_titoli(list(stocks))
        ev = {}
        for s, c in cal.items():
            e = {}
            fut = [t for t in c.get("earn", []) if t >= now - 86400]         # anche ieri: reazione al mercato oggi
            if fut and min(fut) <= now + 60 * 86400:
                e["earn"] = min(fut)
            if c.get("exdiv") and now - 86400 <= c["exdiv"] <= now + 60 * 86400:
                e["exdiv"] = c["exdiv"]
            if e:
                if c.get("div_anno"):
                    e["div_anno"] = c["div_anno"]
                ev[s] = e
        target = {s: c["target"] for s, c in cal.items() if c.get("target")}
        print(f"Calendario societario: {len(cal)}/{len(stocks)} titoli, {len(ev)} con eventi nei prossimi 60 giorni, {time.time() - t0:.0f}s")
        if cal:          # se Yahoo non risponde si tiene il file precedente
            save(out / "eventi.json", {"generated": now, "date": rome(now), "eventi": ev, "target": target})

    # ---------- notizie ----------
    items = notizie.collect(now)
    top = notizie.cluster(items, now)
    targets = [(s, short_name(info.get(s, stocks.get(s, {})).get("n", s)), uni[stocks[s]["g"]]["lang"])
               for s in [m["s"] for m in uni["FTSEMIB"]["members"]] + [a["s"] for a in anom[:15]] if s in stocks]
    targets = list(dict.fromkeys(targets))
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda t: (t[0], notizie.company_news(t[1], t[2], now)), targets))
    company = {s: n for s, n in res if n}
    for a in anom:
        a["news"] = company.get(a["s"], [])
    events = notizie.calendar(now)
    mac = previsioni.macro(now)

    merc = load(out / "mercato.json", {})
    storico = load(out / "storico.json", [])
    today = rome(now)
    if kind == "mattina":
        look = previsioni.outlook(now, mac, indices.get("FTSEMIB.MI"), events)
        look["date"] = today
        look["borsa_aperta"] = giorno_di_borsa(today)     # weekend e festivi: l'app non le mostra come "di oggi"
        storico = [r for r in storico if r.get("date") != today] + [{"date": today, "gap_est": look["gap_pct"], "label": look["label"]}]
    else:
        look = merc.get("outlook")
        # verifica: apertura reale del FTSE MIB contro la chiusura precedente
        d = raw.get("FTSEMIB.MI")
        if d and len(d["c"]) > 2 and rome(d["t"][-1]) == today:
            real = (d["o"][-1] / d["c"][-2] - 1) * 100
            for r in storico:
                if r.get("date") == today:
                    r["gap_real"] = r4(real)
                    r["close_real"] = r4((d["c"][-1] / d["c"][-2] - 1) * 100)
    storico = storico[-120:]
    save(out / "storico.json", storico)

    ai = merc.get("ia") if kind == "sera" else None
    if kind == "mattina" and use_ia:
        mib = [{"simbolo": s, "nome": x["n"], **{k: x.get(k) for k in ("c", "ch1", "ch5", "ch21", "rsi", "sma20", "sma50", "sma200",
                                                                       "trend", "piv", "sup", "res", "atr_pct", "vr", "hi52", "lo52")}}
               for s, x in stocks.items() if x.get("g") == "FTSEMIB"]
        payload = {"oggi": today, "stima_apertura": look, "mercati": mac, "calendario": events,
                   "notizie": [{"indice": i, "titolo": n["t"], "fonti": n["fonti"], "descrizione": n["desc"][:200]} for i, n in enumerate(top)],
                   "volumi_anomali": [{"simbolo": a["s"], "nome": a["n"], "volte_la_media": a["vr"], "variazione_pct": a["ch1"],
                                       "notizie": [n["t"] for n in a["news"]]} for a in anom[:15]],
                   "titoli_ftse_mib": mib}
        ai = ia.commento(payload)
        if ai:
            ai["date"] = today
        print("Commento IA:", "sì" if ai else "no")

    for n in top:
        n.pop("desc", None)
    save(out / "mercato.json", {
        "generated": now, "run": kind, "date": today, "soglia_volumi": SOGLIA_VOLUMI,
        "macro": mac, "outlook": look, "calendario": events, "notizie": top, "anomalie": anom,
        "notizie_titoli": company, "ia": ai,
    })
    print(f"Fatto: {len(stocks)} titoli, {len(anom)} volumi anomali, {len(top)} notizie, {len(events)} eventi.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("mattina", "sera"):
        print(__doc__)
        sys.exit(1)
    o = Path(a[a.index("--out") + 1]) if "--out" in a else HERE / "data"
    if "--se-manca" in a and a[0] == "mattina":      # secondo orario di riserva: niente doppioni
        if any(r.get("date") == rome(time.time()) for r in load(o / "storico.json", [])):
            print("Previsioni di oggi gia' pronte.")
            sys.exit(0)
    run(a[0], o, "--no-ia" not in a)

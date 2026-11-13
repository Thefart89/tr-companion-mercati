"""Volumi anomali DURANTE la seduta (gira su GitHub Actions ogni ~20 minuti nei giorni di borsa).

Idea: alle 10:30 non si confronta il volume con quello di una giornata intera, ma con quanto quel titolo
scambia di solito ENTRO le 10:30 (media degli ultimi 60 giorni, barre da 15 minuti di Yahoo).
Se ha gia' scambiato almeno SOGLIA volte il normale (+400%) viene segnalato, una volta al giorno.

Mercati controllati solo mentre sono aperti (orari letti da Yahoo, ora legale compresa):
    Europa (FTSE MIB, Euro Stoxx 50)  9:00-17:30 ora italiana
    USA (S&P 500)                     15:30-22:00 ora italiana
I primi 15 minuti dopo l'apertura non si segnalano (volumi sempre gonfiati dall'asta d'apertura).

    python volumi.py [--out data] [--cache cache] [--forza]     (--forza: controlla anche a mercato chiuso)
    python volumi.py --ricostruisci    storico simulato delle ultime ~35 sedute (verifica immediata)

Scrive (pubblici, senza dati personali):
    data/volumi_oggi.json       segnali di oggi, aggiornati a ogni controllo
    data/segnali_storico.json   segnali dei giorni passati con il prezzo di fine giornata (verifica dell'utilita')
Cache (non pubblicata): cache/profili.json  volume medio cumulato per fascia oraria, ricalcolato una volta al giorno.
Avviso Telegram facoltativo: segreti TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fonti import chart, charts, rome
from tecnica import r4

HERE = Path(__file__).resolve().parent
SOGLIA = 5.0            # 5 volte il normale a quell'ora = +400%
MIN_GIORNI = 20         # servono almeno 20 sedute di storia per fare la media
ATTESA_APERTURA = 15 * 60
DOPO_CHIUSURA = 45 * 60  # un ultimo controllo dopo la chiusura per fissare i prezzi finali
BARRA = 15 * 60
PRIMA_ORA = 3600
MERCATI = {
    "eu": {"nome": "Europa", "gruppi": ["FTSEMIB", "SX5E"], "rif": "FTSEMIB.MI"},
    "us": {"nome": "USA", "gruppi": ["SPX"], "rif": "^GSPC"},
}


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def seduta(rif: str, now: float) -> dict | None:
    """Orari della seduta di OGGI letti dall'indice di riferimento; None se oggi la borsa e' chiusa."""
    d = chart(rif, "1d", "15m")
    if not d:
        return None
    reg = d["meta"].get("currentTradingPeriod", {}).get("regular", {})
    start, end = reg.get("start"), reg.get("end")
    if not start or not end or rome(start) != rome(now):
        return None          # la prossima seduta non e' oggi
    if now >= start + 1800 and (not d["t"] or rome(d["t"][-1]) != rome(now)):
        return None          # mezz'ora dopo l'apertura e ancora nessuno scambio: festivo
    return {"start": start, "end": end}


def giorni_di(serie: dict) -> dict[str, list]:
    """Barre raggruppate per giorno (ora italiana): {data: [(ts, chiusura, volume), ...]}."""
    g: dict[str, list] = {}
    giorno, fine = None, 0
    for ts, c, v in zip(serie["t"], serie["c"], serie["v"]):
        if ts >= fine:                      # rome() solo una volta per giorno: e' lenta
            giorno = rome(ts)
            fine = ts - (ts + 3600 * 3) % 86400 + 86400   # confine alle 21:00 UTC, dopo l'ultima barra USA
        g.setdefault(giorno, []).append((ts, c, v or 0))
    return g


def cumulato(barre: list) -> list[float]:
    """Volume cumulato alla fine di ogni barra da 15 minuti (barre mancanti = nessuno scambio)."""
    t0 = barre[0][0]
    per_slot: dict[int, float] = {}
    for ts, _, v in barre:
        k = int(round((ts - t0) / BARRA))
        per_slot[k] = per_slot.get(k, 0) + v
    acc, row = 0.0, []
    for k in range(max(per_slot) + 1):
        acc += per_slot.get(k, 0)
        row.append(acc)
    return row


def profilo(serie: dict, oggi: str) -> dict | None:
    """Volume medio CUMULATO alla fine di ogni barra da 15 minuti, sulle sedute passate (oggi escluso)."""
    g = giorni_di(serie)
    return media_profilo([cumulato(b) for d, b in sorted(g.items()) if d != oggi])


def media_profilo(cum: list[list[float]]) -> dict | None:
    cum = cum[-60:]
    if len(cum) < MIN_GIORNI:
        return None
    n = max(len(r) for r in cum)
    media = []
    for k in range(n):
        vals = [r[k] if k < len(r) else r[-1] for r in cum]
        media.append(round(sum(vals) / len(vals)))
    return {"c": media, "g": len(cum)}


def atteso(prof: dict, trascorsi: float) -> float:
    """Volume normalmente scambiato dopo `trascorsi` secondi di seduta (interpolazione tra le barre)."""
    c = prof["c"]
    x = trascorsi / BARRA          # c[k] = cumulato alla fine della barra k, cioe' a (k+1) barre
    if x <= 1:
        return c[0] * max(x, 0)
    k = int(x)
    if k >= len(c):
        return c[-1]
    return c[k - 1] + (c[k] - c[k - 1]) * (x - k)


def telegram(testo: str) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": testo, "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=body, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:  # il token non va mai stampato: solo il tipo di errore
        print(f"Telegram: invio non riuscito ({type(e).__name__})", file=sys.stderr)
        return False


def fmt(v: float, dec: int = 1) -> str:
    return f"{v:+.{dec}f}".replace(".", ",")


def run(out: Path, cache: Path, forza: bool) -> None:
    now = time.time()
    oggi = rome(now)
    uni = json.loads((HERE / "universo.json").read_text(encoding="utf-8"))
    stato = load(out / "volumi_oggi.json", {})
    storico = load(out / "segnali_storico.json", [])

    # ---------- cambio di giorno: i segnali di ieri passano allo storico con il prezzo finale ----------
    if stato.get("date") and stato["date"] != oggi:
        for s in stato.get("segnali", []):
            if s.get("p1") and s.get("p"):
                dopo = (s["p"] / s["p1"] - 1) * 100
                storico.append({"date": stato["date"], **{k: s.get(k) for k in ("s", "n", "g", "m", "tipo", "t1", "r1", "p1", "ch1", "idx1", "p", "ch", "idx", "r")},
                                "dopo": r4(dopo),          # movimento dopo il segnale, fino alla chiusura
                                "continua": (dopo > 0) == (s["ch1"] > 0) and dopo != 0})
        storico = storico[-1500:]
        save(out / "segnali_storico.json", storico)
        stato = {}
    stato.setdefault("date", oggi)
    stato.setdefault("segnali", [])
    stato.setdefault("mercati", {})
    sig = {s["s"]: s for s in stato["segnali"]}

    profili = load(cache / "profili.json", {})
    if profili.get("date") != oggi:
        profili = {"date": oggi, "p": {}}

    nuovi = []
    prima = json.dumps(stato["mercati"], sort_keys=True)
    for mk, M in MERCATI.items():
        ses = seduta(M["rif"], now)
        info = stato["mercati"].get(mk, {})
        if not ses:
            stato["mercati"][mk] = {"nome": M["nome"], "stato": "chiuso oggi"}
            continue
        start, end = ses["start"], ses["end"]
        if now < start + ATTESA_APERTURA and not forza:
            st = "non ancora aperto" if now < start else "appena aperto"
            stato["mercati"][mk] = {"nome": M["nome"], "stato": st, "apre": start, "chiude": end}
            continue
        if now > end + DOPO_CHIUSURA and info.get("finale") and not forza:
            continue                         # gia' fissati i prezzi di chiusura
        membri, gruppo_di, nomi = [], {}, {}
        for g in M["gruppi"]:
            for m in uni[g]["members"]:
                if m["s"] not in gruppo_di:
                    membri.append(m["s"]); gruppo_di[m["s"]] = g; nomi[m["s"]] = m["n"]
        indici = {g: uni[g]["index"] for g in M["gruppi"]}

        # profili (una volta al giorno)
        mancano = [s for s in membri if s not in profili["p"]]
        if mancano:
            t0 = time.time()
            for s, d in charts(mancano, "60d", "15m").items():
                p = profilo(d, oggi)
                if p:
                    profili["p"][s] = p
            print(f"{M['nome']}: profili calcolati per {sum(s in profili['p'] for s in mancano)}/{len(mancano)} titoli in {time.time() - t0:.0f}s")
            save(cache / "profili.json", profili)

        # situazione di oggi
        t0 = time.time()
        oggi_raw = charts(membri + list(indici.values()), "1d", "15m")
        idx_ch = {}
        for g, s in indici.items():
            d = oggi_raw.get(s)
            if d and d["meta"].get("chartPreviousClose"):
                idx_ch[g] = r4((d["meta"]["regularMarketPrice"] / d["meta"]["chartPreviousClose"] - 1) * 100)
        controllati = 0
        for s in membri:
            d, p = oggi_raw.get(s), profili["p"].get(s)
            if not d or not p or not d["t"] or rome(d["t"][0]) != oggi:
                continue
            meta = d["meta"]
            prezzo, prec = meta.get("regularMarketPrice"), meta.get("chartPreviousClose")
            if not prezzo or not prec:
                continue
            ultimo = min(meta.get("regularMarketTime") or now, now, end)
            trascorsi = ultimo - start
            vol = sum(d["v"])
            att = atteso(p, trascorsi)
            if att <= 0:
                continue
            controllati += 1
            r = vol / att
            ch = (prezzo / prec - 1) * 100
            g = gruppo_di[s]
            if s in sig:                      # gia' segnalato oggi: si aggiornano i valori
                sig[s].update({"r": r4(r), "p": prezzo, "ch": r4(ch), "idx": idx_ch.get(g), "tp": ultimo, "vol": vol, "att": round(att)})
            elif r >= SOGLIA and trascorsi >= ATTESA_APERTURA:
                sig[s] = {"s": s, "n": nomi[s], "g": g, "m": mk, "t1": ultimo, "r1": r4(r), "p1": prezzo, "ch1": r4(ch),
                          "idx1": idx_ch.get(g), "r": r4(r), "p": prezzo, "ch": r4(ch), "idx": idx_ch.get(g), "tp": ultimo,
                          "vol": vol, "att": round(att), "avvisato": False,
                          # "apertura": entro la prima ora (di solito notizie/trimestrali, prezzo gia' mosso);
                          # "seduta": dopo la prima ora. Nello storico i due tipi si misurano a parte.
                          "tipo": "apertura" if trascorsi < PRIMA_ORA else "seduta"}
                nuovi.append(sig[s])
        chiuso = now > end + 15 * 60       # i dati arrivano con ~15 minuti di ritardo
        stato["mercati"][mk] = {"nome": M["nome"], "stato": "chiuso" if now > end else "aperto", "apre": start, "chiude": end,
                                "controllo": now, "dati_fino": max((oggi_raw[s]["meta"].get("regularMarketTime") or 0) for s in oggi_raw) if oggi_raw else None,
                                "titoli": controllati, "indici": idx_ch, "finale": chiuso}
        print(f"{M['nome']}: {controllati}/{len(membri)} titoli controllati in {time.time() - t0:.0f}s")

    # ---------- avviso Telegram per i segnali nuovi (solo se recenti: niente arretrati) ----------
    da_avvisare = [s for s in sig.values() if not s.get("avvisato") and now - s["t1"] < 3600]
    if da_avvisare:
        righe = []
        for s in sorted(da_avvisare, key=lambda x: -x["r1"]):
            verso = "prevalgono le vendite" if s["ch1"] < 0 else "prevalgono gli acquisti" if s["ch1"] > 0 else "prezzo fermo"
            idx = f", indice {fmt(s['idx1'])}%" if s.get("idx1") is not None else ""
            volte = f"{s['r1']:.1f}".replace(".", ",")
            quando = "in apertura" if s.get("tipo") == "apertura" else "in seduta"
            righe.append(f"• {s['n']} ({s['s']}), {quando}: volumi {volte} volte il normale a quest'ora"
                         + f", prezzo {fmt(s['ch1'])}%{idx} — {verso}")
        testo = "📊 Volumi anomali adesso (dati con ~15 min di ritardo)\n" + "\n".join(righe) + "\nNon è un consiglio: valuta tu."
        if telegram(testo):
            for s in da_avvisare:
                s["avvisato"] = True
            print(f"Telegram: avvisati {len(da_avvisare)} segnali")
    if nuovi:
        print("Nuovi segnali:", ", ".join(f"{s['s']} x{s['r1']:.1f}" for s in nuovi))

    if nuovi or da_avvisare or json.dumps(stato["mercati"], sort_keys=True) != prima:
        stato["segnali"] = sorted(sig.values(), key=lambda x: x["t1"])
        stato.update({"generated": now, "soglia": SOGLIA})
        save(out / "volumi_oggi.json", stato)
    else:
        print("Nessun mercato da controllare adesso.")


def ricostruisci(out: Path) -> None:
    """Storico SIMULATO sulle ultime ~35 sedute (dati da 15 minuti), per avere subito la verifica.
    Prezzo d'ingresso = chiusura della barra DOPO il segnale (i dati arrivano in ritardo)."""
    uni = json.loads((HERE / "universo.json").read_text(encoding="utf-8"))
    membri, info = [], {}
    for mk, M in MERCATI.items():
        for g in M["gruppi"]:
            for m in uni[g]["members"]:
                if m["s"] not in info:
                    membri.append(m["s"]); info[m["s"]] = (m["n"], g, mk)
    raw = charts(membri, "60d", "15m")
    oggi = rome(time.time())
    sim = []
    for s, d in raw.items():
        n, g, mk = info[s]
        giorni = giorni_di(d)
        chiavi = sorted(giorni)
        cums = [cumulato(giorni[k]) for k in chiavi]
        for j, k in enumerate(chiavi):
            if j < 25 or k == oggi:
                continue
            prof = media_profilo(cums[max(0, j - 60):j])
            if not prof:
                continue
            barre = giorni[k]
            t0, prec, fine = barre[0][0], giorni[chiavi[j - 1]][-1][1], barre[-1][1]
            acc = 0
            for i, (ts, c, v) in enumerate(barre):
                acc += v
                trascorsi = ts + BARRA - t0
                att = atteso(prof, trascorsi)
                if trascorsi < 2 * BARRA or att <= 0 or acc / att < SOGLIA:
                    continue
                p1 = barre[min(i + 1, len(barre) - 1)][1]
                ch1 = (c / prec - 1) * 100
                dopo = (fine / p1 - 1) * 100
                sim.append({"date": k, "s": s, "n": n, "g": g, "m": mk, "t1": ts + BARRA, "r1": r4(acc / att), "p1": p1,
                            "ch1": r4(ch1), "p": fine, "ch": r4((fine / prec - 1) * 100), "dopo": r4(dopo),
                            "continua": (dopo > 0) == (ch1 > 0) and dopo != 0,
                            "tipo": "apertura" if trascorsi < PRIMA_ORA else "seduta", "sim": True})
                break
    vero = [x for x in load(out / "segnali_storico.json", []) if not x.get("sim")]
    giorni_veri = {x["date"] for x in vero}
    tutti = sorted([x for x in sim if x["date"] not in giorni_veri] + vero, key=lambda x: (x["date"], x["t1"]))
    save(out / "segnali_storico.json", tutti[-1500:])
    print(f"Storico simulato: {len(sim)} segnali in {len({x['date'] for x in sim})} sedute")


if __name__ == "__main__":
    a = sys.argv[1:]
    o = Path(a[a.index("--out") + 1]) if "--out" in a else HERE / "data"
    c = Path(a[a.index("--cache") + 1]) if "--cache" in a else HERE / "cache"
    if "--ricostruisci" in a:
        ricostruisci(o)
    else:
        run(o, c, "--forza" in a)

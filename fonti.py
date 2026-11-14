"""Scaricamento dati: pagine web e serie storiche giornaliere di Yahoo Finance (solo libreria standard)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url: str, timeout: float = 20, tries: int = 3) -> bytes:
    """GET con qualche nuovo tentativo (429 e errori di rete), attese crescenti."""
    last: Exception | None = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
            time.sleep(2 + 4 * i)
        except Exception as e:  # rete, timeout
            last = e
            time.sleep(1 + 2 * i)
    raise last or RuntimeError(url)


def chart(symbol: str, rng: str = "1y", interval: str = "1d") -> dict | None:
    """Serie OHLCV di Yahoo. Restituisce {meta, t, o, h, l, c, v} senza le righe vuote, o None."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?range={rng}&interval={interval}&includePrePost=false")
    try:
        d = json.loads(get(url))["chart"]
    except Exception:
        return None
    if not d.get("result"):
        return None
    r = d["result"][0]
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    t = r.get("timestamp") or []
    out = {"meta": r.get("meta", {}), "t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for i, ts in enumerate(t):
        c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
        if c is None:
            continue
        out["t"].append(ts)
        out["c"].append(c)
        for k, src in (("o", "open"), ("h", "high"), ("l", "low")):
            x = (q.get(src) or [None] * len(t))[i]
            out[k].append(x if x is not None else c)
        out["v"].append((q.get("volume") or [None] * len(t))[i] or 0)
    return out


def charts(symbols: list[str], rng: str = "1y", interval: str = "1d", workers: int = 6) -> dict[str, dict]:
    """Scarica molte serie in parallelo (pochi alla volta per non farsi bloccare)."""
    res: dict[str, dict] = {}

    def one(s: str) -> None:
        c = chart(s, rng, interval)
        if c and c["c"]:
            res[s] = c

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, symbols))
    return res


# ---------------- ora italiana (senza dipendere dal database dei fusi orari) ----------------
def _last_sunday(year: int, month: int) -> int:
    import calendar
    d = calendar.monthrange(year, month)[1]
    while calendar.weekday(year, month, d) != 6:
        d -= 1
    return d


def rome_offset(ts: float) -> int:
    """Secondi da aggiungere all'UTC: +2h dall'ultima domenica di marzo all'ultima di ottobre (01:00 UTC)."""
    import datetime as dt
    u = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    start = dt.datetime(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=dt.timezone.utc)
    return 7200 if start <= u < end else 3600


def rome(ts: float, fmt: str = "%Y-%m-%d") -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts + rome_offset(ts), dt.timezone.utc).strftime(fmt)


# ---------------- calendario societario (conti trimestrali, dividendi) ----------------
def _yahoo_crumb():
    """Sessione Yahoo con cookie e 'crumb': serve per l'interfaccia quoteSummary (date dei conti e dei dividendi)."""
    import http.cookiejar
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        op.open(urllib.request.Request("https://fc.yahoo.com", headers={"User-Agent": UA}), timeout=20)
    except Exception:
        pass        # risponde 404 ma imposta comunque il cookie
    crumb = op.open(urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb",
                                           headers={"User-Agent": UA}), timeout=20).read().decode()
    return op, crumb


def calendario_titoli(symbols: list[str], workers: int = 6) -> dict[str, dict]:
    """{simbolo: {earn: [ts...], exdiv: ts, divdate: ts, div_anno: importo,
                  target: {m, med, lo, hi, n, rec, rec_m}}} (solo i campi presenti).
    target = prezzo obiettivo a 12 mesi degli analisti (media, mediana, minimo, massimo, numero di analisti)
    e consenso (rec: strong_buy/buy/hold/underperform/sell; rec_m: 1 = comprare ... 5 = vendere)."""
    try:
        op, crumb = _yahoo_crumb()
    except Exception as e:
        print(f"Calendario societario non disponibile: {e}")
        return {}
    res: dict[str, dict] = {}

    def one(s: str) -> None:
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(s)}"
               f"?modules=calendarEvents,summaryDetail,financialData&crumb={urllib.parse.quote(crumb)}")
        for i in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                r = json.loads(op.open(req, timeout=20).read())["quoteSummary"]["result"][0]
                break
            except Exception:
                time.sleep(2 + 3 * i)
        else:
            return
        ce, sd, fd = r.get("calendarEvents") or {}, r.get("summaryDetail") or {}, r.get("financialData") or {}
        out = {}
        raw = lambda k: (fd.get(k) or {}).get("raw") if isinstance(fd.get(k), dict) else None
        n = raw("numberOfAnalystOpinions")
        if raw("targetMeanPrice") and n:
            out["target"] = {"m": raw("targetMeanPrice"), "med": raw("targetMedianPrice"), "lo": raw("targetLowPrice"),
                             "hi": raw("targetHighPrice"), "n": n, "rec": fd.get("recommendationKey"),
                             "rec_m": raw("recommendationMean")}
        earn = [e.get("raw") for e in (ce.get("earnings") or {}).get("earningsDate") or [] if e.get("raw")]
        if earn:
            out["earn"] = earn
        for k, src in (("exdiv", ce.get("exDividendDate")), ("divdate", ce.get("dividendDate"))):
            if isinstance(src, dict) and src.get("raw"):
                out[k] = src["raw"]
        rate = (sd.get("dividendRate") or {}).get("raw")
        if rate:
            out["div_anno"] = rate
        if out:
            res[s] = out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, symbols))
    return res


# ---------------- giorni di apertura di Borsa Italiana ----------------
def _pasqua(y: int):
    import datetime as dt
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(y, mese, giorno)


def giorno_di_borsa(data: str) -> bool:
    """True se Borsa Italiana e' aperta in quella data (AAAA-MM-GG): niente weekend e festivita' di borsa
    (1/1, Venerdi' Santo, Pasquetta, 1/5, 15/8, 24-26/12, 31/12)."""
    import datetime as dt
    d = dt.date.fromisoformat(data)
    if d.weekday() >= 5:
        return False
    p = _pasqua(d.year)
    chiusi = {(1, 1), (5, 1), (8, 15), (12, 24), (12, 25), (12, 26), (12, 31)}
    return (d.month, d.day) not in chiusi and d not in (p - dt.timedelta(days=2), p + dt.timedelta(days=1))

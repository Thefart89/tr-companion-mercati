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

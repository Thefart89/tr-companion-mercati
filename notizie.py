"""Notizie dai feed RSS pubblici: raccolta, raggruppamento della stessa notizia, punteggio.

Si salvano solo titolo, fonte, ora e link (niente testi degli articoli).
"""
from __future__ import annotations

import email.utils
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from fonti import get, rome

FEEDS = [
    ("Il Sole 24 Ore", "https://www.ilsole24ore.com/rss/finanza.xml", "it"),
    ("Il Sole 24 Ore", "https://www.ilsole24ore.com/rss/economia.xml", "it"),
    ("ANSA", "https://www.ansa.it/sito/notizie/economia/economia_rss.xml", "it"),
    ("la Repubblica", "https://www.repubblica.it/rss/economia/rss2.0.xml", "it"),
    ("Investing.com", "https://it.investing.com/rss/news.rss", "it"),
    ("Google News", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=it&gl=IT&ceid=IT:it", "it"),
    ("Google News", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", "en"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "en"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "en"),
]

# parole che rendono una notizia rilevante per i mercati (peso)
KEYWORDS = {
    "bce": 3, "fed": 3, "tassi": 3, "rates": 2, "inflazione": 3, "inflation": 3, "pil": 2, "gdp": 2,
    "dazi": 3, "tariff": 3, "borsa": 2, "piazza affari": 3, "ftse mib": 3, "wall street": 2, "spread": 2,
    "btp": 2, "petrolio": 2, "oil": 2, "opec": 2, "oro": 1, "gold": 1, "utili": 2, "earnings": 2,
    "trimestrale": 2, "conti": 1, "guidance": 2, "lagarde": 3, "powell": 3, "occupazione": 2,
    "payrolls": 3, "jobs": 1, "recessione": 3, "recession": 3, "guerra": 2, "war": 2, "cina": 1, "china": 1,
    "opa": 3, "acquisizione": 2, "merger": 2, "acquisition": 2, "downgrade": 2, "upgrade": 2,
    "rating": 2, "default": 2, "banca": 1, "bank": 1, "euro": 1, "dollaro": 1, "dollar": 1, "bitcoin": 1,
}
STOP = set("""il lo la i gli le un una di a da in con su per tra fra e o ma che non del della dei delle al alla
ai alle nel nella nei nelle sul sulla è ed the a an of to in on for and or with at by from as is are be its
it this that after over says say new più come anche dopo oggi""".split())


def _text(el: ET.Element | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", (el.text or "") if el is not None else "")).strip()


def parse_feed(raw: bytes, source: str, lang: str) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = _text(it.find("title"))
        if not title:
            continue
        src = source
        s = it.find("source")
        if s is not None and s.text:          # Google News: fonte vera
            src = s.text.strip()
            title = re.sub(r"\s+-\s+" + re.escape(src) + r"$", "", title)
        ts = None
        pd = it.find("pubDate")
        if pd is not None and pd.text:
            try:
                ts = email.utils.parsedate_to_datetime(pd.text).timestamp()
            except (TypeError, ValueError):
                ts = None
        out.append({"t": re.sub(r"\s+", " ", title), "src": src, "url": _text(it.find("link")), "ts": ts, "lang": lang,
                    "desc": _text(it.find("description"))[:300]})
    return out


def words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ù0-9]{3,}", t.lower()) if w not in STOP}


def score(item: dict, now: float) -> float:
    low = item["t"].lower()
    s = sum(w for k, w in KEYWORDS.items() if re.search(r"\b" + re.escape(k) + r"\b", low))
    age_h = (now - item["ts"]) / 3600 if item.get("ts") else 12
    return s + max(0, 6 - age_h / 4)  # piu' recente = meglio (fino a ~24 ore)


def collect(now: float, max_age_h: float = 30) -> list[dict]:
    items: list[dict] = []
    for name, url, lang in FEEDS:
        try:
            items += parse_feed(get(url, timeout=15, tries=2), name, lang)
        except Exception:
            continue
    items = [i for i in items if not i["ts"] or now - i["ts"] < max_age_h * 3600]
    return items


def cluster(items: list[dict], now: float, top: int = 25) -> list[dict]:
    """Raggruppa le notizie con titoli simili; piu' fonti = piu' importante."""
    groups: list[dict] = []
    for it in sorted(items, key=lambda x: -(x["ts"] or 0)):
        w = words(it["t"])
        if len(w) < 2:
            continue
        best = None
        for g in groups:
            inter = len(w & g["w"])
            if inter >= 3 and inter / min(len(w), len(g["w"])) >= 0.5:
                best = g
                break
        if best:
            best["items"].append(it)
            best["w"] |= w
        else:
            groups.append({"w": set(w), "items": [it]})
    out = []
    for g in groups:
        lead = g["items"][0]
        srcs = sorted({i["src"] for i in g["items"]})
        sc = max(score(i, now) for i in g["items"]) + 3 * (len(srcs) - 1)
        out.append({"t": lead["t"], "src": lead["src"], "url": lead["url"], "ts": lead["ts"], "lang": lead["lang"],
                    "desc": lead["desc"], "fonti": srcs[:6], "score": round(sc, 1)})
    out.sort(key=lambda x: -x["score"])
    return out[:top]


def company_news(name: str, lang: str, now: float, n: int = 3) -> list[dict]:
    """Ultime notizie su un'azienda (Google News)."""
    if lang == "it":
        q, loc = f'"{name}" azioni OR borsa', "hl=it&gl=IT&ceid=IT:it"
    else:
        q, loc = f'"{name}" stock OR shares', "hl=en-US&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}+when:3d&{loc}"
    try:
        items = parse_feed(get(url, timeout=15, tries=2), "Google News", lang)
    except Exception:
        return []
    items = [i for i in items if i["ts"] and now - i["ts"] < 4 * 86400]
    items.sort(key=lambda x: -x["ts"])
    return [{k: i[k] for k in ("t", "src", "url", "ts")} for i in items[:n]]


def calendar(now: float) -> list[dict]:
    """Appuntamenti macro di oggi con impatto alto/medio (calendario pubblico settimanale)."""
    import json
    try:
        ev = json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15, tries=2))
    except Exception:
        return []
    today = rome(now)
    out = []
    for e in ev:
        if e.get("impact") not in ("High", "Medium") or e.get("country") not in ("EUR", "USD", "GBP", "CNY", "JPY"):
            continue
        d = str(e.get("date", ""))
        try:
            ts = __import__("datetime").datetime.fromisoformat(d).timestamp()
        except ValueError:
            continue
        if rome(ts) != today:
            continue
        out.append({"ts": ts, "paese": e.get("country"), "evento": e.get("title"), "impatto": e.get("impact"),
                    "previsto": e.get("forecast") or None, "precedente": e.get("previous") or None})
    return sorted(out, key=lambda x: x["ts"])

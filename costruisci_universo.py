"""Rigenera universo.json (titoli dei 3 indici) da Wikipedia. Si usa di rado, a mano:

    pip install pandas lxml
    python costruisci_universo.py

Le composizioni cambiano poche volte l'anno; il lavoro giornaliero legge solo universo.json.
"""
from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (tr-companion universe builder)"}


def tables(url: str) -> list[pd.DataFrame]:
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode()
    return pd.read_html(io.StringIO(html))


def pick(ts: list[pd.DataFrame], col: str, min_rows: int) -> pd.DataFrame:
    for t in ts:
        if col in t.columns and len(t) >= min_rows:
            return t
    raise SystemExit(f"Tabella con colonna {col} non trovata")


def main() -> None:
    mib = pick(tables("https://en.wikipedia.org/wiki/FTSE_MIB"), "ISIN", 35)
    sx5e = pick(tables("https://en.wikipedia.org/wiki/EURO_STOXX_50"), "Main listing", 45)
    spx = pick(tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"), "GICS Sector", 450)
    out = {
        "FTSEMIB": {"name": "FTSE MIB", "index": "FTSEMIB.MI", "cur": "EUR", "lang": "it",
                    "members": [{"s": r.Ticker, "n": r.Company, "isin": r.ISIN, "sec": r._4}
                                for r in mib.itertuples()]},
        "SX5E": {"name": "Euro Stoxx 50", "index": "^STOXX50E", "cur": "EUR", "lang": "en",
                 "members": [{"s": r.Ticker, "n": r.Name, "sec": r.Sector} for r in sx5e.itertuples()]},
        "SPX": {"name": "S&P 500", "index": "^GSPC", "cur": "USD", "lang": "en",
                "members": [{"s": str(r.Symbol).replace(".", "-"), "n": r.Security, "sec": r._3}
                            for r in spx.itertuples()]},
    }
    (HERE / "universo.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print({k: len(v["members"]) for k, v in out.items()})


if __name__ == "__main__":
    main()

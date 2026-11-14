"""Commento del mattino scritto da un'IA (facoltativo).

- GEMINI_API_KEY (scelta dell'utente, 13/11): Google Gemini, piano gratuito di Google AI Studio.
  Nel piano gratuito Google puo' usare i testi inviati: qui partono solo dati di mercato pubblici.
- ANTHROPIC_API_KEY (alternativa a pagamento, ~0,10-0,15 $ al giorno): Claude Opus 5.5.
Senza chiave, o se la chiamata non riesce, l'app mostra solo i calcoli automatici.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

MODEL = "claude-opus-5-5"
# alias aggiornato da Google, poi riserve (la "lite" e' la meno richiesta quando Google e' sovraccarico)
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]

SYSTEM = """Sei un analista di mercato che scrive in italiano semplice per un risparmiatore che non è un esperto.
Ricevi dati JSON raccolti stamattina: mercati esteri, una stima automatica dell'apertura di Milano, appuntamenti
macro, titoli delle notizie, titoli con volumi anomali e indicatori tecnici dei titoli del FTSE MIB.

Regole:
- Usa solo i dati ricevuti: non inventare numeri, notizie o eventi.
- Descrivi scenari e livelli da osservare ("se supera…", "se scende sotto…"), mai consigli di comprare o vendere.
- Sii prudente: le previsioni sono incerte, dillo quando i segnali sono deboli o contrastanti.
- Frasi brevi, niente gergo; se usi un termine tecnico (RSI, media mobile) spiegalo in poche parole la prima volta.
- I prezzi in formato italiano (1.234,5)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "sintesi": {"type": "string", "description": "4-6 frasi: cosa aspettarsi oggi sui mercati, a partire da Milano"},
        "anomalie": {"type": "array", "items": {"type": "object", "properties": {
            "simbolo": {"type": "string"}, "commento": {"type": "string", "description": "1-2 frasi: possibile motivo dei volumi"}},
            "required": ["simbolo", "commento"], "additionalProperties": False}},
        "titoli": {"type": "array", "description": "Un commento per ogni titolo del FTSE MIB ricevuto",
                   "items": {"type": "object", "properties": {
                       "simbolo": {"type": "string"},
                       "commento": {"type": "string", "description": "1-2 frasi: lettura tecnica e livelli da osservare"}},
                       "required": ["simbolo", "commento"], "additionalProperties": False}},
    },
    "required": ["sintesi", "anomalie", "titoli"],
    "additionalProperties": False,
}

# ---------- notizie: commento sotto ogni notizia + notizie internazionali tradotte (richiesta del 14/11) ----------
SYSTEM_NEWS = """Sei un analista di mercato che scrive in italiano semplice per un risparmiatore italiano che non è un esperto
e che investe in certificati a leva su azioni (soprattutto italiane) e indici.
Ricevi due liste di notizie di oggi: "italiane" (giornali italiani) e "estere" (giornali internazionali, in inglese),
ognuna con titolo, fonti e a volte una breve descrizione.

Compiti:
1. Per OGNI notizia italiana scrivi un commento: le possibili conseguenze sui mercati (quali settori, titoli, indici,
   tassi, spread, valute o materie prime potrebbero muoversi, in che direzione e perché).
2. Indica le notizie italiane più importanti per chi investe oggi (al massimo 8, in ordine di importanza).
3. Dalle notizie estere scegli quelle rilevanti per i mercati (al massimo 10, in ordine di importanza) e SCARTA
   quelle che raccontano un fatto già presente tra le notizie italiane (stesso evento, anche con parole diverse),
   le notizie di costume, sport o cronaca senza effetti sui mercati, e i doppioni tra loro.
   Per ognuna: titolo tradotto in italiano naturale, una frase che riassume il fatto, e il commento come al punto 1.

Regole:
- Usa solo le informazioni ricevute: non inventare numeri, dichiarazioni o fatti che non sono nel titolo o nella descrizione.
- Usa il condizionale e indica l'incertezza ("potrebbe", "di solito"); se l'effetto è probabilmente piccolo, dillo.
- Mai consigli di comprare o vendere.
- Commenti di 1-2 frasi brevi, niente gergo (se usi un termine tecnico spiegalo in poche parole).
- Nomi di aziende e persone come nell'originale; numeri in formato italiano (1.234,5)."""

SCHEMA_NEWS = {
    "type": "object",
    "properties": {
        "importanti": {"type": "array", "description": "indici delle notizie italiane più importanti, in ordine, al massimo 8",
                       "items": {"type": "integer"}},
        "italiane": {"type": "array", "description": "un elemento per ogni notizia italiana ricevuta",
                     "items": {"type": "object", "properties": {
                         "indice": {"type": "integer"},
                         "commento": {"type": "string", "description": "1-2 frasi: possibili effetti sui mercati"}},
                         "required": ["indice", "commento"], "additionalProperties": False}},
        "estere": {"type": "array", "description": "notizie estere rilevanti e non già presenti tra le italiane, al massimo 10, in ordine di importanza",
                   "items": {"type": "object", "properties": {
                       "indice": {"type": "integer", "description": "posizione nella lista estera ricevuta"},
                       "titolo": {"type": "string", "description": "titolo tradotto in italiano"},
                       "sintesi": {"type": "string", "description": "una frase in italiano: il fatto"},
                       "commento": {"type": "string", "description": "1-2 frasi: possibili effetti sui mercati"}},
                       "required": ["indice", "titolo", "sintesi", "commento"], "additionalProperties": False}},
    },
    "required": ["importanti", "italiane", "estere"],
    "additionalProperties": False,
}


def notizie(payload: dict) -> dict | None:
    """Commento a ogni notizia italiana, scelta delle piu' importanti, notizie estere tradotte senza doppioni."""
    if os.environ.get("GEMINI_API_KEY"):
        return commento_gemini(payload, SYSTEM_NEWS, SCHEMA_NEWS)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return commento_claude(payload, SYSTEM_NEWS, SCHEMA_NEWS)
    return None


def commento(payload: dict) -> dict | None:
    if os.environ.get("GEMINI_API_KEY"):
        return commento_gemini(payload)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return commento_claude(payload)
    return None


def _gemini_schema(x):
    """JSON Schema -> sottoinsieme OpenAPI accettato da Gemini (tipi maiuscoli, niente additionalProperties)."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k == "additionalProperties":
                continue
            out[k] = v.upper() if k == "type" and isinstance(v, str) else _gemini_schema(v)
        return out
    if isinstance(x, list):
        return [_gemini_schema(v) for v in x]
    return x


def commento_gemini(payload: dict, system: str = SYSTEM, schema: dict = SCHEMA) -> dict | None:
    key = os.environ["GEMINI_API_KEY"]
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": _gemini_schema(schema),
                             "maxOutputTokens": 16000},
    }).encode()
    # Ogni modello: fino a 3 tentativi se Google e' sovraccarico (503/500/429) o non risponde;
    # poi si passa al modello successivo. Chiave non valida o richiesta errata: stop subito.
    for model in GEMINI_MODELS:
        d = None
        for tentativo in range(3):
            if tentativo:
                time.sleep(20 * tentativo)
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                msg = " ".join(e.read().decode(errors="replace").split())[:200]
                print(f"IA Gemini ({model}): errore {e.code}: {msg}", file=sys.stderr)
                if e.code == 404:          # modello non disponibile: si prova il successivo
                    break
                if e.code not in (429, 500, 502, 503, 504):
                    return None
            except Exception as e:  # rete, timeout: senza risposta in 3 minuti si passa subito al modello successivo
                print(f"IA Gemini ({model}): {e}", file=sys.stderr)
                break
        if d is None:
            continue
        try:
            cand = d["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
            out = json.loads(text)
        except (KeyError, IndexError, ValueError):
            print(f"IA Gemini ({model}): risposta non utilizzabile ({str(d)[:200]})", file=sys.stderr)
            return None
        u = d.get("usageMetadata", {})
        out["modello"] = d.get("modelVersion") or model
        out["costo_token"] = {"in": u.get("promptTokenCount"), "out": u.get("candidatesTokenCount")}
        return out
    return None


def commento_claude(payload: dict, system: str = SYSTEM, schema: dict = SCHEMA) -> dict | None:
    try:
        import anthropic
    except ImportError:
        print("IA: libreria anthropic non installata", file=sys.stderr)
        return None
    client = anthropic.Anthropic()
    try:
        r = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",          # se il modello rifiuta, l'API riprova da sola con un altro modello
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
    except anthropic.AuthenticationError:
        print("IA: chiave API non valida", file=sys.stderr)
        return None
    except anthropic.RateLimitError:
        print("IA: limite di richieste raggiunto", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"IA: errore {e.status_code}: {e.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError:
        print("IA: errore di rete", file=sys.stderr)
        return None
    if r.stop_reason in ("refusal", "max_tokens"):
        print(f"IA: risposta non utilizzabile ({r.stop_reason})", file=sys.stderr)
        return None
    text = next((b.text for b in r.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except ValueError:
        return None
    out["modello"] = r.model
    out["costo_token"] = {"in": r.usage.input_tokens, "out": r.usage.output_tokens}
    return out

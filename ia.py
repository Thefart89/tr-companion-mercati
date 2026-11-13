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
import urllib.error
import urllib.request

MODEL = "claude-opus-5-5"
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash"]   # alias aggiornato da Google, poi riserva

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
        "notizie": {"type": "array", "description": "Le notizie più importanti di oggi, al massimo 8, in ordine di importanza",
                    "items": {"type": "object", "properties": {
                        "indice": {"type": "integer", "description": "posizione della notizia nella lista ricevuta"},
                        "perche": {"type": "string", "description": "una frase: perché conta per i mercati"}},
                        "required": ["indice", "perche"], "additionalProperties": False}},
        "anomalie": {"type": "array", "items": {"type": "object", "properties": {
            "simbolo": {"type": "string"}, "commento": {"type": "string", "description": "1-2 frasi: possibile motivo dei volumi"}},
            "required": ["simbolo", "commento"], "additionalProperties": False}},
        "titoli": {"type": "array", "description": "Un commento per ogni titolo del FTSE MIB ricevuto",
                   "items": {"type": "object", "properties": {
                       "simbolo": {"type": "string"},
                       "commento": {"type": "string", "description": "1-2 frasi: lettura tecnica e livelli da osservare"}},
                       "required": ["simbolo", "commento"], "additionalProperties": False}},
    },
    "required": ["sintesi", "notizie", "anomalie", "titoli"],
    "additionalProperties": False,
}


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


def commento_gemini(payload: dict) -> dict | None:
    key = os.environ["GEMINI_API_KEY"]
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": _gemini_schema(SCHEMA),
                             "maxOutputTokens": 16000},
    }).encode()
    for model in GEMINI_MODELS:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body, method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            print(f"IA Gemini ({model}): errore {e.code}: {msg}", file=sys.stderr)
            if e.code == 404:          # modello non disponibile: si prova il successivo
                continue
            return None
        except Exception as e:  # rete, timeout
            print(f"IA Gemini ({model}): {e}", file=sys.stderr)
            return None
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


def commento_claude(payload: dict) -> dict | None:
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
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
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

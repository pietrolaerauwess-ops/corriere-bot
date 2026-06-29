"""Lettura degli indirizzi dei DESTINATARI.

Versione LEGGERA (adatta all'hosting cloud gratuito, poca memoria):
- Immagini e fotogrammi dei video: Google Gemini (AI con visione).
- Testo scritto a mano dall'utente: parser locale (senza chiamate all'AI).

Niente librerie pesanti (niente EasyOCR/PyTorch).
"""
import json
import re
import threading
import time

import config


class AIError(Exception):
    """Problema con l'AI (chiave non valida, limite raggiunto, rete)."""


# ----------------------------------------------------------------------
#  AI (Gemini) — lettura delle immagini
# ----------------------------------------------------------------------
_client = None
_ai_lock = threading.Lock()
_ai_ultima = [0.0]
_AI_MIN_INTERVALLO = 4.5  # ~15 richieste/minuto del piano gratuito
_last_debug = [""]

_AI_PROMPT = """Questa è la foto di una o più etichette di spedizione di pacchi, \
oppure lo schermo di un palmare/gestionale con indirizzi di consegna.

Estrai SOLO l'indirizzo del DESTINATARIO (la persona o azienda a cui va consegnato \
il pacco; spesso indicato con "Destinatario", "Consegnare a", "A:").
IGNORA: mittente, codici a barre, numeri di tracking/spedizione, peso, logo e nome \
del corriere, telefoni, prezzi.

Per ogni consegna fornisci l'indirizzo completo: via/piazza e numero civico, CAP, \
città e provincia se presenti.
Rispondi ESCLUSIVAMENTE con un array JSON di stringhe, senza altro testo.
Esempio: ["Via Roma 12, 20121 Milano MI"]
Se non vedi nessun indirizzo di destinatario, rispondi: []
"""


def image_has_ai() -> bool:
    """True se è configurata una chiave Gemini."""
    k = config.GEMINI_API_KEY
    return bool(k) and "incolla" not in k


def last_debug() -> str:
    """Info sull'ultima lettura (per la modalità /debug)."""
    return _last_debug[0]


def _get_ai_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _ai_addresses(image_bytes: bytes, mime_type: str = "image/jpeg"):
    """Estrae gli indirizzi da un'immagine con Gemini. Può sollevare AIError."""
    from google.genai import types

    client = _get_ai_client()
    with _ai_lock:
        attesa = _AI_MIN_INTERVALLO - (time.monotonic() - _ai_ultima[0])
        if attesa > 0:
            time.sleep(attesa)
        try:
            risposta = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes, mime_type=mime_type or "image/jpeg"
                    ),
                    _AI_PROMPT,
                ],
            )
            _ai_ultima[0] = time.monotonic()
        except Exception as e:  # noqa: BLE001
            _ai_ultima[0] = time.monotonic()
            raise _traduci_errore(e)
    return _parse_json_list(getattr(risposta, "text", "") or "")


def _traduci_errore(e: Exception) -> AIError:
    s = str(e).lower()
    if any(k in s for k in ("429", "resource_exhausted", "quota", "rate limit")):
        return AIError("Limite gratuito dell'AI raggiunto: aspetta circa un minuto.")
    if any(k in s for k in ("api key", "api_key", "permission", "401", "403", "unauthenticated")):
        return AIError("Chiave Gemini non valida: controlla GEMINI_API_KEY.")
    return AIError("AI non raggiungibile al momento.")


def _parse_json_list(text: str):
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            v = item.get("indirizzo") or item.get("address") or ""
            if v.strip():
                out.append(v.strip())
    return out


def image_addresses(image_bytes: bytes, mime_type: str = "image/jpeg"):
    """Legge gli indirizzi da una FOTO con l'AI."""
    indirizzi = _ai_addresses(image_bytes, mime_type)
    _last_debug[0] = "Metodo: AI (Gemini)\n" + "\n".join(indirizzi)
    return indirizzi


def frame_addresses(jpeg_bytes: bytes):
    """Legge gli indirizzi da un singolo fotogramma di video (JPEG) con l'AI."""
    return _ai_addresses(jpeg_bytes, "image/jpeg")


# ----------------------------------------------------------------------
#  Parser locale per il TESTO scritto dall'utente (senza AI)
# ----------------------------------------------------------------------
_STREET_KW = [
    "via", "viale", "v.le", "vle", "piazza", "piazzale", "p.za", "p.zza", "pza",
    "corso", "c.so", "cso", "vicolo", "largo", "strada", "borgo", "contrada",
    "località", "localita", "frazione", "fraz", "lungomare", "salita", "calata",
    "traversa", "riviera", "galleria", "passeggiata", "circonvallazione",
    "rotonda", "viottolo", "stradone", "rampa",
]
_STREET_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _STREET_KW) + r")\b", re.IGNORECASE
)
_CAP_RE = re.compile(r"\b\d{5}\b")


def _has_street(testo: str) -> bool:
    return bool(_STREET_RE.search(testo))


def parse_addresses(testo: str):
    """Individua gli indirizzi dentro un testo (per il testo digitato a mano)."""
    righe = [re.sub(r"\s+", " ", r).strip(" .,;:-|") for r in testo.splitlines()]
    righe = [r for r in righe if r]

    indirizzi = []
    buf = []
    for r in righe:
        ha_via = _has_street(r)
        ha_cap = bool(_CAP_RE.search(r))
        if ha_via and buf and _has_street(" ".join(buf)):
            indirizzi.append(" ".join(buf))
            buf = []
        if not buf and not (ha_via or ha_cap):
            continue
        buf.append(r)
        if ha_cap:
            indirizzi.append(" ".join(buf))
            buf = []
    coda = " ".join(buf)
    if buf and (_has_street(coda) or _CAP_RE.search(coda)):
        indirizzi.append(coda)

    if not indirizzi:
        indirizzi = [r for r in righe if _has_street(r) or _CAP_RE.search(r)]

    visti, risultato = set(), []
    for ind in indirizzi:
        chiave = ind.lower()
        if chiave not in visti:
            visti.add(chiave)
            risultato.append(ind)
    return risultato


def extract_from_text(testo: str):
    """Estrae gli indirizzi da un testo incollato/scritto dall'utente."""
    return parse_addresses(testo)

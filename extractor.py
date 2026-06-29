"""Lettura degli indirizzi — VERSIONE POTENTE (da usare sul PC).

- FOTO singole: prima l'AI (Gemini) se configurata, con RISERVA l'OCR offline
  (EasyOCR) se l'AI non è disponibile o non trova nulla.
- VIDEO: OCR offline (vedi video.py), senza limiti.
- TESTO scritto a mano: parser locale.

Usa le librerie pesanti (EasyOCR). Funziona anche senza chiave Gemini.
"""
import io
import json
import re
import threading
import time

import numpy as np
from PIL import Image, ImageOps

import config


class AIError(Exception):
    """Problema con l'AI (chiave non valida, limite, rete). Qui di solito si ripiega sull'OCR."""


# ----------------------------------------------------------------------
#  OCR offline (EasyOCR) — caricato in modo pigro
# ----------------------------------------------------------------------
_reader = None


def is_ocr_ready() -> bool:
    return _reader is not None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(config.ocr_langs_list(), gpu=False)
    return _reader


def _preprocess(image_bytes: bytes):
    img = Image.open(io.BytesIO(image_bytes))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    img = img.convert("RGB")
    w, h = img.size
    lato = max(w, h)
    if lato and lato < 1600:
        f = 1600.0 / lato
        img = img.resize((max(1, int(w * f)), max(1, int(h * f))))
    return np.array(img)


def read_image_text(image_bytes: bytes) -> str:
    arr = _preprocess(image_bytes)
    reader = _get_reader()
    blocchi = reader.readtext(arr, detail=0, paragraph=True)
    return "\n".join(blocchi)


def _upscale_array(arr):
    h, w = arr.shape[:2]
    lato = max(h, w)
    if lato and lato < 1600:
        f = 1600.0 / lato
        img = Image.fromarray(arr).resize((max(1, int(w * f)), max(1, int(h * f))))
        return np.array(img)
    return arr


def read_array_text(arr_rgb) -> str:
    """OCR di un fotogramma già in memoria (numpy RGB). Usato dai video."""
    reader = _get_reader()
    blocchi = reader.readtext(_upscale_array(arr_rgb), detail=0, paragraph=True)
    return "\n".join(blocchi)


# ----------------------------------------------------------------------
#  AI (Gemini) per le FOTO
# ----------------------------------------------------------------------
_client = None
_ai_lock = threading.Lock()
_ai_ultima = [0.0]
_AI_MIN_INTERVALLO = 4.5
_last_debug = [""]

_AI_PROMPT = """Questa immagine può essere:
(a) l'etichetta di un pacco, oppure
(b) lo schermo di un'app/palmare/navigatore con una LISTA di tappe o consegne.

Estrai gli indirizzi di consegna così:
- Se è un'ETICHETTA di pacco: prendi SOLO l'indirizzo del DESTINATARIO (ignora il \
mittente, i codici a barre, il tracking, il peso, il logo del corriere).
- Se è una LISTA di tappe/consegne: prendi l'indirizzo di OGNI tappa.

Per ogni indirizzo dai la forma completa: via/piazza/corso e numero civico, CAP, \
città e provincia se presenti. NON includere nomi di persona.
Rispondi ESCLUSIVAMENTE con un array JSON di stringhe, senza altro testo.
Esempio: ["Viale Europa 2, 41051 Castelnuovo Rangone MO", "Via Roma 12, 20121 Milano MI"]
Se non vedi nessun indirizzo, rispondi: []
"""


def image_has_ai() -> bool:
    k = config.GEMINI_API_KEY
    return bool(k) and "incolla" not in k


def last_debug() -> str:
    return _last_debug[0]


def _get_ai_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _ai_addresses(image_bytes: bytes, mime_type: str = "image/jpeg"):
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
        return AIError("limite gratuito dell'AI raggiunto")
    if any(k in s for k in ("api key", "api_key", "permission", "401", "403", "unauthenticated")):
        return AIError("chiave Gemini non valida")
    return AIError("AI non raggiungibile")


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
    """FOTO: prima l'AI (se configurata), con riserva l'OCR offline. Non solleva
    errori: se l'AI non va, ripiega sull'OCR."""
    if image_has_ai():
        try:
            indirizzi = _ai_addresses(image_bytes, mime_type)
            if indirizzi:
                _last_debug[0] = "Metodo: AI (Gemini)\n" + "\n".join(indirizzi)
                return indirizzi
        except AIError as e:
            _last_debug[0] = f"AI non disponibile ({e}); uso l'OCR offline."

    raw = read_image_text(image_bytes)
    metodo = "OCR offline" if not image_has_ai() else "OCR offline (riserva)"
    _last_debug[0] = f"Metodo: {metodo}\n{raw}"
    return parse_addresses(raw)


# ----------------------------------------------------------------------
#  Parser locale per il TESTO scritto dall'utente
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

_REC_MARKERS = [
    "destinatario", "consegnare a", "consegna a", "destinazione", "spedire a",
    "deliver to", "ship to",
]
_SND_MARKERS = ["mittente", "sender"]


def _has_street(testo: str) -> bool:
    return bool(_STREET_RE.search(testo))


def _prefer_recipient(righe):
    basse = [r.lower() for r in righe]
    inizio = 0
    for i, r in enumerate(basse):
        if any(m in r for m in _REC_MARKERS):
            inizio = i
            break
    selezione = righe[inizio:] if inizio else list(righe)

    risultato, salta = [], False
    for r in selezione:
        rl = r.lower()
        ha_cap = bool(_CAP_RE.search(r))
        if any(m in rl for m in _SND_MARKERS):
            # inizio del blocco mittente: se il CAP del mittente è GIÀ su questa
            # riga, il blocco finisce qui (non saltare oltre, o si perde il
            # destinatario); altrimenti salta fino al prossimo CAP.
            salta = not ha_cap
            continue
        if salta:
            if ha_cap:
                salta = False
            continue
        risultato.append(r)
    return risultato or selezione or righe


def _clean_address(addr: str) -> str:
    """Toglie il nome di persona prima della via (es. 'Paola Riva Via Adige 5' ->
    'Via Adige 5') e la parola 'Italy/Italia' finale, per aiutare il geocoding."""
    m = _STREET_RE.search(addr)
    if m and m.start() > 0:
        addr = addr[m.start():].strip()
    addr = re.sub(r"[\s,]+(italy|italia)\s*$", "", addr, flags=re.IGNORECASE).strip()
    return addr


def parse_addresses(testo: str):
    righe = [re.sub(r"\s+", " ", r).strip(" .,;:-|") for r in testo.splitlines()]
    righe = [r for r in righe if r]
    righe = _prefer_recipient(righe)

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
        ind = _clean_address(ind)
        chiave = ind.lower()
        if chiave not in visti:
            visti.add(chiave)
            risultato.append(ind)
    return risultato


def extract_from_text(testo: str):
    return parse_addresses(testo)

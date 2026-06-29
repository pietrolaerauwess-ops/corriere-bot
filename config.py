"""Configurazione — VERSIONE POTENTE (da usare sul PC).

Differenza dalla versione cloud: l'AI (Gemini) è OPZIONALE, perché c'è l'OCR
offline come riserva. Se non metti la chiave Gemini, il bot funziona lo stesso
(legge tutto con l'OCR offline)."""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

# Chiave Google Gemini (OPZIONALE qui): se presente, le FOTO usano l'AI.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

# OCR offline (riserva per le foto e lettura dei video)
OCR_LANGS = os.getenv("OCR_LANGS", "it,en").strip()

# Geocoding e ottimizzazione
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "it").strip()
NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "").strip()
MAX_STOPS_PER_LINK = int(os.getenv("MAX_STOPS_PER_LINK", "10"))

# Calcolo del percorso sulle strade reali (OSRM), con riserva linea d'aria.
USE_ROADS = os.getenv("USE_ROADS", "1").strip() not in ("0", "false", "no", "")
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").strip()


def ocr_langs_list():
    return [x.strip() for x in OCR_LANGS.split(",") if x.strip()] or ["it", "en"]


def user_agent():
    if NOMINATIM_EMAIL:
        return f"corriere-bot/1.0 ({NOMINATIM_EMAIL})"
    return "corriere-bot/1.0"


def check():
    """Qui serve solo il token Telegram (l'AI è opzionale grazie all'OCR offline)."""
    problemi = []
    if not TELEGRAM_TOKEN or "incolla" in TELEGRAM_TOKEN:
        problemi.append("Manca TELEGRAM_TOKEN nel file .env")
    return problemi

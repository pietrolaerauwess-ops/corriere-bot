"""Caricamento della configurazione dal file .env (o dalle variabili d'ambiente)."""
import os
from dotenv import load_dotenv

load_dotenv()  # carica .env se presente (in locale); sul cloud si usano le variabili

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

# Chiave Google Gemini: legge le foto e i fotogrammi dei video.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

# Geocoding e ottimizzazione
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "it").strip()
NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "").strip()
MAX_STOPS_PER_LINK = int(os.getenv("MAX_STOPS_PER_LINK", "10"))

# Calcolo del percorso sulle strade reali (OSRM). Se non disponibile, il bot usa
# automaticamente la distanza in linea d'aria.
USE_ROADS = os.getenv("USE_ROADS", "1").strip() not in ("0", "false", "no", "")
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").strip()


def user_agent():
    """Identificativo richiesto dal servizio gratuito OpenStreetMap/Nominatim."""
    if NOMINATIM_EMAIL:
        return f"corriere-bot/1.0 ({NOMINATIM_EMAIL})"
    return "corriere-bot/1.0"


def check():
    """Controlla che le chiavi obbligatorie siano presenti.
    Restituisce una lista di messaggi di errore (vuota se va tutto bene)."""
    problemi = []
    if not TELEGRAM_TOKEN or "incolla" in TELEGRAM_TOKEN:
        problemi.append("Manca TELEGRAM_TOKEN")
    if not GEMINI_API_KEY or "incolla" in GEMINI_API_KEY:
        problemi.append("Manca GEMINI_API_KEY")
    return problemi

"""Conversione indirizzo -> coordinate GPS usando OpenStreetMap / Nominatim.

Servizio gratuito e senza chiave. Per rispettare le regole d'uso teniamo
al massimo 1 richiesta al secondo e mettiamo in cache i risultati.
"""
import threading
import time

import requests

import config

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_MIN_INTERVALLO = 1.1  # secondi tra una richiesta e l'altra (regola di Nominatim)

_lock = threading.Lock()
_ultima_chiamata = [0.0]
_cache = {}


def _short(display_name: str) -> str:
    """Accorcia l'indirizzo restituito da OpenStreetMap per renderlo leggibile."""
    parti = [p.strip() for p in display_name.split(",")]
    return ", ".join(parti[:4]) if len(parti) > 4 else display_name


def geocode(indirizzo: str):
    """Restituisce un dizionario con coordinate e indirizzo normalizzato,
    oppure None se l'indirizzo non viene trovato."""
    chiave = indirizzo.strip().lower()
    if chiave in _cache:
        return _cache[chiave]

    with _lock:
        attesa = _MIN_INTERVALLO - (time.monotonic() - _ultima_chiamata[0])
        if attesa > 0:
            time.sleep(attesa)
        try:
            risposta = requests.get(
                _NOMINATIM_URL,
                params={
                    "q": indirizzo,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": config.DEFAULT_REGION,
                    "addressdetails": 0,
                },
                headers={"User-Agent": config.user_agent()},
                timeout=15,
            )
            _ultima_chiamata[0] = time.monotonic()
            dati = risposta.json()
        except Exception:
            _ultima_chiamata[0] = time.monotonic()
            return None

    if not dati:
        _cache[chiave] = None
        return None

    primo = dati[0]
    geo = {
        "input": indirizzo,
        "formatted": _short(primo.get("display_name", indirizzo)),
        "lat": float(primo["lat"]),
        "lng": float(primo["lon"]),
    }
    _cache[chiave] = geo
    return geo

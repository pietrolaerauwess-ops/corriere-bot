"""Conversione indirizzo -> coordinate GPS usando OpenStreetMap / Nominatim.

Servizio gratuito e senza chiave. Rispettiamo le regole (max ~1 richiesta/sec) e
mettiamo in cache i risultati. Proviamo anche varianti dell'indirizzo (es. togliendo
la lettera dal numero civico "2b" -> "2") per trovarlo più facilmente.
"""
import logging
import re
import threading
import time

import requests

import config

log = logging.getLogger("geocoder")

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_MIN_INTERVALLO = 1.1  # secondi tra una richiesta e l'altra (regola di Nominatim)

_lock = threading.Lock()
_ultima_chiamata = [0.0]
_cache = {}


def _short(display_name: str) -> str:
    """Accorcia l'indirizzo restituito da OpenStreetMap per renderlo leggibile."""
    parti = [p.strip() for p in display_name.split(",")]
    return ", ".join(parti[:4]) if len(parti) > 4 else display_name


def _query(q: str):
    """Una singola richiesta a Nominatim (con rate-limit). Restituisce la lista
    dei risultati, oppure None in caso di errore/blocco."""
    with _lock:
        attesa = _MIN_INTERVALLO - (time.monotonic() - _ultima_chiamata[0])
        if attesa > 0:
            time.sleep(attesa)
        try:
            risposta = requests.get(
                _NOMINATIM_URL,
                params={
                    "q": q,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": config.DEFAULT_REGION,
                    "addressdetails": 0,
                },
                headers={"User-Agent": config.user_agent()},
                timeout=15,
            )
            _ultima_chiamata[0] = time.monotonic()
        except Exception as e:  # noqa: BLE001
            _ultima_chiamata[0] = time.monotonic()
            log.warning("Errore di rete nel geocoding di '%s': %s", q, e)
            return None

    if risposta.status_code != 200:
        log.warning("Nominatim ha risposto %s per: %s", risposta.status_code, q)
        return None
    try:
        return risposta.json()
    except Exception:  # noqa: BLE001
        return None


def _varianti(indirizzo: str):
    """Genera alcune varianti dell'indirizzo per aumentare le probabilità."""
    varianti = [indirizzo]
    # numero civico con lettera attaccata: "2b" -> "2"
    senza_lettera = re.sub(r"\b(\d+)\s*[A-Za-z]\b", r"\1", indirizzo)
    if senza_lettera != indirizzo:
        varianti.append(senza_lettera)
    return varianti


def geocode(indirizzo: str):
    """Restituisce un dizionario con coordinate e indirizzo normalizzato,
    oppure None se l'indirizzo non viene trovato."""
    chiave = indirizzo.strip().lower()
    if chiave in _cache:
        return _cache[chiave]

    for q in _varianti(indirizzo):
        dati = _query(q)
        if dati:
            primo = dati[0]
            geo = {
                "input": indirizzo,
                "formatted": _short(primo.get("display_name", indirizzo)),
                "lat": float(primo["lat"]),
                "lng": float(primo["lon"]),
            }
            _cache[chiave] = geo
            return geo

    _cache[chiave] = None
    return None

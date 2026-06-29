"""Costruzione dei link di navigazione di Google Maps.

L'app di Google Maps accetta poche tappe per percorso, quindi un giro lungo
viene spezzato in piu' link consecutivi. L'ultima tappa di un link e' la
partenza del link successivo, cosi' la navigazione resta continua.
"""
import urllib.parse


def _dir_url(segmento):
    """Crea un URL di indicazioni stradali per un gruppo di punti."""
    origin = f"{segmento[0]['lat']},{segmento[0]['lng']}"
    dest = f"{segmento[-1]['lat']},{segmento[-1]['lng']}"
    parametri = [
        "api=1",
        f"origin={origin}",
        f"destination={dest}",
        "travelmode=driving",
    ]
    intermedi = segmento[1:-1]
    if intermedi:
        waypoints = "|".join(f"{p['lat']},{p['lng']}" for p in intermedi)
        parametri.append("waypoints=" + urllib.parse.quote(waypoints, safe="|,"))
    return "https://www.google.com/maps/dir/?" + "&".join(parametri)


def build_links(punti_ordinati, max_per_link=10):
    """Spezza la lista ordinata di punti in piu' link Google Maps.
    Restituisce una lista di URL."""
    if len(punti_ordinati) < 2:
        return []
    if max_per_link < 2:
        max_per_link = 2

    links = []
    i = 0
    n = len(punti_ordinati)
    while i < n - 1:
        segmento = punti_ordinati[i : i + max_per_link]
        links.append(_dir_url(segmento))
        i += max_per_link - 1  # sovrappone l'ultimo punto come partenza del prossimo
    return links

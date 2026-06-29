"""Ottimizzazione del percorso (problema del commesso viaggiatore) con OR-Tools.

Distanze tra i punti:
- se possibile, tempi reali di percorrenza sulle STRADE (servizio gratuito OSRM);
- altrimenti, distanza in linea d'aria (Haversine) come riserva.

Percorso "aperto": si parte dal primo punto (la partenza) e si termina all'ultima
consegna, SENZA tornare al punto di partenza.
"""
import math

import requests
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import config

_last_method = ["linea d'aria"]


def last_method() -> str:
    """Come sono state calcolate le distanze nell'ultimo percorso."""
    return _last_method[0]


def _haversine_m(a, b):
    """Distanza in metri in linea d'aria tra due punti {lat, lng}."""
    R = 6_371_000
    lat1, lng1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lng2 = math.radians(b["lat"]), math.radians(b["lng"])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _haversine_matrix(points):
    n = len(points)
    return [
        [0 if i == j else int(_haversine_m(points[i], points[j])) for j in range(n)]
        for i in range(n)
    ]


def _osrm_matrix(points):
    """Matrice dei tempi reali di percorrenza (secondi) via OSRM, o None se fallisce."""
    if not config.USE_ROADS or len(points) > 100:
        return None
    coords = ";".join(f"{p['lng']},{p['lat']}" for p in points)
    url = f"{config.OSRM_URL}/table/v1/driving/{coords}?annotations=duration"
    try:
        risposta = requests.get(url, timeout=30)
        dati = risposta.json()
    except Exception:
        return None
    if dati.get("code") != "Ok" or "durations" not in dati:
        return None

    durations = dati["durations"]
    n = len(points)
    matrice = []
    for i in range(n):
        riga = []
        for j in range(n):
            v = durations[i][j]
            if v is None:  # nessuna strada trovata: penalità alta
                riga.append(0 if i == j else 10_000_000)
            else:
                riga.append(int(v))
        matrice.append(riga)
    return matrice


def solve(points):
    """Riceve una lista di punti {lat, lng}; il punto 0 è la partenza.
    Restituisce la lista degli indici nell'ordine ottimale di visita."""
    n = len(points)
    if n <= 2:
        _last_method[0] = "—"
        return list(range(n))

    base = _osrm_matrix(points)
    if base is not None:
        _last_method[0] = "strade reali"
    else:
        base = _haversine_matrix(points)
        _last_method[0] = "linea d'aria"

    # Nodo fittizio finale a distanza 0 da tutti: percorso aperto (non torna indietro)
    size = n + 1
    dummy = n
    matrix = [[0] * size for _ in range(size)]
    for i in range(n):
        for j in range(n):
            matrix[i][j] = base[i][j]

    manager = pywrapcp.RoutingIndexManager(size, 1, [0], [dummy])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(min(30, max(5, n // 4)))

    solution = routing.SolveWithParameters(params)
    if not solution:
        return list(range(n))

    ordine = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != dummy:
            ordine.append(node)
        index = solution.Value(routing.NextVar(index))
    return ordine

"""Estrazione indirizzi da VIDEO — VERSIONE POTENTE (OCR offline, senza limiti).

Prende un fotogramma ogni tot secondi, salta quelli quasi identici (quando non
stai scorrendo), legge con l'OCR offline e unisce gli indirizzi togliendo i doppioni.
"""
import os
import tempfile

import cv2
import numpy as np

import extractor


def addresses_from_video(video_bytes, every_seconds=1.2, max_frames=120):
    """Restituisce la lista degli indirizzi trovati nel video (senza doppioni)."""
    fd, percorso = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    with open(percorso, "wb") as f:
        f.write(video_bytes)

    try:
        cap = cv2.VideoCapture(percorso)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        passo = max(1, int(fps * every_seconds))

        visti, risultato = set(), []
        prev_small = None
        idx = letti = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % passo == 0:
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 64))
                if prev_small is not None:
                    diff = float(np.mean(np.abs(small.astype(int) - prev_small.astype(int))))
                    if diff < 3.0:
                        idx += 1
                        continue
                prev_small = small

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                testo = extractor.read_array_text(rgb)
                for ind in extractor.parse_addresses(testo):
                    chiave = ind.lower()
                    if chiave not in visti:
                        visti.add(chiave)
                        risultato.append(ind)

                letti += 1
                if letti >= max_frames:
                    break
            idx += 1

        cap.release()
        return risultato
    finally:
        try:
            os.remove(percorso)
        except OSError:
            pass

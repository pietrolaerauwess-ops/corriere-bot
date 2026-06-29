"""Estrazione degli indirizzi da un VIDEO (es. lo scorrimento delle tappe sul
palmare di Poste), così non serve fare tanti screenshot.

Versione leggera: prende alcuni fotogrammi (uno ogni tot secondi), salta quelli
quasi identici (quando non stai scorrendo) e li fa leggere all'AI Gemini.
"""
import os
import tempfile

import cv2
import numpy as np

import extractor


def addresses_from_video(video_bytes, every_seconds=1.2, max_frames=25):
    """Restituisce la lista degli indirizzi trovati nel video (senza doppioni).

    Solleva extractor.AIError se l'AI non è disponibile fin da subito.
    """
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
        errore = None

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % passo == 0:
                # salta i fotogrammi quasi identici (nessuno scorrimento)
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 64))
                if prev_small is not None:
                    diff = float(np.mean(np.abs(small.astype(int) - prev_small.astype(int))))
                    if diff < 3.0:
                        idx += 1
                        continue
                prev_small = small

                ok_jpg, buf = cv2.imencode(".jpg", frame)
                if ok_jpg:
                    try:
                        for ind in extractor.frame_addresses(buf.tobytes()):
                            chiave = ind.lower()
                            if chiave not in visti:
                                visti.add(chiave)
                                risultato.append(ind)
                    except extractor.AIError as e:
                        errore = e
                        break  # es. limite AI raggiunto: ci fermiamo con quel che abbiamo

                letti += 1
                if letti >= max_frames:
                    break
            idx += 1

        cap.release()

        if errore is not None and not risultato:
            raise errore  # nessun risultato e l'AI non va: segnaliamo l'errore
        return risultato
    finally:
        try:
            os.remove(percorso)
        except OSError:
            pass

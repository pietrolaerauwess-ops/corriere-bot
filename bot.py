"""Bot Telegram per corrieri (versione 100% gratuita):
riceve foto/screenshot/testo con indirizzi, li legge con OCR locale,
li trasforma in coordinate (OpenStreetMap) e crea un percorso ottimizzato
con i link di Google Maps.

Avvio:  python bot.py
"""
import asyncio
import logging
import os
import threading

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import extractor
import geocoder
import maps_links
import optimizer
import video

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("corriere-bot")

# Limite di Telegram: 4096 caratteri per messaggio. Stiamo un po' sotto.
_MAX_MSG = 3800


async def invia_lungo(update, righe, **kwargs):
    """Invia un elenco di righe spezzandolo in più messaggi se troppo lungo."""
    buffer = ""
    for riga in righe:
        if len(buffer) + len(riga) + 1 > _MAX_MSG:
            if buffer:
                await update.message.reply_text(buffer, **kwargs)
            buffer = riga
        else:
            buffer = riga if not buffer else buffer + "\n" + riga
    if buffer:
        await update.message.reply_text(buffer, **kwargs)

# Tastiera con i comandi principali sempre a portata di mano
TASTIERA = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📍 Invia posizione di partenza", request_location=True)],
        ["📋 Lista", "🚀 Ottimizza"],
        ["🗑 Azzera", "ℹ️ Aiuto"],
    ],
    resize_keyboard=True,
)


TESTO_AIUTO = (
    "ℹ️ *COME SI USA — in 3 passi*\n\n"
    "*1) Da dove parti*\n"
    "Premi 📍 per inviare la posizione, oppure scrivi:\n"
    "`/partenza Via Roma 1, Milano`\n\n"
    "*2) Manda gli indirizzi*\n"
    "Puoi mandarmeli in 4 modi (anche più insieme): \n"
    "• 📷 *foto dei pacchi*\n"
    "• 🖼 *screenshot* del gestionale\n"
    "• ✍️ *testo* scritto a mano\n"
    "• 🎬 *video*: scorri le tappe sul palmare e mandami la registrazione, "
    "gli indirizzi li leggo io (così eviti tanti screenshot).\n"
    "Ti dico sempre quante consegne ho aggiunto, e tolgo i doppioni.\n\n"
    "*3) Ottimizza*\n"
    "Premi 🚀 Ottimizza: ti do l'elenco già in ordine e i link di Google Maps. "
    "Apri un link, fai quelle consegne, poi apri il successivo.\n\n"
    "*Comandi utili*\n"
    "📋 Lista — vedi le consegne inserite\n"
    "🗑 Azzera — cancella tutto e ricomincia\n"
    "/rimuovi 3 — toglie la consegna numero 3\n\n"
    "🎬 *Come fare il video delle tappe*\n"
    "• Apri sul palmare la lista delle consegne con gli indirizzi.\n"
    "• Avvia la registrazione e *scorri lentamente* dall'alto verso il basso.\n"
    "• Fai una breve pausa su ogni schermata, così il testo si legge bene.\n"
    "• Tieni il palmare *fermo e a fuoco*, evita riflessi e ombre sullo schermo.\n"
    "• Tienilo *corto* (sotto i ~20 MB): se hai tante tappe, fai due video.\n\n"
    "📷 *Consiglio per le foto:* inquadra l'etichetta dritta, a fuoco, "
    "con CAP e città ben leggibili."
)


# ----------------------------------------------------------------------
#  Comandi
# ----------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Ciao! Sono il tuo assistente per le consegne.\n\n"
        "Ecco come funziona:\n"
        "1️⃣ Inviami la tua *posizione di partenza* (pulsante 📍 in basso) "
        "oppure scrivi `/partenza` seguito dall'indirizzo da cui parti.\n"
        "2️⃣ Mandami gli indirizzi dei destinatari come *foto dei pacchi, screenshot o testo*. "
        "Oppure, ancora più comodo, un *video*: scorri le tappe sul palmare e mandami "
        "la registrazione, gli indirizzi li leggo io.\n"
        "3️⃣ Premi *🚀 Ottimizza* e ti restituisco il percorso migliore con i link di Google Maps.\n\n"
        "Premi *ℹ️ Aiuto* (o scrivi /aiuto) per la guida rapida e i consigli sul video.",
        parse_mode="Markdown",
        reply_markup=TASTIERA,
    )


async def cmd_aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        TESTO_AIUTO, parse_mode="Markdown", reply_markup=TASTIERA
    )


async def cmd_partenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/partenza Via Roma 1, Milano  -> imposta il punto di partenza per indirizzo."""
    testo = " ".join(context.args).strip()
    if not testo:
        await update.message.reply_text(
            "Scrivi l'indirizzo dopo il comando, così:\n"
            "/partenza Via Roma 1, 20121 Milano\n\n"
            "Oppure usa il pulsante 📍 per la tua posizione attuale.",
            reply_markup=TASTIERA,
        )
        return
    await update.message.chat.send_action("typing")
    geo = await asyncio.to_thread(geocoder.geocode, testo)
    if not geo:
        await update.message.reply_text(
            "Non sono riuscito a trovare quell'indirizzo di partenza. "
            "Controlla che sia completo (via, numero, CAP, città).",
            reply_markup=TASTIERA,
        )
        return
    context.user_data["start"] = geo
    await update.message.reply_text(
        f"🏁 Partenza impostata: {geo['formatted']}", reply_markup=TASTIERA
    )


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attiva/disattiva la visualizzazione del testo grezzo letto dalle immagini."""
    nuovo = not context.user_data.get("debug", False)
    context.user_data["debug"] = nuovo
    if nuovo:
        msg = (
            "🧪 Modalità diagnostica ATTIVA.\n"
            "Da ora, per ogni immagine ti mostro anche il testo grezzo che ho letto. "
            "Riinviala per disattivare con /debug."
        )
    else:
        msg = "Modalità diagnostica disattivata."
    await update.message.reply_text(msg, reply_markup=TASTIERA)


async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stops = context.user_data.get("stops", [])
    start = context.user_data.get("start")
    righe = []
    if start:
        righe.append(f"🏁 Partenza: {start['formatted']}")
    if not stops:
        righe.append("Nessun indirizzo ancora inserito.")
    else:
        righe.append(f"\n📦 {len(stops)} consegne:")
        for i, s in enumerate(stops, 1):
            righe.append(f"{i}. {s['formatted']}")
    await invia_lungo(update, righe, reply_markup=TASTIERA)


async def cmd_azzera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stops"] = []
    context.user_data.pop("start", None)
    await update.message.reply_text(
        "🗑 Fatto. Ho azzerato partenza e consegne.", reply_markup=TASTIERA
    )


async def cmd_rimuovi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rimuovi N  -> toglie la consegna numero N dalla lista."""
    stops = context.user_data.get("stops", [])
    try:
        n = int(context.args[0])
        rimosso = stops.pop(n - 1)
        await update.message.reply_text(
            f"❌ Rimossa: {rimosso['formatted']}", reply_markup=TASTIERA
        )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Usa il comando così: /rimuovi 3  (per togliere la consegna numero 3). "
            "Vedi i numeri con /lista.",
            reply_markup=TASTIERA,
        )


# ----------------------------------------------------------------------
#  Ricezione input
# ----------------------------------------------------------------------
async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    context.user_data["start"] = {
        "input": "posizione GPS",
        "formatted": "La tua posizione attuale",
        "lat": loc.latitude,
        "lng": loc.longitude,
    }
    await update.message.reply_text(
        "📍 Partenza impostata sulla tua posizione attuale.\n"
        "Ora mandami gli indirizzi delle consegne (foto, screenshot o testo).",
        reply_markup=TASTIERA,
    )


async def _processa_immagine(update, context, dati, mime_type="image/jpeg"):
    await update.message.reply_text("🔎 Sto leggendo l'immagine con l'AI...")
    try:
        indirizzi = await asyncio.to_thread(
            extractor.image_addresses, dati, mime_type
        )
    except extractor.AIError as e:
        await update.message.reply_text("⚠️ " + str(e), reply_markup=TASTIERA)
        return
    if context.user_data.get("debug"):
        await invia_lungo(update, ["🧪 (debug)", extractor.last_debug() or "(vuoto)"])
    if not indirizzi:
        await update.message.reply_text(
            "❌ Non ho riconosciuto l'indirizzo del destinatario in questa immagine.\n"
            "Inquadra l'etichetta dritta e a fuoco, con CAP e città ben visibili.",
            reply_markup=TASTIERA,
        )
        return
    await _aggiungi_indirizzi(update, context, indirizzi)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    foto = update.message.photo[-1]  # la versione a risoluzione più alta
    file = await foto.get_file()
    dati = bytes(await file.download_as_bytearray())
    await _processa_immagine(update, context, dati)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    mime = doc.mime_type or ""
    if mime.startswith("video/"):
        return await _processa_video(update, context, doc)
    if not mime.startswith("image/"):
        await update.message.reply_text(
            "Posso leggere immagini, video o testo. Inviami una foto, un video "
            "delle tappe o scrivi gli indirizzi."
        )
        return
    await update.message.chat.send_action("typing")
    file = await doc.get_file()
    dati = bytes(await file.download_as_bytearray())
    await _processa_immagine(update, context, dati)


async def _processa_video(update, context, oggetto):
    """Scarica un video e ne estrae gli indirizzi delle tappe (fotogramma per fotogramma)."""
    dimensione = getattr(oggetto, "file_size", None)
    if dimensione and dimensione > 20 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ Il video è troppo grande (Telegram permette ai bot max ~20 MB).\n"
            "Registralo più corto o a risoluzione più bassa, oppure dividilo in due.",
            reply_markup=TASTIERA,
        )
        return
    await update.message.chat.send_action("typing")
    await update.message.reply_text(
        "🎬 Sto analizzando il video tappa per tappa... può volerci un minuto o due."
    )
    try:
        file = await oggetto.get_file()
        dati = bytes(await file.download_as_bytearray())
    except Exception:
        await update.message.reply_text(
            "⚠️ Non sono riuscito a scaricare il video (forse troppo grande). "
            "Prova con un video più corto.",
            reply_markup=TASTIERA,
        )
        return
    try:
        indirizzi = await asyncio.to_thread(video.addresses_from_video, dati)
    except extractor.AIError as e:
        await update.message.reply_text("⚠️ " + str(e), reply_markup=TASTIERA)
        return
    if not indirizzi:
        await update.message.reply_text(
            "❌ Non ho trovato indirizzi nel video.\n"
            "Consigli: scorri le tappe più lentamente, tieni il palmare fermo e a "
            "fuoco, evita riflessi sullo schermo.",
            reply_markup=TASTIERA,
        )
        return
    await _aggiungi_indirizzi(update, context, indirizzi)


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _processa_video(update, context, update.message.video)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = (update.message.text or "").strip()

    # Pulsanti della tastiera
    if testo.startswith("📋"):
        return await cmd_lista(update, context)
    if testo.startswith("🚀"):
        return await cmd_ottimizza(update, context)
    if testo.startswith("🗑"):
        return await cmd_azzera(update, context)
    if testo.startswith("ℹ️") or testo.lower() == "aiuto":
        return await cmd_aiuto(update, context)

    await update.message.chat.send_action("typing")
    indirizzi = await asyncio.to_thread(extractor.extract_from_text, testo)
    if not indirizzi:
        await update.message.reply_text(
            "Non ho trovato indirizzi in questo messaggio. "
            "Prova a inviare una foto più chiara o a scrivere l'indirizzo completo "
            "(via, numero, CAP, città).\n\n"
            "Per impostare la partenza usa il pulsante 📍 oppure /partenza.",
            reply_markup=TASTIERA,
        )
        return
    await _aggiungi_indirizzi(update, context, indirizzi)


def _gia_presente(stops, geo):
    """True se una consegna nello stesso punto (stesse coordinate) è già in lista."""
    for s in stops:
        if round(s["lat"], 5) == round(geo["lat"], 5) and round(
            s["lng"], 5
        ) == round(geo["lng"], 5):
            return True
    return False


async def _aggiungi_indirizzi(update, context, indirizzi):
    """Geocodifica gli indirizzi trovati e li aggiunge alla lista consegne."""
    if not indirizzi:
        await update.message.reply_text(
            "Non ho trovato indirizzi. Riprova con un'immagine più chiara "
            "o scrivili a mano.",
            reply_markup=TASTIERA,
        )
        return

    stops = context.user_data.setdefault("stops", [])
    aggiunti, falliti, doppioni = [], [], 0
    for indirizzo in indirizzi:
        geo = await asyncio.to_thread(geocoder.geocode, indirizzo)
        if not geo:
            falliti.append(indirizzo)
        elif _gia_presente(stops, geo):
            doppioni += 1  # già in lista (capita coi video che ripetono le tappe)
        else:
            stops.append(geo)
            aggiunti.append(geo)

    righe = [f"✅ Aggiunte {len(aggiunti)} consegne (totale: {len(stops)})."]
    if doppioni:
        righe.append(f"   (ho saltato {doppioni} doppioni)")
    for g in aggiunti:
        righe.append(f"  • {g['formatted']}")
    if falliti:
        righe.append("\n⚠️ Non sono riuscito a localizzare questi (controllali):")
        for f in falliti:
            righe.append(f"  • {f}")
    righe.append("\nQuando hai finito premi 🚀 Ottimizza.")
    await invia_lungo(update, righe, reply_markup=TASTIERA)


# ----------------------------------------------------------------------
#  Ottimizzazione e risultato
# ----------------------------------------------------------------------
async def cmd_ottimizza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stops = context.user_data.get("stops", [])
    start = context.user_data.get("start")

    if not stops:
        await update.message.reply_text(
            "Non hai ancora inserito consegne. Mandami foto o testo con gli indirizzi.",
            reply_markup=TASTIERA,
        )
        return

    # Costruisce l'elenco dei punti: la partenza (se c'è) è il punto 0
    punti = []
    partenza_esplicita = start is not None
    if partenza_esplicita:
        punti.append(start)
    punti.extend(stops)

    if not partenza_esplicita:
        await update.message.reply_text(
            "ℹ️ Non hai impostato una partenza: userò la prima consegna come punto di partenza.\n"
            "Per risultati migliori, invia la tua posizione col pulsante in basso."
        )

    await update.message.reply_text("⏳ Sto calcolando il percorso migliore...")

    ordine = await asyncio.to_thread(optimizer.solve, punti)
    punti_ordinati = [punti[i] for i in ordine]

    metodo = optimizer.last_method()
    nota = "🛣 calcolato sulle strade reali" if metodo == "strade reali" else "📏 calcolato in linea d'aria"

    # Elenco testuale numerato (testo semplice: gli indirizzi possono contenere
    # caratteri che romperebbero la formattazione Markdown)
    righe = [f"🗺 PERCORSO OTTIMIZZATO ({nota})\n"]
    for i, p in enumerate(punti_ordinati):
        if i == 0 and partenza_esplicita:
            righe.append(f"🏁 Partenza — {p['formatted']}")
        else:
            numero = i if partenza_esplicita else i + 1
            righe.append(f"{numero}. {p['formatted']}")
    await invia_lungo(update, righe)

    # Link di navigazione (spezzati in più tappe)
    links = maps_links.build_links(punti_ordinati, config.MAX_STOPS_PER_LINK)
    if not links:
        return

    intro = (
        f"🧭 Navigazione in {len(links)} "
        f"{'tratta' if len(links) == 1 else 'tratte'} "
        "(apri un link, completalo, poi apri il successivo):"
    )
    await update.message.reply_text(intro)
    for n, link in enumerate(links, 1):
        await update.message.reply_text(f"➡️ Tratta {n}:\n{link}")


# ----------------------------------------------------------------------
#  Gestione errori
# ----------------------------------------------------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Errore durante la gestione di un aggiornamento", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Si è verificato un problema temporaneo. Riprova tra un momento. "
                "Se continua, controlla la connessione o il token nel file .env."
            )
        except Exception:
            pass


# ----------------------------------------------------------------------
#  "Battito cardiaco" per l'hosting cloud (Koyeb): mini server web che
#  risponde ai controlli e permette di tenere sveglio il bot (keep-alive).
#  Si attiva SOLO online, quando è impostata la variabile d'ambiente PORT.
# ----------------------------------------------------------------------
def _avvia_keepalive():
    porta = os.getenv("PORT")
    if not porta:
        return  # in locale non serve

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass  # silenzia i log delle richieste

    def _serve():
        HTTPServer(("0.0.0.0", int(porta)), _Health).serve_forever()

    threading.Thread(target=_serve, daemon=True).start()
    print(f"🌐 Mini server attivo sulla porta {porta} (keep-alive).")


# ----------------------------------------------------------------------
#  Avvio
# ----------------------------------------------------------------------
def main():
    problemi = config.check()
    if problemi:
        print("\n❌ Configurazione incompleta:\n")
        for p in problemi:
            print("   -", p)
        print(
            "\nApri il file .env e inserisci le chiavi mancanti, poi riavvia.\n"
            "Vedi la GUIDA.md per le istruzioni passo-passo.\n"
        )
        return

    # Python 3.13+ non crea più automaticamente un event loop nel thread
    # principale: lo prepariamo noi, altrimenti run_polling va in errore
    # ("There is no current event loop in thread 'MainThread'").
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("aiuto", cmd_aiuto))
    app.add_handler(CommandHandler("help", cmd_aiuto))
    app.add_handler(CommandHandler("partenza", cmd_partenza))
    app.add_handler(CommandHandler("lista", cmd_lista))
    app.add_handler(CommandHandler("ottimizza", cmd_ottimizza))
    app.add_handler(CommandHandler("azzera", cmd_azzera))
    app.add_handler(CommandHandler("rimuovi", cmd_rimuovi))
    app.add_handler(CommandHandler("debug", cmd_debug))

    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document))
    app.add_handler(MessageHandler(filters.Document.VIDEO, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(on_error)

    _avvia_keepalive()  # attivo solo sul cloud (quando c'è la variabile PORT)

    print("✅ Bot avviato! Apri Telegram e scrivi /start al tuo bot.")
    print("   (Per fermarlo: chiudi questa finestra o premi Ctrl+C)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

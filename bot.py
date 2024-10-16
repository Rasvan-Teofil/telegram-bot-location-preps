import csv
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# Logging-Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Kleingruppen und Putztermine
kleingruppen = ['Gentlemans', 'International 1', 'International 2', 'Morning Prayer', 'Youth']
putztermine = {
    'Gentlemans': datetime(2024, 10, 20, 9, 0),
    'International 1': datetime(2024, 10, 15, 17, 13),
    'International 2': datetime(2024, 10, 22, 9, 0),
    'Morning Prayer': datetime(2024, 10, 24, 9, 0),
    'Youth': datetime(2024, 10, 25, 9, 0),
}

user_group = {}
scheduler = BackgroundScheduler()
loop = None  # Globaler Event-Loop für den Hauptthread

# Funktion zum Laden der CSV-Datei und Aktualisieren der Daten
def update_putztermine_from_csv(file_path):
    global kleingruppen, putztermine
    try:
        with open(file_path, mode='r') as file:
            csv_reader = csv.DictReader(file)
            kleingruppen = []  # Reset der Kleingruppen-Liste
            putztermine.clear()  # Clear the existing putztermine dictionary

            logging.info(f"CSV-Datei wird geladen: {file_path}")

            for row in csv_reader:
                gruppe = row['Gruppe']
                try:
                    termin = datetime.strptime(row['Termin'], '%Y-%m-%d %H:%M')
                    if termin < datetime.now():
                        logging.warning(f"Termin für {gruppe} liegt in der Vergangenheit: {termin}")
                        continue
                    kleingruppen.append(gruppe)  # Gruppe aus der CSV hinzufügen
                    putztermine[gruppe] = termin
                except ValueError as e:
                    logging.error(f"Ungültiges Datumsformat in der CSV-Datei für {gruppe}: {e}")
        logging.info("CSV-Datei erfolgreich geladen und Kleingruppen aktualisiert.")
    except FileNotFoundError:
        logging.error(f"Die CSV-Datei wurde nicht gefunden: {file_path}")
    except Exception as e:
        logging.error(f"Fehler beim Lesen der CSV-Datei: {e}")

# Command Handler zum Aktualisieren der Daten via CSV
async def update_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = '/Users/teofilwetzel/Desktop/Development/Telegram Bot/Source/update.csv'  # Pfad zur CSV-Datei
    logging.info("CSV-Update wird angefordert...")
    try:
        update_putztermine_from_csv(file_path)
        await update.message.reply_text("Kleingruppen und Putztermine wurden aus der CSV-Datei aktualisiert.")
    except Exception as e:
        logging.error(f"Fehler beim Aktualisieren der CSV-Daten: {e}")
        await update.message.reply_text(f"Fehler beim Aktualisieren der CSV-Daten: {e}")

# Funktion zum Filtern der Kleingruppen basierend auf aktuellen Terminen
def filter_kleingruppen():
    now = datetime.now()
    return [gruppe for gruppe in kleingruppen if gruppe in putztermine and putztermine[gruppe] > now]

# Start-Funktion wird durch den /start Befehl ausgelöst
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Prüfen, ob der Start-Befehl von einer Nachricht oder einem Callback kam
    if update.callback_query:
        return  # Wenn es ein CallbackQuery ist, breche die Funktion ab, um doppelte Nachrichten zu vermeiden

    chat_id = update.message.chat_id  # Wenn es eine Nachricht ist, sende die Start-Nachricht

    # Inline-Button für Start erstellen
    start_button = [
        [InlineKeyboardButton("🚀 Starten", callback_data="start_selected")]
    ]
    reply_markup = InlineKeyboardMarkup(start_button)

    # Begrüßungsnachricht mit dem Inline-Button senden
    await context.bot.send_message(chat_id=chat_id, text="Willkommen! Klicke auf den Button, um zu starten:", reply_markup=reply_markup)

# Funktion zur Verarbeitung des Start-Knopfes
async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Starte die Kleingruppen-Auswahl, nachdem der Button gedrückt wurde
    await choose_group(query, context)

# Funktion zur Auswahl der Kleingruppe (dynamisch basierend auf CSV)
async def choose_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    aktive_kleingruppen = filter_kleingruppen()

    if aktive_kleingruppen:
        # Dynamisches Erstellen der Buttons basierend auf den geladenen Gruppen
        group_buttons = [
            [InlineKeyboardButton(f"👥 {gruppe}", callback_data=gruppe)] for gruppe in aktive_kleingruppen
        ]
        reply_markup = InlineKeyboardMarkup(group_buttons)
        await context.bot.send_message(chat_id=chat_id, text="👋 Wähle deine Kleingruppe:", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text="Es gibt keine Kleingruppen mit zukünftigen Terminen zur Auswahl.")


# Funktion zur Verarbeitung der Gruppenauswahl
async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_group = query.data

    # Überprüfen, ob "change_group" nicht die ausgewählte Gruppe ist
    if selected_group == "change_group":
        # Rückführen zur Auswahl der Kleingruppe
        await change_group(update, context)
        return  # Funktion beenden, um die Standardnachricht nicht anzuzeigen

    # Wenn der Benutzer eine tatsächliche Gruppe ausgewählt hat
    user_group[query.from_user.id] = selected_group
    await query.edit_message_text(f"🎉 Du hast {selected_group} ausgewählt!")

    if selected_group in putztermine:
        reminder_date = putztermine[selected_group]
        try:
            # Job für Erinnerung hinzufügen
            scheduler.add_job(schedule_reminder, 'date', run_date=reminder_date, args=[query.from_user.id, selected_group, context.application])
            # Text für Erinnerung mit Datum
            message = f"⏰ Du wirst am {reminder_date.strftime('%d.%m.%Y um %H:%M')} an deinen Putztermin erinnert 🧹."
            # Inline-Button "Gruppe wechseln" hinzufügen
            change_group_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("Nicht deine Kleingruppe? Gruppe wechseln", callback_data="change_group")]
            ])
            await query.message.reply_text(message, reply_markup=change_group_button)
        except Exception as e:
            await query.message.reply_text(f"Fehler beim Planen der Erinnerung für {selected_group}: {e}")
            logging.error(f"Fehler beim Planen der Erinnerung für {selected_group}: {e}")

# Neue Callback-Funktion zum Wechseln der Gruppe
async def change_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # Die Auswahl der Gruppe zurücksetzen
    if user_id in user_group:
        del user_group[user_id]
    # Benutzer zurück zur Gruppenauswahl führen
    await choose_group(update, context)

# Wrapper-Funktion, um die async-Funktion korrekt aufzurufen
def schedule_reminder(user_id, group_name, application):
    asyncio.run_coroutine_threadsafe(send_reminder(user_id, group_name, application), loop)

# Asynchrone Funktion, um die Erinnerungsnachricht zu senden
async def send_reminder(user_id, group_name, application):
    checklist_link = "https://cchn.notion.site/Checkliste-Pilgramstra-e-putzen-36b4556037ec4ca996d0fd6bfe5541bb?pvs=4"
    message = f"Erinnerung: 🧹 Deine Kleingruppe {group_name} hat morgen den Putztag! Hier ist die Checkliste: {checklist_link}"

    if user_id in user_group:
        await application.bot.send_message(chat_id=user_id, text=message)

# Befehl, um abonnierte Benutzer und deren Gruppen anzuzeigen
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if user_group:
        message = "📋 Abonnierte Benutzer und ihre Gruppen:\n"
        for user_id, group in user_group.items():
            user_info = await context.bot.get_chat(user_id)
            username = user_info.username if user_info.username else f"Benutzer-ID: {user_id}"
            message += f"{username} ist in {group}\n"
    else:
        message = "Es sind keine Benutzer für einen Termin angemeldet."

    await update.message.reply_text(message)

# Funktion zum Lesen des Tokens aus einer Datei
def get_token(file_path):
    try:
        with open(file_path, 'r') as file:
            token = file.read().strip()  # Token lesen und Leerzeichen entfernen
        return token
    except FileNotFoundError:
        logging.error(f"Token-Datei nicht gefunden: {file_path}")
        raise
    except Exception as e:
        logging.error(f"Fehler beim Lesen des Tokens: {e}")
        raise

# In der main-Funktion den neuen Handler hinzufügen
def main():
    global loop
    
    # Token aus der Datei lesen
    token_file = '/Users/teofilwetzel/Desktop/Development/Telegram Bot/bot_token.txt'  # Pfad zur Token-Datei
    bot_token = get_token(token_file)
    
    # Anwendung mit dem gelesenen Token erstellen
    application = Application.builder().token(bot_token).build()

    loop = asyncio.get_event_loop()

    # Handlers für verschiedene Befehle
    application.add_handler(CommandHandler("start", start))  # Befehl zum Starten des Bots mit dem Knopf
    application.add_handler(CallbackQueryHandler(handle_start_button, pattern="^start_selected$"))  # Handler für den Start-Knopf
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("update_csv", update_csv))
    application.add_handler(CallbackQueryHandler(group_selected))  # Handler für die Auswahl einer Gruppe
    application.add_handler(CallbackQueryHandler(change_group, pattern="^change_group$"))  # Handler für "Gruppe wechseln"

    scheduler.start()
    application.run_polling()

if __name__ == '__main__':
    main()
import time
import signal
import math
import sys
import os
from datetime import datetime

import board
import busio
import adafruit_dht
import mariadb
import RPi.GPIO as GPIO
import adafruit_character_lcd.character_lcd_i2c as character_lcd
from dotenv import load_dotenv

load_dotenv()

# ---------------- KONFIGURATION ----------------
FAN_PIN = 21
SENSOR_PIN_INNEN = board.D4
SENSOR_PIN_AUSSEN = board.D26
MESS_INTERVALL = 2              # Sekunden zwischen Messungen
DB_RECONNECT_DELAY = 5          # Sekunden vor DB-Reconnect-Versuch
DB_MAX_RETRIES = 3              # Max Reconnect-Versuche pro Zyklus

# Taupunkt-Logik
SCHALT_MINIMUM = 0.5            # Mindest-Delta-Taupunkt zum Einschalten (°C)
HYSTERESE = 1.0                 # Hysterese-Schwelle (°C)

# Magnus-Formel Konstanten
MAGNUS_A = 7.5
MAGNUS_B = 237.3

# DB aus .env (Fallback auf alte Werte für Kompatibilität)
DB_CONFIG = {
    "user": os.getenv("DB_USER", "delta"),
    "password": os.getenv("DB_PASSWORD", "delta"),
    "host": os.getenv("DB_HOST", "10.231.81.129"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "database": os.getenv("DB_NAME", "deltataupunkt"),
}


# ---------------- LOGGING ----------------
def log(tag, message):
    """Konsolen-Log mit Timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{tag}] {message}")


# ---------------- TAUPUNKT ----------------
def berechne_taupunkt(temperatur, luftfeuchtigkeit):
    """Magnus-Formel: Taupunkt aus Temperatur (°C) und rel. Feuchte (%)."""
    sdd = 6.1078 * 10 ** ((MAGNUS_A * temperatur) / (MAGNUS_B + temperatur))
    dd = (luftfeuchtigkeit / 100.0) * sdd
    v = math.log10(dd / 6.1078)
    return MAGNUS_B * v / (MAGNUS_A - v)


# ---------------- GPIO ----------------
GPIO.setmode(GPIO.BCM)
GPIO.setup(FAN_PIN, GPIO.OUT)
GPIO.output(FAN_PIN, GPIO.HIGH)  # Lüfter initial AUS


# ---------------- LCD ----------------
def init_lcd():
    """LCD initialisieren. Gibt None zurück bei Fehler."""
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        lcd = character_lcd.Character_LCD_I2C(i2c, 16, 2)
        lcd.backlight = True
        lcd.clear()
        lcd.message = "System startet"
        time.sleep(2)
        lcd.clear()
        return lcd
    except Exception as e:
        log("LCD", f"Init fehlgeschlagen: {e}")
        return None


lcd = init_lcd()


# ---------------- DB ----------------
conn = None
cur = None


def db_connect():
    """Verbindung zur Datenbank herstellen."""
    global conn, cur
    try:
        conn = mariadb.connect(**DB_CONFIG)
        conn.auto_reconnect = True
        cur = conn.cursor()
        log("DB", "Verbunden")
        return True
    except mariadb.Error as e:
        log("DB", f"Verbindungsfehler: {e}")
        conn = None
        cur = None
        return False


def db_ensure_connection():
    """Prüft DB-Verbindung und stellt sie bei Bedarf wieder her."""
    global conn, cur
    if conn is None:
        return db_connect()
    try:
        conn.ping()
        return True
    except Exception:
        log("DB", "Verbindung verloren, Reconnect...")
        for attempt in range(DB_MAX_RETRIES):
            if db_connect():
                return True
            time.sleep(DB_RECONNECT_DELAY)
        log("DB", "Reconnect fehlgeschlagen")
        return False


def log_to_database(temp_in, hum_in, temp_out, hum_out, fan_state):
    """Messwerte in die Datenbank schreiben."""
    if not db_ensure_connection():
        return

    try:
        cur.execute(
            """INSERT INTO sensorwerte
               (temp_innen, temp_aussen, hum_innen, hum_aussen, fan_state)
               VALUES (?, ?, ?, ?, ?)""",
            (temp_in, temp_out, hum_in, hum_out, fan_state)
        )
        conn.commit()
    except mariadb.Error as e:
        log("DB", f"Insert-Fehler: {e}")


# Erstverbindung
if not db_connect():
    log("DB", "Keine initiale DB-Verbindung – starte trotzdem (Offline-Modus)")


# ---------------- SENSOREN ----------------
sensor_innen = adafruit_dht.DHT22(SENSOR_PIN_INNEN)
sensor_aussen = adafruit_dht.DHT22(SENSOR_PIN_AUSSEN)


# ---------------- FAN OVERRIDE ----------------
def check_fan_override():
    """Prüft DB auf manuellen Override. Gibt (active, state) zurück."""
    if not db_ensure_connection():
        return False, None

    try:
        cur.execute("SELECT active, target_state, expires_at FROM fan_override WHERE id=1")
        row = cur.fetchone()

        if not row or not row[0]:
            return False, None

        expires_at = row[2]
        if expires_at is not None and expires_at <= datetime.now():
            # Abgelaufen → deaktivieren
            cur.execute("UPDATE fan_override SET active=FALSE WHERE id=1")
            conn.commit()
            log("OVERRIDE", "Abgelaufen, zurück zu Automatik")
            return False, None

        return True, row[1]

    except Exception as e:
        log("OVERRIDE", f"Fehler: {e}")
        return False, None


# ---------------- LÜFTER STEUERUNG ----------------
def set_fan(state):
    """Lüfter schalten. 'on' = LOW (aktiv), 'off' = HIGH."""
    if state == "on":
        GPIO.output(FAN_PIN, GPIO.LOW)
    else:
        GPIO.output(FAN_PIN, GPIO.HIGH)


# ---------------- GRACEFUL SHUTDOWN ----------------
running = True


def shutdown(signum, frame):
    """Signal-Handler für sauberes Herunterfahren (SIGTERM/SIGINT)."""
    global running
    log("SYSTEM", f"Signal {signum} empfangen – fahre herunter...")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


# ---------------- HAUPTSCHLEIFE ----------------
rotation = 0  # 0 = Lüfter aus (Automatik), 1 = Lüfter an (Automatik)
fan_state = "off"

log("SYSTEM", "Taupunktlüftung gestartet")

while running:
    try:
        # -------- SENSOREN AUSLESEN --------
        temp_innen = sensor_innen.temperature
        hum_innen = sensor_innen.humidity
        temp_aussen = sensor_aussen.temperature
        hum_aussen = sensor_aussen.humidity

        # Validierung: DHT22 liefert manchmal None
        if None in (temp_innen, hum_innen, temp_aussen, hum_aussen):
            log("SENSOR", "Ungültige Messung (None) – überspringe Zyklus")
            time.sleep(MESS_INTERVALL)
            continue

        # Plausibilitätsprüfung
        if not (-40 <= temp_innen <= 80 and -40 <= temp_aussen <= 80):
            log("SENSOR", f"Unplausible Temperatur: innen={temp_innen}, aussen={temp_aussen}")
            time.sleep(MESS_INTERVALL)
            continue

        if not (0 <= hum_innen <= 100 and 0 <= hum_aussen <= 100):
            log("SENSOR", f"Unplausible Feuchte: innen={hum_innen}, aussen={hum_aussen}")
            time.sleep(MESS_INTERVALL)
            continue

        # -------- TAUPUNKTE BERECHNEN --------
        taupunkt_innen = berechne_taupunkt(temp_innen, hum_innen)
        taupunkt_aussen = berechne_taupunkt(temp_aussen, hum_aussen)

        # -------- FAN OVERRIDE PRÜFEN --------
        override_active, override_state = check_fan_override()

        if override_active:
            fan_state = override_state
            set_fan(fan_state)
            log("OVERRIDE", f"Lüfter manuell auf '{fan_state}'")
        else:
            # -------- AUTOMATIK-LOGIK --------
            delta_taupunkt = taupunkt_aussen - taupunkt_innen

            if rotation == 0:
                # Lüfter ist aus – prüfe ob einschalten sinnvoll
                if delta_taupunkt > (SCHALT_MINIMUM + HYSTERESE):
                    fan_state = "on"
                    set_fan(fan_state)
                    rotation = 1
                    log("FAN", f"EIN – Delta-TP={delta_taupunkt:.2f}°C")
                else:
                    fan_state = "off"
            else:
                # Lüfter ist an – prüfe ob ausschalten nötig
                if delta_taupunkt < (SCHALT_MINIMUM - HYSTERESE):
                    fan_state = "off"
                    set_fan(fan_state)
                    rotation = 0
                    log("FAN", f"AUS – Delta-TP={delta_taupunkt:.2f}°C")
                else:
                    fan_state = "on"

        # -------- LCD ANZEIGE --------
        if lcd:
            try:
                lcd.clear()
                lcd.message = (
                    f"I:{temp_innen:.1f}C {hum_innen:.0f}%\n"
                    f"A:{temp_aussen:.1f}C {hum_aussen:.0f}%"
                )
            except Exception as e:
                log("LCD", f"Fehler: {e}")

        # -------- KONSOLE --------
        log("MESS", (
            f"Innen: {temp_innen:.1f}°C/{hum_innen:.0f}% (TP:{taupunkt_innen:.1f}°C) | "
            f"Aussen: {temp_aussen:.1f}°C/{hum_aussen:.0f}% (TP:{taupunkt_aussen:.1f}°C) | "
            f"Fan: {fan_state}"
        ))

        # -------- DB SCHREIBEN --------
        log_to_database(temp_innen, hum_innen, temp_aussen, hum_aussen, fan_state)

        time.sleep(MESS_INTERVALL)

    except RuntimeError as error:
        # DHT22-typischer Lesefehler – normal, einfach erneut versuchen
        log("SENSOR", f"Lesefehler: {error.args[0]}")
        time.sleep(MESS_INTERVALL)
        continue

    except Exception as error:
        log("SYSTEM", f"Unerwarteter Fehler: {error}")
        break


# ---------------- CLEANUP ----------------
log("SYSTEM", "Aufräumen...")
sensor_innen.exit()
sensor_aussen.exit()
set_fan("off")
GPIO.cleanup()

if lcd:
    lcd.clear()
    lcd.backlight = False

if conn:
    conn.close()

log("SYSTEM", "Beendet")

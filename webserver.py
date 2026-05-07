import os
import math
import csv
import io
from datetime import datetime, timedelta

import requests
import mysql.connector
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__,
    template_folder="website/templates",
    static_folder="website/static"
)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-fallback-key-change-in-production")

# ---------------- DB CONFIG ----------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}

# ---------------- SMTP CONFIG ----------------
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = SMTP_USERNAME

# ---------------- TAUPUNKT KONSTANTEN ----------------
TAUPUNKT_A = 7.5
TAUPUNKT_B = 237.3

# ---------------- ENERGIE KONFIGURATION ----------------
# Leistungsaufnahme in Watt (konfigurierbar über .env)
LUEFTER_WATT = float(os.getenv("LUEFTER_WATT", 5.0))        # Kleiner Lüfter: ~3-8W typisch
RPI_WATT = float(os.getenv("RPI_WATT", 6.0))                # RPi 4B idle: ~3-6W
STROMPREIS_KWH = float(os.getenv("STROMPREIS_KWH", 0.35))   # €/kWh (DE Durchschnitt)


# ---------------- INIT DB ----------------
def init_db():
    try:
        db = mysql.connector.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"]
        )
        cursor = db.cursor()

        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        db.commit()
        cursor.close()
        db.close()

        db = mysql.connector.connect(**DB_CONFIG)
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensorwerte (
                id INT AUTO_INCREMENT PRIMARY KEY,

                temp_innen FLOAT,
                temp_aussen FLOAT,
                hum_innen FLOAT,
                hum_aussen FLOAT,

                fan_state VARCHAR(10) DEFAULT 'off',

                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                alert_type VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                acknowledged BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fan_override (
                id INT PRIMARY KEY DEFAULT 1,
                active BOOLEAN DEFAULT FALSE,
                target_state VARCHAR(10) DEFAULT 'off',
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT IGNORE INTO fan_override (id, active, target_state)
            VALUES (1, FALSE, 'off')
        """)

        db.commit()
        cursor.close()
        db.close()
        print("[DB] Verbindung erfolgreich, Tabellen erstellt.")

    except Exception as e:
        print(f"[DB WARNUNG] Datenbank nicht erreichbar: {e}")
        print("[DB WARNUNG] Server startet ohne Datenbankverbindung. API-Endpunkte sind eingeschränkt.")


init_db()


# ---------------- DB ----------------
def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Exception as e:
        return None


def db_required(func):
    """Decorator: Prüft DB-Verbindung und gibt 503 zurück wenn nicht erreichbar."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        db = get_db()
        if db is None:
            return jsonify({"error": "Datenbank nicht verfügbar. Bitte Verbindung prüfen."}), 503
        db.close()
        return func(*args, **kwargs)
    return wrapper


# ---------------- LOGIN REQUIRED ----------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


# ---------------- TAUPUNKT BERECHNUNG ----------------
def berechne_taupunkt(temperatur, luftfeuchtigkeit):
    """Magnus-Formel zur Taupunktberechnung."""
    if temperatur is None or luftfeuchtigkeit is None:
        return None
    try:
        sdd = 6.1078 * 10 ** ((TAUPUNKT_A * temperatur) / (TAUPUNKT_B + temperatur))
        dd = (luftfeuchtigkeit / 100.0) * sdd
        v = math.log10(dd / 6.1078)
        taupunkt = TAUPUNKT_B * v / (TAUPUNKT_A - v)
        return round(taupunkt, 2)
    except (ValueError, ZeroDivisionError):
        return None


def berechne_absolute_feuchte(temperatur, luftfeuchtigkeit):
    """Absolute Feuchte in g/m³ berechnen."""
    if temperatur is None or luftfeuchtigkeit is None:
        return None
    try:
        sdd = 6.1078 * 10 ** ((TAUPUNKT_A * temperatur) / (TAUPUNKT_B + temperatur))
        dd = (luftfeuchtigkeit / 100.0) * sdd
        af = 216.7 * (dd / (temperatur + 273.15))
        return round(af, 2)
    except (ValueError, ZeroDivisionError):
        return None



# ---------------- WEATHER ----------------
STANDORTE = {
    "leer": {"lat": 53.2311, "lon": 7.4653, "name": "Leer (Ostfriesland)"},
    "aurich": {"lat": 53.4714, "lon": 7.4836, "name": "Aurich"},
    "emden": {"lat": 53.3594, "lon": 7.2060, "name": "Emden"},
    "oldenburg": {"lat": 53.1435, "lon": 8.2146, "name": "Oldenburg"},
    "wilhelmshaven": {"lat": 53.5303, "lon": 8.1052, "name": "Wilhelmshaven"},
    "norden": {"lat": 53.5957, "lon": 7.2060, "name": "Norden"},
    "papenburg": {"lat": 53.0725, "lon": 7.3964, "name": "Papenburg"},
    "wittmund": {"lat": 53.5769, "lon": 7.7810, "name": "Wittmund"},
}


# ---------------- EMAIL ----------------
def send_registration_email(to_email, username):
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = "✔ Registrierung erfolgreich – Delta-Taupunktlüftung"

        text = f"""
Hallo {username},

deine Registrierung war erfolgreich.

Du kannst dich jetzt im System anmelden und dein Dashboard nutzen.

Delta-Taupunktlüftung System
"""

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background:#f6f9fc; padding:20px;">
            <div style="max-width:600px; margin:auto; background:white; padding:25px; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.1);">

                <h2 style="color:#1fa4c9;">Willkommen, {username} 👋</h2>

                <p>Deine Registrierung war erfolgreich.</p>

                <p style="font-size:15px;">
                    Du kannst dich jetzt im System anmelden und dein Dashboard nutzen.
                </p>

                <div style="margin:20px 0; padding:15px; background:#e8f7fb; border-left:4px solid #1fa4c9;">
                    <b>Status:</b> Account erstellt<br>
                    <b>System:</b> Delta-Taupunktlüftung
                </div>

                <p style="color:#555;">
                    Viel Spaß mit deinem System 🚀
                </p>

                <hr style="border:none; border-top:1px solid #eee;">

                <p style="font-size:12px; color:#999;">
                    Diese E-Mail wurde automatisch generiert.
                </p>

            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

        print(f"E-Mail gesendet an {to_email}")

    except Exception as e:
        print("Email Fehler:", e)


# ---------------- ROUTES ----------------
@app.route("/")
def root():
    return redirect(url_for("login"))


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        if db is None:
            flash("Datenbank nicht erreichbar")
            return redirect(url_for("login"))

        cursor = db.cursor()
        cursor.execute("SELECT id, password FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user[1], password):
            session["user_id"] = user[0]
            return redirect(url_for("index"))

        flash("Login fehlgeschlagen")
        return redirect(url_for("login"))

    return render_template("login.html")


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        if db is None:
            flash("Datenbank nicht erreichbar")
            return redirect(url_for("register"))

        cursor = db.cursor()

        try:
            hashed = generate_password_hash(password)

            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, hashed)
            )

            db.commit()

            send_registration_email(email, username)

            flash("Registrierung erfolgreich")
            return redirect(url_for("login"))

        except Error:
            flash("User existiert bereits")

        finally:
            cursor.close()
            db.close()

    return render_template("register.html")


# ---------------- PAGES ----------------
@app.route("/index")
@login_required
def index():
    return render_template("index.html")


@app.route("/sensoren")
@login_required
def sensoren():
    return render_template("sensoren.html")


@app.route("/steuerung")
@login_required
def steuerung():
    return render_template("steuerung.html")


# ---------------- API SENSOR ----------------
@app.route("/api/sensoren")
@login_required
@db_required
def api_sensoren():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, timestamp
        FROM sensorwerte
        ORDER BY timestamp DESC
        LIMIT 500
    """)

    data = cursor.fetchall()

    cursor.close()
    db.close()

    return jsonify(data)


# ---------------- API FAN ----------------
@app.route("/api/fan", methods=["GET"])
@login_required
@db_required
def api_fan():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT fan_state
        FROM sensorwerte
        ORDER BY timestamp DESC
        LIMIT 1
    """)

    data = cursor.fetchone()

    cursor.close()
    db.close()

    return jsonify(data or {"fan_state": "off"})


# ---------------- API FAN OVERRIDE ----------------
@app.route("/api/fan/override", methods=["GET"])
@login_required
@db_required
def api_fan_override_get():
    """Aktuellen Override-Status abfragen."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT active, target_state, expires_at, created_at
        FROM fan_override
        WHERE id = 1
    """)
    override = cursor.fetchone()

    cursor.close()
    db.close()

    if not override:
        return jsonify({"active": False, "target_state": "off", "expires_at": None})

    # Prüfen ob Override abgelaufen ist
    abgelaufen = False
    if override["active"] and override["expires_at"]:
        abgelaufen = datetime.now() > override["expires_at"]

    return jsonify({
        "active": override["active"] and not abgelaufen,
        "target_state": override["target_state"],
        "expires_at": override["expires_at"].isoformat() if override["expires_at"] else None,
        "created_at": override["created_at"].isoformat() if override["created_at"] else None,
        "abgelaufen": abgelaufen
    })


@app.route("/api/fan/override", methods=["POST"])
@login_required
@db_required
def api_fan_override_set():
    """Lüfter manuell übersteuern.

    JSON-Body:
        state: "on" oder "off"
        dauer_min: Dauer in Minuten (Standard: 30, Max: 480)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON-Body erforderlich mit 'state' und optional 'dauer_min'"}), 400

    state = data.get("state", "").lower()
    if state not in ("on", "off"):
        return jsonify({"error": "state muss 'on' oder 'off' sein"}), 400

    dauer_min = data.get("dauer_min", 30)
    dauer_min = max(1, min(int(dauer_min), 480))

    expires_at = datetime.now() + timedelta(minutes=dauer_min)

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE fan_override
        SET active = TRUE, target_state = %s, expires_at = %s, created_at = NOW()
        WHERE id = 1
    """, (state, expires_at))

    db.commit()
    cursor.close()
    db.close()

    return jsonify({
        "success": True,
        "message": f"Lüfter wird für {dauer_min} Minuten auf '{state}' gesetzt.",
        "target_state": state,
        "expires_at": expires_at.isoformat()
    })


@app.route("/api/fan/override", methods=["DELETE"])
@login_required
@db_required
def api_fan_override_delete():
    """Override aufheben, zurück zur automatischen Steuerung."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE fan_override
        SET active = FALSE, target_state = 'off', expires_at = NULL
        WHERE id = 1
    """)

    db.commit()
    cursor.close()
    db.close()

    return jsonify({
        "success": True,
        "message": "Override aufgehoben. Automatische Steuerung aktiv."
    })


# ---------------- API WEATHER ----------------
@app.route("/api/weather")
@login_required
def api_weather():
    ort = STANDORTE["leer"]
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={ort['lat']}"
        f"&longitude={ort['lon']}"
        f"&current_weather=true"
    )

    r = requests.get(url, timeout=10).json()
    w = r.get("current_weather", {})

    return jsonify({
        "city": ort["name"],
        "temperature": w.get("temperature"),
        "windspeed": w.get("windspeed"),
        "time": w.get("time")
    })


# ================================================================
# NEUE FEATURES
# ================================================================

# ---------------- API DASHBOARD SUMMARY ----------------
@app.route("/api/dashboard")
@login_required
@db_required
def api_dashboard():
    """Aktueller Systemstatus auf einen Blick: letzte Werte, Taupunkte, Lüfterstatus."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, fan_state, timestamp
        FROM sensorwerte
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    latest = cursor.fetchone()

    cursor.close()
    db.close()

    if not latest:
        return jsonify({"error": "Keine Sensordaten vorhanden"}), 404

    taupunkt_innen = berechne_taupunkt(latest["temp_innen"], latest["hum_innen"])
    taupunkt_aussen = berechne_taupunkt(latest["temp_aussen"], latest["hum_aussen"])
    af_innen = berechne_absolute_feuchte(latest["temp_innen"], latest["hum_innen"])
    af_aussen = berechne_absolute_feuchte(latest["temp_aussen"], latest["hum_aussen"])

    delta_taupunkt = None
    lueftung_empfohlen = False
    if taupunkt_innen is not None and taupunkt_aussen is not None:
        delta_taupunkt = round(taupunkt_aussen - taupunkt_innen, 2)
        lueftung_empfohlen = delta_taupunkt > 1.5

    return jsonify({
        "temperatur_innen": latest["temp_innen"],
        "temperatur_aussen": latest["temp_aussen"],
        "luftfeuchtigkeit_innen": latest["hum_innen"],
        "luftfeuchtigkeit_aussen": latest["hum_aussen"],
        "taupunkt_innen": taupunkt_innen,
        "taupunkt_aussen": taupunkt_aussen,
        "absolute_feuchte_innen": af_innen,
        "absolute_feuchte_aussen": af_aussen,
        "delta_taupunkt": delta_taupunkt,
        "lueftung_empfohlen": lueftung_empfohlen,
        "fan_state": latest["fan_state"],
        "letztes_update": latest["timestamp"].isoformat() if latest["timestamp"] else None
    })


# ---------------- API TAUPUNKT ----------------
@app.route("/api/taupunkt")
@login_required
@db_required
def api_taupunkt():
    """Taupunktberechnung für die letzten N Messwerte (Standard: 100)."""
    limit = request.args.get("limit", 100, type=int)
    limit = min(limit, 1000)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, timestamp
        FROM sensorwerte
        ORDER BY timestamp DESC
        LIMIT %s
    """, (limit,))

    rows = cursor.fetchall()
    cursor.close()
    db.close()

    result = []
    for row in rows:
        result.append({
            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
            "taupunkt_innen": berechne_taupunkt(row["temp_innen"], row["hum_innen"]),
            "taupunkt_aussen": berechne_taupunkt(row["temp_aussen"], row["hum_aussen"]),
            "absolute_feuchte_innen": berechne_absolute_feuchte(row["temp_innen"], row["hum_innen"]),
            "absolute_feuchte_aussen": berechne_absolute_feuchte(row["temp_aussen"], row["hum_aussen"]),
        })

    return jsonify(result)


# ---------------- API SENSORDATEN MIT ZEITFILTER ----------------
@app.route("/api/sensoren/zeitraum")
@login_required
@db_required
def api_sensoren_zeitraum():
    """Sensordaten gefiltert nach Zeitraum.

    Query-Parameter:
        von: ISO-Datum (z.B. 2025-01-01)
        bis: ISO-Datum (z.B. 2025-01-31)
        intervall: Aggregationsintervall in Minuten (optional, z.B. 15)
    """
    von = request.args.get("von")
    bis = request.args.get("bis")
    intervall = request.args.get("intervall", type=int)

    if not von or not bis:
        return jsonify({"error": "Parameter 'von' und 'bis' sind erforderlich (Format: YYYY-MM-DD)"}), 400

    try:
        von_dt = datetime.fromisoformat(von)
        bis_dt = datetime.fromisoformat(bis) + timedelta(days=1)
    except ValueError:
        return jsonify({"error": "Ungültiges Datumsformat. Verwende YYYY-MM-DD"}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if intervall and intervall > 0:
        cursor.execute("""
            SELECT
                FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(timestamp) / %s) * %s) AS zeitpunkt,
                ROUND(AVG(temp_innen), 1) AS temp_innen,
                ROUND(AVG(temp_aussen), 1) AS temp_aussen,
                ROUND(AVG(hum_innen), 1) AS hum_innen,
                ROUND(AVG(hum_aussen), 1) AS hum_aussen,
                COUNT(*) AS messungen
            FROM sensorwerte
            WHERE timestamp BETWEEN %s AND %s
            GROUP BY zeitpunkt
            ORDER BY zeitpunkt ASC
        """, (intervall * 60, intervall * 60, von_dt, bis_dt))
    else:
        cursor.execute("""
            SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, fan_state, timestamp
            FROM sensorwerte
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp ASC
        """, (von_dt, bis_dt))

    data = cursor.fetchall()
    cursor.close()
    db.close()

    return jsonify(data)


# ---------------- API CSV EXPORT ----------------
@app.route("/api/export/csv")
@login_required
@db_required
def api_export_csv():
    """Sensordaten als CSV-Datei herunterladen.

    Query-Parameter:
        von: ISO-Datum (optional)
        bis: ISO-Datum (optional)
        limit: Max. Datensätze (Standard: 5000)
    """
    von = request.args.get("von")
    bis = request.args.get("bis")
    limit = request.args.get("limit", 5000, type=int)
    limit = min(limit, 50000)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if von and bis:
        try:
            von_dt = datetime.fromisoformat(von)
            bis_dt = datetime.fromisoformat(bis) + timedelta(days=1)
        except ValueError:
            return jsonify({"error": "Ungültiges Datumsformat"}), 400

        cursor.execute("""
            SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, fan_state, timestamp
            FROM sensorwerte
            WHERE timestamp BETWEEN %s AND %s
            ORDER BY timestamp ASC
            LIMIT %s
        """, (von_dt, bis_dt, limit))
    else:
        cursor.execute("""
            SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, fan_state, timestamp
            FROM sensorwerte
            ORDER BY timestamp DESC
            LIMIT %s
        """, (limit,))

    rows = cursor.fetchall()
    cursor.close()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Zeitstempel", "Temp Innen (°C)", "Temp Aussen (°C)",
        "Feuchte Innen (%)", "Feuchte Aussen (%)",
        "Taupunkt Innen (°C)", "Taupunkt Aussen (°C)",
        "Abs. Feuchte Innen (g/m³)", "Abs. Feuchte Aussen (g/m³)",
        "Lüfter"
    ])

    for row in rows:
        tp_innen = berechne_taupunkt(row["temp_innen"], row["hum_innen"])
        tp_aussen = berechne_taupunkt(row["temp_aussen"], row["hum_aussen"])
        af_innen = berechne_absolute_feuchte(row["temp_innen"], row["hum_innen"])
        af_aussen = berechne_absolute_feuchte(row["temp_aussen"], row["hum_aussen"])

        writer.writerow([
            row["timestamp"].isoformat() if row["timestamp"] else "",
            row["temp_innen"], row["temp_aussen"],
            row["hum_innen"], row["hum_aussen"],
            tp_innen, tp_aussen,
            af_innen, af_aussen,
            row["fan_state"]
        ])

    filename = f"sensordaten_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ---------------- API LÜFTER STATISTIK ----------------
@app.route("/api/fan/statistik")
@login_required
@db_required
def api_fan_statistik():
    """Lüfter-Laufzeit pro Tag (letzte 30 Tage)."""
    tage = request.args.get("tage", 30, type=int)
    tage = min(tage, 365)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            DATE(timestamp) AS datum,
            SUM(CASE WHEN fan_state = 'on' THEN 1 ELSE 0 END) AS messungen_an,
            SUM(CASE WHEN fan_state = 'off' THEN 1 ELSE 0 END) AS messungen_aus,
            COUNT(*) AS messungen_gesamt
        FROM sensorwerte
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP BY DATE(timestamp)
        ORDER BY datum DESC
    """, (tage,))

    data = cursor.fetchall()
    cursor.close()
    db.close()

    result = []
    for row in data:
        gesamt = row["messungen_gesamt"]
        anteil_an = round((row["messungen_an"] / gesamt) * 100, 1) if gesamt > 0 else 0
        result.append({
            "datum": row["datum"].isoformat() if row["datum"] else None,
            "messungen_an": row["messungen_an"],
            "messungen_aus": row["messungen_aus"],
            "anteil_an_prozent": anteil_an,
            "geschaetzte_laufzeit_min": row["messungen_an"] * 2
        })

    return jsonify(result)


# ---------------- API ENERGIEVERBRAUCH ----------------
@app.route("/api/energie")
@login_required
@db_required
def api_energie():
    """Geschätzter Energieverbrauch des Systems.

    Query-Parameter:
        monat: Monat im Format YYYY-MM (optional, Standard: aktueller Monat)
    """
    monat = request.args.get("monat")

    if monat:
        try:
            start = datetime.fromisoformat(monat + "-01")
        except ValueError:
            return jsonify({"error": "Format: YYYY-MM (z.B. 2025-04)"}), 400
    else:
        now = datetime.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Ende = Anfang nächster Monat
    if start.month == 12:
        ende = start.replace(year=start.year + 1, month=1)
    else:
        ende = start.replace(month=start.month + 1)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Lüfter-Messungen im Monat zählen
    cursor.execute("""
        SELECT
            SUM(CASE WHEN fan_state = 'on' THEN 1 ELSE 0 END) AS messungen_an,
            COUNT(*) AS messungen_gesamt
        FROM sensorwerte
        WHERE timestamp BETWEEN %s AND %s
    """, (start, ende))

    row = cursor.fetchone()
    cursor.close()
    db.close()

    messungen_an = row["messungen_an"] or 0
    messungen_gesamt = row["messungen_gesamt"] or 0

    # Messintervall = 2 Sekunden → Laufzeit in Stunden
    luefter_stunden = (messungen_an * 2) / 3600
    # Gesamtzeitraum in Stunden (basierend auf allen Messungen)
    gesamt_stunden = (messungen_gesamt * 2) / 3600

    # Energieverbrauch
    luefter_kwh = (LUEFTER_WATT * luefter_stunden) / 1000
    rpi_kwh = (RPI_WATT * gesamt_stunden) / 1000
    gesamt_kwh = luefter_kwh + rpi_kwh

    # Kosten
    kosten_luefter = luefter_kwh * STROMPREIS_KWH
    kosten_rpi = rpi_kwh * STROMPREIS_KWH
    kosten_gesamt = gesamt_kwh * STROMPREIS_KWH

    return jsonify({
        "monat": start.strftime("%Y-%m"),
        "konfiguration": {
            "luefter_watt": LUEFTER_WATT,
            "rpi_watt": RPI_WATT,
            "strompreis_kwh_eur": STROMPREIS_KWH,
            "messintervall_sek": 2
        },
        "laufzeit": {
            "luefter_stunden": round(luefter_stunden, 1),
            "system_stunden": round(gesamt_stunden, 1),
            "luefter_anteil_prozent": round((messungen_an / messungen_gesamt * 100), 1) if messungen_gesamt > 0 else 0
        },
        "verbrauch_kwh": {
            "luefter": round(luefter_kwh, 3),
            "raspberry_pi": round(rpi_kwh, 3),
            "gesamt": round(gesamt_kwh, 3)
        },
        "kosten_eur": {
            "luefter": round(kosten_luefter, 2),
            "raspberry_pi": round(kosten_rpi, 2),
            "gesamt": round(kosten_gesamt, 2)
        }
    })


@app.route("/api/energie/config", methods=["GET"])
@login_required
def api_energie_config():
    """Aktuelle Energie-Konfiguration anzeigen."""
    return jsonify({
        "luefter_watt": LUEFTER_WATT,
        "rpi_watt": RPI_WATT,
        "strompreis_kwh_eur": STROMPREIS_KWH,
        "hinweis": "Werte über .env-Datei konfigurierbar (LUEFTER_WATT, RPI_WATT, STROMPREIS_KWH)"
    })


# ---------------- API SYSTEM HEALTH ----------------
@app.route("/api/health")
@login_required
@db_required
def api_health():
    """Systemstatus: Letzte Messung, DB-Verbindung, Sensor-Ausfall-Erkennung."""
    status = {
        "db_connected": False,
        "sensor_aktiv": False,
        "letzte_messung": None,
        "alter_sekunden": None,
        "warnung": None
    }

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        status["db_connected"] = True

        cursor.execute("""
            SELECT timestamp FROM sensorwerte ORDER BY timestamp DESC LIMIT 1
        """)
        latest = cursor.fetchone()

        if latest and latest["timestamp"]:
            status["letzte_messung"] = latest["timestamp"].isoformat()
            alter = (datetime.now() - latest["timestamp"]).total_seconds()
            status["alter_sekunden"] = int(alter)
            status["sensor_aktiv"] = alter < 60

            if alter > 300:
                status["warnung"] = "Keine Sensordaten seit über 5 Minuten!"
            elif alter > 60:
                status["warnung"] = "Sensordaten leicht verzögert."

        cursor.execute("SELECT COUNT(*) AS total FROM sensorwerte")
        count = cursor.fetchone()
        status["messungen_gesamt"] = count["total"] if count else 0

        cursor.execute("""
            SELECT COUNT(*) AS heute
            FROM sensorwerte
            WHERE DATE(timestamp) = CURDATE()
        """)
        heute = cursor.fetchone()
        status["messungen_heute"] = heute["heute"] if heute else 0

        cursor.close()
        db.close()

    except Exception as e:
        status["warnung"] = f"Datenbankfehler: {str(e)}"

    return jsonify(status)


# ---------------- API TEMPERATUR STATISTIK ----------------
@app.route("/api/statistik/temperatur")
@login_required
@db_required
def api_statistik_temperatur():
    """Min/Max/Durchschnitt für Temperatur und Feuchte der letzten N Tage."""
    tage = request.args.get("tage", 7, type=int)
    tage = min(tage, 365)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            DATE(timestamp) AS datum,
            ROUND(MIN(temp_innen), 1) AS temp_innen_min,
            ROUND(MAX(temp_innen), 1) AS temp_innen_max,
            ROUND(AVG(temp_innen), 1) AS temp_innen_avg,
            ROUND(MIN(temp_aussen), 1) AS temp_aussen_min,
            ROUND(MAX(temp_aussen), 1) AS temp_aussen_max,
            ROUND(AVG(temp_aussen), 1) AS temp_aussen_avg,
            ROUND(MIN(hum_innen), 1) AS hum_innen_min,
            ROUND(MAX(hum_innen), 1) AS hum_innen_max,
            ROUND(AVG(hum_innen), 1) AS hum_innen_avg,
            ROUND(MIN(hum_aussen), 1) AS hum_aussen_min,
            ROUND(MAX(hum_aussen), 1) AS hum_aussen_max,
            ROUND(AVG(hum_aussen), 1) AS hum_aussen_avg
        FROM sensorwerte
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP BY DATE(timestamp)
        ORDER BY datum DESC
    """, (tage,))

    data = cursor.fetchall()
    cursor.close()
    db.close()

    return jsonify(data)


# ---------------- API ALERTS ----------------
@app.route("/api/alerts")
@login_required
@db_required
def api_alerts():
    """Aktive Systemwarnungen abrufen."""
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, alert_type, message, acknowledged, created_at
        FROM alerts
        WHERE acknowledged = FALSE
        ORDER BY created_at DESC
        LIMIT 50
    """)

    alerts = cursor.fetchall()
    cursor.close()
    db.close()

    return jsonify(alerts)


@app.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
@db_required
def api_acknowledge_alert(alert_id):
    """Warnung als gelesen markieren."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("UPDATE alerts SET acknowledged = TRUE WHERE id = %s", (alert_id,))
    db.commit()

    cursor.close()
    db.close()

    return jsonify({"success": True})


# ---------------- API WETTERVORHERSAGE ----------------
@app.route("/api/forecast")
@login_required
def api_forecast():
    """Wettervorhersage für die nächsten Stunden inkl. Lüftungsempfehlung.

    Query-Parameter:
        stadt: Stadtname (optional, Standard: Leer)
        tage: Vorhersage-Tage (1-7, Standard: 2)
    """
    stadt = request.args.get("stadt", "").strip()
    tage = request.args.get("tage", 2, type=int)
    tage = max(1, min(tage, 7))

    if stadt.lower() in STANDORTE:
        ort = STANDORTE[stadt.lower()]
    elif stadt:
        return jsonify({
            "error": f"Stadt '{stadt}' nicht gefunden",
            "verfuegbare_staedte": list(STANDORTE.keys())
        }), 404
    else:
        ort = STANDORTE["leer"]

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={ort['lat']}"
        f"&longitude={ort['lon']}"
        f"&hourly=temperature_2m,relative_humidity_2m,dewpoint_2m,precipitation_probability"
        f"&forecast_days={tage}"
        f"&timezone=Europe%2FBerlin"
    )

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return jsonify({"error": f"Wetterdaten nicht verfügbar: {str(e)}"}), 502

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    humidities = hourly.get("relative_humidity_2m", [])
    dewpoints = hourly.get("dewpoint_2m", [])
    precip_probs = hourly.get("precipitation_probability", [])

    # Lüftungsempfehlung berechnen: Außen-Taupunkt vs. typischer Innen-Taupunkt
    stunden = []
    for i in range(len(times)):
        temp = temps[i] if i < len(temps) else None
        hum = humidities[i] if i < len(humidities) else None
        dp = dewpoints[i] if i < len(dewpoints) else None
        precip = precip_probs[i] if i < len(precip_probs) else None

        # Lüften empfohlen wenn: niedriger Taupunkt außen UND geringe Regenwahrscheinlichkeit
        lueften_optimal = False
        if dp is not None and precip is not None:
            lueften_optimal = dp < 10.0 and precip < 30

        stunden.append({
            "zeit": times[i],
            "temperatur": temp,
            "luftfeuchtigkeit": hum,
            "taupunkt": dp,
            "regenwahrscheinlichkeit": precip,
            "lueften_optimal": lueften_optimal
        })

    # Zusammenfassung: nächste optimale Lüftungsfenster
    optimale_fenster = [s for s in stunden if s["lueften_optimal"]]

    return jsonify({
        "stadt": ort["name"],
        "vorhersage_tage": tage,
        "stunden": stunden,
        "naechstes_lueftungsfenster": optimale_fenster[0] if optimale_fenster else None,
        "optimale_stunden_gesamt": len(optimale_fenster)
    })


@app.route("/api/forecast/staedte")
@login_required
def api_forecast_staedte():
    """Liste aller verfügbaren Städte für die Wettervorhersage."""
    return jsonify(STANDORTE)


# ---------------- API TAUPUNKT RECHNER (öffentlich) ----------------
@app.route("/api/taupunkt/berechnen")
def api_taupunkt_berechnen():
    """Taupunkt manuell berechnen (ohne Login, als Hilfstool).

    Query-Parameter:
        temperatur: Temperatur in °C
        feuchte: Relative Luftfeuchtigkeit in %
    """
    temperatur = request.args.get("temperatur", type=float)
    feuchte = request.args.get("feuchte", type=float)

    if temperatur is None or feuchte is None:
        return jsonify({"error": "Parameter 'temperatur' und 'feuchte' erforderlich"}), 400

    if not (0 <= feuchte <= 100):
        return jsonify({"error": "Feuchte muss zwischen 0 und 100 liegen"}), 400

    taupunkt = berechne_taupunkt(temperatur, feuchte)
    absolute_feuchte = berechne_absolute_feuchte(temperatur, feuchte)

    return jsonify({
        "temperatur": temperatur,
        "relative_feuchte": feuchte,
        "taupunkt": taupunkt,
        "absolute_feuchte": absolute_feuchte
    })


# ---------------- START ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

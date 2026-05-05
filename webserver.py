import os
import requests
import mysql.connector
from mysql.connector import Error
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
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

app.secret_key = os.getenv("FLASK_SECRET_KEY")

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


# ---------------- INIT DB ----------------
def init_db():
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

    db.commit()
    cursor.close()
    db.close()


init_db()


# ---------------- DB ----------------
def get_db():
    return mysql.connector.connect(**DB_CONFIG)


# ---------------- LOGIN REQUIRED ----------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper



# ---------------- WEATHER ----------------
weather_location = {
    "lat": 53.2311,
    "lon": 7.4653,
    "name": "Leer (Ostfriesland)"
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


# ---------------- API SENSOR ----------------
@app.route("/api/sensoren")
@login_required
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


# ---------------- API WEATHER ----------------
@app.route("/api/weather")
@login_required
def api_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={weather_location['lat']}"
        f"&longitude={weather_location['lon']}"
        f"&current_weather=true"
    )

    r = requests.get(url).json()
    w = r.get("current_weather", {})

    return jsonify({
        "city": weather_location["name"],
        "temperature": w.get("temperature"),
        "windspeed": w.get("windspeed"),
        "time": w.get("time")
    })


# ---------------- START ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
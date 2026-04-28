import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
from mysql.connector import Error
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(
    __name__,
    template_folder="website/templates",
    static_folder="website/static"
)

app.secret_key = os.getenv("FLASK_SECRET_KEY")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}


# ---------------- DB INIT ----------------
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
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.commit()
        cursor.close()
        db.close()

        print("DB bereit")

    except Error as e:
        print("DB Error:", e)


init_db()


# ---------------- DB CONNECTION ----------------
def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print("DB error:", e)
        return None


# ---------------- LOGIN REQUIRED ----------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


# ---------------- FAN STATUS (RAM STORAGE) ----------------
fan_status = {
    "state": "off",
    "mode": "manual",
    "speed": 0
}

weather_location = {
    "lat": 53.2311,
    "lon": 7.4653,
    "name": "Leer (Ostfriesland)"
}


# ---------------- AUTH ----------------
@app.route("/")
def root():
    return redirect(url_for("login"))


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


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, generate_password_hash(password))
            )
            db.commit()
            return redirect(url_for("login"))

        except Error:
            flash("Fehler bei Registrierung")

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


@app.route("/einstellungen")
@login_required
def einstellungen():
    return render_template("einstellungen.html")


@app.route("/verbindung")
@login_required
def verbindung():
    return render_template("verbindung.html")

@app.route("/api/weather")
@login_required
def api_weather():
    global weather_location

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


# ---------------- SENSOR API ----------------
@app.route("/api/sensoren")
@login_required
def api_sensoren():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT temp_innen, temp_aussen, hum_innen, hum_aussen, timestamp
        FROM sensorwerte
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    data = cursor.fetchall()

    cursor.close()
    db.close()

    return jsonify(data)

@app.route("/api/fan", methods=["GET", "POST"])
@login_required
def api_fan():
    global fan_status

    if request.method == "POST":
        data = request.json

        fan_status["state"] = data.get("state", fan_status["state"])
        fan_status["mode"] = data.get("mode", fan_status["mode"])
        fan_status["speed"] = data.get("speed", fan_status["speed"])

        return jsonify({"status": "updated", "fan": fan_status})

    return jsonify(fan_status)


# ---------------- START ----------------
if __name__ == "__main__":
    app.run(debug=True)
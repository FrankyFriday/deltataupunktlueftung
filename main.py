import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from mysql.connector import Error
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = SMTP_USERNAME


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
        db.commit()
        cursor.close()
        db.close()
        print("Datenbank und Tabelle initiiert.")
    except Error as e:
        print(f"Database error: {e}")


init_db()


def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"DB connection error: {e}")
        return None


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Bitte zuerst einloggen!")
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def send_registration_email(to_email, username):
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = "Willkommen bei Delta-Taupunktlüftung!"

        text = f"""Hallo {username},

vielen Dank für deine Registrierung bei Delta-Taupunktlüftung!

Wir freuen uns, dich an Bord zu haben.

Viele Grüße,
Dein Delta-Taupunktlüftung Team
"""

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height:1.5; color:#333;">
            <h2 style="color:#4CAF50;">Willkommen bei Delta-Taupunktlüftung, {username}!</h2>
            <p>Vielen Dank für deine Registrierung bei <strong>Delta-Taupunktlüftung</strong>.</p>
            <p>Wir freuen uns, dich an Bord zu haben.</p>
            <br>
            <p>Viele Grüße,<br><em>Dein Delta-Taupunktlüftung Team</em></p>
        </body>
        </html>
        """

        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")

        msg.attach(part1)
        msg.attach(part2)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Bestätigungs-E-Mail an {to_email} gesendet.")
    except Exception as e:
        print(f"Fehler beim Senden der E-Mail: {e}")



@app.route("/")
def root():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        if db is None:
            flash("Datenbankverbindung fehlgeschlagen.")
            return redirect(url_for("login"))

        cursor = db.cursor()
        cursor.execute("SELECT id, password FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user:
            user_id, hashed_password = user
            if check_password_hash(hashed_password, password):
                session["user_id"] = user_id
                return redirect(url_for("index"))
            else:
                flash("Falscher Benutzername oder Passwort!")
        else:
            flash("Falscher Benutzername oder Passwort!")

        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Erfolgreich ausgeloggt.")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not password or not email:
            flash("Bitte alle Felder ausfüllen!")
            return redirect(url_for("register"))

        db = get_db()
        if db is None:
            flash("Datenbankverbindung fehlgeschlagen.")
            return redirect(url_for("register"))

        cursor = db.cursor()
        try:
            hashed_password = generate_password_hash(password)
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
            db.commit()

            send_registration_email(email, username)

            flash("Registrierung erfolgreich! Eine Bestätigungs-E-Mail wurde versendet.")
            return redirect(url_for("login"))

        except mysql.connector.IntegrityError:
            flash("Benutzername existiert bereits!")
            return redirect(url_for("register"))
        except Error as e:
            flash("Fehler bei der Registrierung.")
            print(f"Registration error: {e}")
            return redirect(url_for("register"))
        finally:
            cursor.close()
            db.close()

    return render_template("register.html")


@app.route("/index")
@login_required
def index():
    return render_template("index.html")


@app.route("/einstellungen")
@login_required
def einstellungen():
    return render_template("einstellungen.html")


@app.route("/sensoren")
@login_required
def sensoren():
    return render_template("sensoren.html")


@app.route("/verbindung")
@login_required
def verbindung():
    return render_template("verbindung.html")


if __name__ == "__main__":
    app.run(debug=True)

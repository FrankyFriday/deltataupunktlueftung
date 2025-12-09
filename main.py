from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error
from functools import wraps

app = Flask(
    __name__,
    template_folder="website/templates",  # Anpassung: templates liegen in website/templates
    static_folder="website/static"        # Anpassung: statische Dateien liegen in website/static
)

app.secret_key = "supersecretkey"

# ------------------ MySQL CONFIG -------------------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root",
    "database": "website_db"
}

# ------------------ DB INIT -------------------
def init_db():
    try:
        # Verbindung ohne DB, um DB ggf. zu erstellen
        db = mysql.connector.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"]
        )
        cursor = db.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS website_db")
        db.commit()
        cursor.close()
        db.close()

        # Verbindung zur DB um Tabelle zu erstellen
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
    except Error as e:
        print(f"Database error: {e}")

init_db()

# ------------------ HELPER: DB Verbindung -------------------
def get_db():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"DB connection error: {e}")
        return None

# ------------------ LOGIN REQUIRED DECORATOR -------------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

# ------------------ ROUTES -------------------
@app.route("/")
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        print(f"Login Versuch: username={username}")

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
            print("User gefunden:", user[0])
            if check_password_hash(user[1], password):
                print("Passwort korrekt, Login erfolgreich")
                session["user_id"] = user[0]
                return redirect(url_for("index"))
            else:
                print("Falsches Passwort")
        else:
            print("User nicht gefunden")

        flash("Falscher Benutzername oder Passwort!")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Bitte alle Felder ausfüllen!")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        db = get_db()
        if db is None:
            flash("Datenbankverbindung fehlgeschlagen.")
            return redirect(url_for("register"))

        cursor = db.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
            db.commit()
            flash("Registrierung erfolgreich!")
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

# ------------------ Geschützte Seiten -------------------
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

# ------------------ RUN -------------------
if __name__ == "__main__":
    app.run(debug=True)

import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "salon.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.secret_key = "manicure-secret-key-change-me"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Пароль мастера (поменяйте на свой!)
MASTER_PASSWORD = "master2024"

# Контактная информация (можно поменять прямо тут)
SALON_INFO = {
    "phone": "+7 (747) 629-37-76",
    "work_hours": "Пн–Вс: 10:00–16:00",
    "address": "с.Саумалколь, Алтынтау бутик №1",
}


# ---------- БАЗА ДАННЫХ ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            is_booked INTEGER NOT NULL DEFAULT 0,
            UNIQUE(date, time)
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INTEGER NOT NULL,
            client_name TEXT NOT NULL,
            client_phone TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (slot_id) REFERENCES slots(id)
        );

        CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ---------- ДОСТУП МАСТЕРА ----------

def master_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_master"):
            return redirect(url_for("master_login"))
        return f(*args, **kwargs)
    return wrapper


# ---------- КЛИЕНТСКИЕ СТРАНИЦЫ ----------

@app.route("/")
def index():
    conn = get_db()
    photos = conn.execute(
        "SELECT * FROM gallery ORDER BY uploaded_at DESC LIMIT 12"
    ).fetchall()
    conn.close()
    return render_template("index.html", photos=photos, info=SALON_INFO)


@app.route("/booking", methods=["GET", "POST"])
def booking():
    conn = get_db()

    if request.method == "POST":
        slot_id = request.form.get("slot_id")
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        comment = request.form.get("comment", "").strip()

        if not slot_id or not name or not phone:
            flash("Пожалуйста, заполните имя, телефон и выберите время.", "error")
            return redirect(url_for("booking"))

        slot = conn.execute(
            "SELECT * FROM slots WHERE id = ? AND is_booked = 0", (slot_id,)
        ).fetchone()

        if not slot:
            flash("К сожалению, это время уже заняли. Выберите другое.", "error")
            conn.close()
            return redirect(url_for("booking"))

        conn.execute("UPDATE slots SET is_booked = 1 WHERE id = ?", (slot_id,))
        conn.execute(
            "INSERT INTO bookings (slot_id, client_name, client_phone, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (slot_id, name, phone, comment, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("Вы успешно записаны! Мы вас ждём 💅", "success")
        return redirect(url_for("booking_success", slot_id=slot_id))

    today = datetime.now().strftime("%Y-%m-%d")
    free_slots = conn.execute(
        "SELECT * FROM slots WHERE is_booked = 0 AND date >= ? ORDER BY date, time",
        (today,),
    ).fetchall()
    conn.close()

    # группируем по дате
    by_date = {}
    for s in free_slots:
        by_date.setdefault(s["date"], []).append(s)

    return render_template("booking.html", by_date=by_date, info=SALON_INFO)


@app.route("/booking/success/<int:slot_id>")
def booking_success(slot_id):
    conn = get_db()
    slot = conn.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
    conn.close()
    return render_template("success.html", slot=slot, info=SALON_INFO)


# ---------- СТРАНИЦА МАСТЕРА ----------

@app.route("/master/login", methods=["GET", "POST"])
def master_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == MASTER_PASSWORD:
            session["is_master"] = True
            return redirect(url_for("master_panel"))
        flash("Неверный пароль", "error")
    return render_template("master_login.html")


@app.route("/master/logout")
def master_logout():
    session.pop("is_master", None)
    return redirect(url_for("index"))


@app.route("/master", methods=["GET"])
@master_required
def master_panel():
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    slots = conn.execute(
        "SELECT * FROM slots WHERE date >= ? ORDER BY date, time", (today,)
    ).fetchall()

    bookings = conn.execute(
        """
        SELECT b.*, s.date, s.time
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        WHERE s.date >= ?
        ORDER BY s.date, s.time
        """,
        (today,),
    ).fetchall()

    photos = conn.execute(
        "SELECT * FROM gallery ORDER BY uploaded_at DESC"
    ).fetchall()

    conn.close()

    by_date = {}
    for s in slots:
        by_date.setdefault(s["date"], []).append(s)

    return render_template(
        "master.html",
        by_date=by_date,
        bookings=bookings,
        photos=photos,
        info=SALON_INFO,
    )


@app.route("/master/add_slot", methods=["POST"])
@master_required
def add_slot():
    date = request.form.get("date")
    time_ = request.form.get("time")
    if date and time_:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO slots (date, time, is_booked) VALUES (?, ?, 0)",
                (date, time_),
            )
            conn.commit()
            flash(f"Добавлено окно {date} {time_}", "success")
        except sqlite3.IntegrityError:
            flash("Такое время уже существует", "error")
        conn.close()
    return redirect(url_for("master_panel"))


@app.route("/master/add_slots_range", methods=["POST"])
@master_required
def add_slots_range():
    """Добавить слоты на период дат (с..по) через интервал времени."""
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    interval = int(request.form.get("interval", 60))

    if not (start_date and end_date and start_time and end_time):
        flash("Заполните даты и время", "error")
        return redirect(url_for("master_panel"))

    date_fmt = "%Y-%m-%d"
    time_fmt = "%H:%M"

    d_start = datetime.strptime(start_date, date_fmt)
    d_end = datetime.strptime(end_date, date_fmt)

    if d_end < d_start:
        flash("Дата окончания раньше даты начала", "error")
        return redirect(url_for("master_panel"))

    conn = get_db()
    added = 0
    current_day = d_start

    while current_day <= d_end:
        day_str = current_day.strftime(date_fmt)
        t_start = datetime.strptime(start_time, time_fmt)
        t_end = datetime.strptime(end_time, time_fmt)
        current_time = t_start

        while current_time < t_end:
            t = current_time.strftime(time_fmt)
            try:
                conn.execute(
                    "INSERT INTO slots (date, time, is_booked) VALUES (?, ?, 0)",
                    (day_str, t),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
            current_time += timedelta(minutes=interval)

        current_day += timedelta(days=1)

    conn.commit()
    conn.close()
    flash(f"Добавлено {added} окон с {start_date} по {end_date}", "success")
    return redirect(url_for("master_panel"))


@app.route("/master/free_slot/<int:slot_id>", methods=["POST"])
@master_required
def free_slot(slot_id):
    """Освободить занятое окно (если клиент отменил запись)."""
    conn = get_db()
    conn.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (slot_id,))
    conn.execute("DELETE FROM bookings WHERE slot_id = ?", (slot_id,))
    conn.commit()
    conn.close()
    flash("Окно снова доступно для записи", "success")
    return redirect(url_for("master_panel"))


@app.route("/master/delete_slot/<int:slot_id>", methods=["POST"])
@master_required
def delete_slot(slot_id):
    conn = get_db()
    conn.execute("DELETE FROM bookings WHERE slot_id = ?", (slot_id,))
    conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()
    flash("Окно удалено", "success")
    return redirect(url_for("master_panel"))


@app.route("/master/upload_photo", methods=["POST"])
@master_required
def upload_photo():
    file = request.files.get("photo")
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))

        conn = get_db()
        conn.execute(
            "INSERT INTO gallery (filename, uploaded_at) VALUES (?, ?)",
            (unique_name, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("Фото добавлено на главную страницу", "success")
    else:
        flash("Не удалось загрузить фото (разрешены jpg, png, webp, gif)", "error")
    return redirect(url_for("master_panel"))


@app.route("/master/delete_photo/<int:photo_id>", methods=["POST"])
@master_required
def delete_photo(photo_id):
    conn = get_db()
    photo = conn.execute("SELECT * FROM gallery WHERE id = ?", (photo_id,)).fetchone()
    if photo:
        path = os.path.join(app.config["UPLOAD_FOLDER"], photo["filename"])
        if os.path.exists(path):
            os.remove(path)
        conn.execute("DELETE FROM gallery WHERE id = ?", (photo_id,))
        conn.commit()
    conn.close()
    flash("Фото удалено", "success")
    return redirect(url_for("master_panel"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)

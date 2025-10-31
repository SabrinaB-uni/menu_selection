"""
Flask cafeteria app
Starts on 0.0.0.0 so that colleagues can reach it at
    http://<your-pc-name>:5000/
Example: http://support-sab:5000/
"""

from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import os
import socket   # <-- to discover the computer / domain name

# ---------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH  = os.path.join(BASE_DIR, "cafeteria.db")

app = Flask(__name__)
app.secret_key = "my-cafeteria-app-secret-key-2024"

# ---------------------------------------------------------------------
#  Database helpers
# ---------------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_classes():
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM Class ORDER BY name").fetchall()


def get_menu_items():
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM Menu_Items ORDER BY name").fetchall()


def get_students_by_class(class_id: int):
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM Student WHERE class_id = ? ORDER BY name", (class_id,)
        ).fetchall()


def save_choice(student_id: int, menu_item_id: int, class_id: int) -> bool:
    today = datetime.now().date()
    try:
        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM Choices WHERE student_id = ? AND date = ?",
                (student_id, today),
            )
            conn.execute(
                """
                INSERT INTO Choices (student_id, menu_item_id, date, class_id)
                VALUES (?, ?, ?, ?)
                """,
                (student_id, menu_item_id, today, class_id),
            )
            conn.commit()
        return True
    except Exception as exc:
        print(f"[DB error] {exc}")
        return False


def get_all_choices():
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT c.*,
                   s.name  AS student_name,
                   m.name  AS menu_item_name,
                   cl.name AS class_name
            FROM   Choices     c
            JOIN   Student     s  ON c.student_id   = s.id
            JOIN   Menu_Items  m  ON c.menu_item_id = m.id
            JOIN   Class       cl ON c.class_id     = cl.id
            ORDER  BY c.date DESC, cl.name, s.name
            """
        ).fetchall()


def get_choice_statistics():
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT m.name       AS menu_item,
                   COUNT(*)     AS count,
                   DATE(c.date) AS choice_date
            FROM   Choices c
            JOIN   Menu_Items m ON c.menu_item_id = m.id
            GROUP  BY m.name, DATE(c.date)
            ORDER  BY choice_date DESC, count DESC
            """
        ).fetchall()


def get_today_choices_by_class(class_id: int):
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT s.name AS student_name,
                   m.name AS menu_item_name
            FROM   Choices  c
            JOIN   Student  s ON c.student_id  = s.id
            JOIN   Menu_Items m ON c.menu_item_id = m.id
            WHERE  c.class_id = ?
              AND  DATE(c.date) = DATE('now')
            ORDER  BY s.name
            """,
            (class_id,),
        ).fetchall()

#  Routes
# ---------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", classes=get_classes())


@app.route("/teacher_menu/<int:class_id>")
def teacher_menu(class_id: int):
    with get_db_connection() as conn:
        class_info = conn.execute(
            "SELECT * FROM Class WHERE id = ?", (class_id,)
        ).fetchone()

    if class_info is None:
        flash("Class not found", "error")
        return redirect(url_for("index"))

    return render_template(
        "teacher_menu.html",
        class_info=class_info,
        menu_items=get_menu_items(),
        students=get_students_by_class(class_id),
        today_choices=get_today_choices_by_class(class_id),
    )


@app.route("/save_selections", methods=["POST"])
def save_selections():
    class_id = request.form.get("class_id")
    if not class_id:
        flash("Class ID missing", "error")
        return redirect(url_for("index"))

    class_id = int(class_id)
    saved, errors = 0, 0

    for key, value in request.form.items():
        if key.startswith("student_") and value:
            try:
                student_id = int(key.split("_", 1)[1])
                menu_item_id = int(value)
                if save_choice(student_id, menu_item_id, class_id):
                    saved += 1
                else:
                    errors += 1
            except Exception as exc:
                errors += 1
                print(f"[save_selections] {exc}")

    if saved and not errors:
        flash(f"Successfully saved {saved} selections!", "success")
    elif saved and errors:
        flash(f"Saved {saved}, but {errors} failed.", "warning")
    elif errors:
        flash(f"Failed to save selections ({errors} errors).", "error")
    else:
        flash("No selections to save.", "info")

    return redirect(url_for("teacher_menu", class_id=class_id))


@app.route("/admin")
def admin_board():
    return render_template(
        "admin_board.html", choices=get_all_choices(), stats=get_choice_statistics()
    )


@app.route("/clear_today_choices/<int:class_id>")
def clear_today_choices(class_id: int):
    try:
        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM Choices WHERE class_id = ? AND DATE(date) = DATE('now')",
                (class_id,),
            )
            conn.commit()
        flash("Today's choices cleared!", "success")
    except Exception as exc:
        flash(f"Error clearing choices: {exc}", "error")

    return redirect(url_for("teacher_menu", class_id=class_id))


# ---------------------------------------------------------------------
#  Boot-up
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        raise SystemExit(
            f"Database file {DB_PATH} not found – create it before running the app."
        )

    # Determine the computer + domain name (e.g. support-sab)
    host_name = socket.getfqdn()  # full DNS name if joined to a domain
    short_name = socket.gethostname()

    print("\n---------------------------------------------------")
    print("Flask cafeteria application started.")
    print("Local machine:  http://127.0.0.1:5000")
    print(f"LAN / DNS name: http://{host_name}:5000  (or http://{short_name}:5000)")
    print("---------------------------------------------------\n")

    # Listen on *all* interfaces so remote PCs on the same network can connect
    app.run(host="0.0.0.0", port=5000, debug=False)
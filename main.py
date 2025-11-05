from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = 'cafeteria.db'

app = Flask(__name__)
app.secret_key = 'my-cafeteria-app-secret-key-2024'


# Database helpers
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables the very first time you run the app."""
    sql = """
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS Class (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT    NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Menu_Items (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT    NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Student (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT    NOT NULL,
        class_id INTEGER NOT NULL,
        FOREIGN KEY (class_id) REFERENCES Class(id)
    );

    CREATE TABLE IF NOT EXISTS Choices (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id   INTEGER NOT NULL,
        menu_item_id INTEGER NOT NULL,
        class_id     INTEGER NOT NULL,
        date         DATE    NOT NULL,
        FOREIGN KEY (student_id)   REFERENCES Student(id),
        FOREIGN KEY (menu_item_id) REFERENCES Menu_Items(id),
        FOREIGN KEY (class_id)     REFERENCES Class(id),
        UNIQUE(student_id, date)
    );
    """
    with get_db_connection() as conn:
        conn.executescript(sql)


def get_classes():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()


def get_menu_items():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Menu_Items ORDER BY name').fetchall()


def get_students_by_class(class_id):
    """Get students sorted by surname (last word in name)"""
    with get_db_connection() as conn:
        students = conn.execute(
            'SELECT * FROM Student WHERE class_id = ?',
            (class_id,)
        ).fetchall()

        # Sort by surname (last word in the name)
        sorted_students = sorted(students, key=lambda x: x['name'].split()[-1].lower())
        return sorted_students


def save_choice(student_id, menu_item_id, class_id, date):
    try:
        with get_db_connection() as conn:
            conn.execute("""
                DELETE FROM Choices 
                WHERE student_id = ? AND date = ?
            """, (student_id, date))

            if menu_item_id:
                conn.execute("""
                    INSERT INTO Choices
                    (student_id, menu_item_id, date, class_id)
                    VALUES (?, ?, ?, ?)
                """, (student_id, menu_item_id, date, class_id))
            conn.commit()
            return True
    except Exception as e:
        print(f"Database error: {e}")
        return False


def get_week_choices_by_class(class_id, start_date):
    """Get all choices for a class for a specific week"""
    end_date = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=4)
    with get_db_connection() as conn:
        choices = conn.execute("""
            SELECT s.id as student_id,
                   s.name as student_name,
                   c.date,
                   c.menu_item_id,
                   m.name as menu_item_name
            FROM Student s
            LEFT JOIN Choices c ON s.id = c.student_id 
                AND c.date >= ? AND c.date <= ?
            LEFT JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE s.class_id = ?
            ORDER BY s.name, c.date
        """, (start_date, end_date.strftime('%Y-%m-%d'), class_id)).fetchall()

        student_choices = {}
        for choice in choices:
            student_id = choice['student_id']
            if student_id not in student_choices:
                student_choices[student_id] = {
                    'student_name': choice['student_name'],
                    'choices': {}
                }
            if choice['date']:
                student_choices[student_id]['choices'][choice['date']] = choice['menu_item_id']

        return student_choices


def get_all_choices():
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT c.*,
                   s.name  AS student_name,
                   m.name  AS menu_item_name,
                   cl.name AS class_name
            FROM Choices c
            JOIN Student    s  ON c.student_id   = s.id
            JOIN Menu_Items m  ON c.menu_item_id = m.id
            JOIN Class      cl ON c.class_id     = cl.id
            ORDER BY c.date DESC, cl.name, s.name
        """).fetchall()


def get_choice_statistics():
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT m.name AS menu_item, 
                   COUNT(*) AS count,
                   DATE(c.date) as choice_date
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            GROUP BY m.name, DATE(c.date)
            ORDER BY choice_date DESC, count DESC
        """).fetchall()


def get_next_week_monday():
    """Get the Monday of the NEXT week"""
    today = datetime.now().date()
    days_since_monday = today.weekday()
    # Get this week's Monday
    this_monday = today - timedelta(days=days_since_monday)
    # Get next week's Monday
    next_monday = this_monday + timedelta(days=7)
    return next_monday.strftime('%Y-%m-%d')


# Routes
@app.route('/')
def index():
    return render_template('index.html', classes=get_classes())


@app.route('/teacher_menu/<int:class_id>')
def teacher_menu(class_id):
    with get_db_connection() as conn:
        class_info = conn.execute(
            'SELECT * FROM Class WHERE id = ?', (class_id,)
        ).fetchone()

    if class_info is None:
        flash('Class not found', 'error')
        return redirect(url_for('index'))

    # Get NEXT week's Monday
    next_monday = get_next_week_monday()

    # Get choices for next week
    student_choices = get_week_choices_by_class(class_id, next_monday)

    # Calculate week number for next week
    start_date = datetime.strptime(next_monday, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]

    # Generate dates for next week (Monday to Friday)
    week_dates = []
    for i in range(5):  # Monday to Friday
        date = start_date + timedelta(days=i)
        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),  # Format: 21-Oct
        })

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        menu_items=get_menu_items(),
        students=get_students_by_class(class_id),
        student_choices=student_choices,
        week_dates=week_dates,
        week_number=week_number
    )


@app.route('/auto_save', methods=['POST'])
def auto_save():
    try:
        data = request.get_json()

        student_id = int(data['student_id'])
        date = data['date']
        class_id = int(data['class_id'])
        menu_item_id = int(data['menu_item_id']) if data['menu_item_id'] else None

        if save_choice(student_id, menu_item_id, class_id, date):
            return jsonify({'success': True, 'message': 'Saved'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save'}), 500

    except Exception as e:
        print(f"Auto-save error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin')
def admin_board():
    return render_template(
        'admin_board.html',
        choices=get_all_choices(),
        stats=get_choice_statistics()
    )

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        init_db()
        print('Created cafeteria.db with all tables.')
    app.run(host="0.0.0.0", port=5000, debug=True)
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = r'C:\Users\sbouzouina\menu-selection\menu_selection.db'

app = Flask(__name__)
app.secret_key = 'my-cafeteria-app-secret-key-2024'


# Database connection
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Core database functions
def get_classes():
    with get_db() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()


def get_students_by_class(class_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT *, first_name || " " || last_name as full_name FROM Student WHERE class_id = ? ORDER BY last_name, first_name',
            (class_id,)
        ).fetchall()


def get_menu_items_for_day_and_cycle(day_of_week, cycle_number):
    """Get menu items available for specific day and cycle"""
    day_cols = ['mon', 'tue', 'wed', 'thu', 'fri']
    cycle_col = f'week_cycle{cycle_number}'

    with get_db() as conn:
        query = f'SELECT * FROM Menu_Items WHERE {day_cols[day_of_week]} = 1 AND {cycle_col} = 1 ORDER BY name'
        return conn.execute(query).fetchall()


def save_choice(student_id, menu_item_id, class_id, date):
    try:
        with get_db() as conn:
            # Delete existing choice
            conn.execute("DELETE FROM Choices WHERE student_id = ? AND date = ?", (student_id, date))

            # Add new choice if selected
            if menu_item_id:
                conn.execute(
                    "INSERT INTO Choices (student_id, menu_item_id, date, class_id) VALUES (?, ?, ?, ?)",
                    (student_id, menu_item_id, date, class_id)
                )
            conn.commit()
            return True
    except Exception as e:
        print(f"Error saving choice: {e}")
        return False


def get_week_choices(class_id, start_date):
    """Get all choices for a class for a week"""
    end_date = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=4)

    with get_db() as conn:
        choices = conn.execute("""
            SELECT s.id as student_id, s.first_name || ' ' || s.last_name as student_name,
                   c.date, c.menu_item_id, m.name as menu_item_name
            FROM Student s
            LEFT JOIN Choices c ON s.id = c.student_id AND c.date >= ? AND c.date <= ?
            LEFT JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE s.class_id = ?
            ORDER BY s.last_name, s.first_name, c.date
        """, (start_date, end_date.strftime('%Y-%m-%d'), class_id)).fetchall()

        # Organize by student
        student_choices = {}
        for choice in choices:
            sid = choice['student_id']
            if sid not in student_choices:
                student_choices[sid] = {
                    'student_name': choice['student_name'],
                    'choices': {}
                }
            if choice['date']:
                student_choices[sid]['choices'][choice['date']] = choice['menu_item_id']

        return student_choices


def get_week_cycle(date_str):
    """Get cycle from database or calculate it"""
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    week_num = date_obj.isocalendar()[1]
    year = date_obj.year

    with get_db() as conn:
        result = conn.execute(
            "SELECT cycle_number FROM Week_Cycle WHERE week_number = ? AND year = ?",
            (week_num, year)
        ).fetchone()

        return result['cycle_number'] if result else ((week_num - 1) % 3) + 1


def get_monday(offset_weeks=0):
    """Get Monday of current week + offset"""
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    return (monday + timedelta(weeks=offset_weeks)).strftime('%Y-%m-%d')


def get_week_dates(start_date):
    """Generate week dates with menu items"""
    start = datetime.strptime(start_date, '%Y-%m-%d')
    cycle = get_week_cycle(start_date)

    week_dates = []
    for i in range(5):  # Monday to Friday
        date = start + timedelta(days=i)
        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),
            'day_index': i,
            'menu_items': get_menu_items_for_day_and_cycle(i, cycle)
        })
    return week_dates, start.isocalendar()[1], cycle


# Routes
@app.route('/')
def index():
    return render_template('index.html', classes=get_classes())


@app.route('/teacher_menu/<int:class_id>')
def teacher_menu(class_id):
    # Get class info
    with get_db() as conn:
        class_info = conn.execute('SELECT * FROM Class WHERE id = ?', (class_id,)).fetchone()

    if not class_info:
        flash('Class not found', 'error')
        return redirect(url_for('index'))

    # Get selected week (default to next week)
    selected_week = request.args.get('week', get_monday(1))
    week_dates, week_number, week_cycle = get_week_dates(selected_week)

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        students=get_students_by_class(class_id),
        student_choices=get_week_choices(class_id, selected_week),
        week_dates=week_dates,
        week_number=week_number,
        week_cycle=week_cycle,
        selected_week=selected_week
    )


@app.route('/auto_save', methods=['POST'])
def auto_save():
    try:
        data = request.get_json()
        if save_choice(
                int(data['student_id']),
                int(data['menu_item_id']) if data['menu_item_id'] else None,
                int(data['class_id']),
                data['date']
        ):
            return jsonify({'success': True, 'message': 'Saved'})
        return jsonify({'success': False, 'message': 'Failed to save'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin')
def admin_board():
    selected_week = request.args.get('week', get_monday(0))  # Current week
    week_dates, week_number, week_cycle = get_week_dates(selected_week)

    # Get summary data
    end_date = (datetime.strptime(selected_week, '%Y-%m-%d') + timedelta(days=4)).strftime('%Y-%m-%d')

    with get_db() as conn:
        summary = conn.execute("""
            SELECT m.name as menu_item, COUNT(*) as total, c.date
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.date >= ? AND c.date <= ?
            GROUP BY m.name, c.date
            ORDER BY c.date, m.name
        """, (selected_week, end_date)).fetchall()

    return render_template(
        'admin_board.html',
        summary=summary,
        week_dates=week_dates,
        week_number=week_number,
        week_cycle=week_cycle,
        selected_week=selected_week
    )


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Please create the database in HeidiSQL first!")
    else:
        print(f"Database found at: {DB_PATH}")
        app.run(host="0.0.0.0", port=5000, debug=True)
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = r'C:\Users\sbouzouina\menu-selection\menu_selection.db'

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

    CREATE TABLE IF NOT EXISTS Menu_Availability (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        menu_item_id INTEGER NOT NULL,
        day_of_week  INTEGER NOT NULL, -- 0=Monday, 1=Tuesday, etc.
        FOREIGN KEY (menu_item_id) REFERENCES Menu_Items(id),
        UNIQUE(menu_item_id, day_of_week)
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


def get_menu_items_for_day(day_of_week):
    """Get menu items available for a specific day (0=Monday, 4=Friday)"""
    with get_db_connection() as conn:
        # First check if we have any availability rules
        availability_count = conn.execute('SELECT COUNT(*) FROM Menu_Availability').fetchone()[0]

        if availability_count == 0:
            # No rules set, return all items
            return conn.execute('SELECT * FROM Menu_Items ORDER BY name').fetchall()
        else:
            # Return only items available on this day
            return conn.execute('''
                SELECT DISTINCT m.* FROM Menu_Items m
                JOIN Menu_Availability ma ON m.id = ma.menu_item_id
                WHERE ma.day_of_week = ?
                ORDER BY m.name
            ''', (day_of_week,)).fetchall()


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


def get_week_summary(start_date):
    """Get summary of all choices for a week grouped by menu item"""
    end_date = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=4)
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT m.name as menu_item, 
                   COUNT(*) as total,
                   c.date
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.date >= ? AND c.date <= ?
            GROUP BY m.name, c.date
            ORDER BY c.date, m.name
        """, (start_date, end_date.strftime('%Y-%m-%d'))).fetchall()


def get_week_summary_totals(start_date):
    """Get total quantities needed for each menu item for the week"""
    end_date = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=4)
    with get_db_connection() as conn:
        results = conn.execute("""
            SELECT m.name as menu_item, 
                   COUNT(*) as total_portions
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.date >= ? AND c.date <= ?
            GROUP BY m.name
            ORDER BY total_portions DESC
        """, (start_date, end_date.strftime('%Y-%m-%d'))).fetchall()

        # Debug: print results
        print(f"Query results for {start_date} to {end_date.strftime('%Y-%m-%d')}:")
        for row in results:
            print(f"  {row['menu_item']}: {row['total_portions']}")

        return results


def get_daily_breakdown_by_class(start_date):
    """Get choices broken down by day, class, and menu item"""
    end_date = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=4)
    with get_db_connection() as conn:
        # Get all classes
        classes = conn.execute('SELECT * FROM Class ORDER BY name').fetchall()

        # Get all menu items
        menu_items = conn.execute('SELECT * FROM Menu_Items ORDER BY name').fetchall()

        # Get the data
        results = conn.execute("""
            SELECT 
                ch.date,
                cl.name as class_name,
                cl.id as class_id,
                m.name as menu_item,
                m.id as menu_item_id,
                COUNT(*) as quantity
            FROM Choices ch
            JOIN Class cl ON ch.class_id = cl.id
            JOIN Menu_Items m ON ch.menu_item_id = m.id
            WHERE ch.date >= ? AND ch.date <= ?
            GROUP BY ch.date, cl.name, m.name
            ORDER BY ch.date, cl.name, m.name
        """, (start_date, end_date.strftime('%Y-%m-%d'))).fetchall()

        # Organize by day
        daily_data = {}
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')

        # Initialize all weekdays
        for i in range(5):  # Monday to Friday
            date = (start_dt + timedelta(days=i)).strftime('%Y-%m-%d')
            day_name = (start_dt + timedelta(days=i)).strftime('%A')
            daily_data[date] = {
                'day_name': day_name,
                'classes': [{'name': cls['name'], 'id': cls['id']} for cls in classes],
                'menu_items': [{'name': item['name'], 'id': item['id']} for item in menu_items],
                'data': {},  # Will store class_id -> menu_item_id -> quantity
                'class_totals': {},  # class_id -> total
                'item_totals': {}  # menu_item_id -> total
            }

            # Initialize data structure
            for cls in classes:
                daily_data[date]['data'][cls['id']] = {}
                daily_data[date]['class_totals'][cls['id']] = 0
                for item in menu_items:
                    daily_data[date]['data'][cls['id']][item['id']] = 0

            for item in menu_items:
                daily_data[date]['item_totals'][item['id']] = 0

        # Fill in the actual data
        for row in results:
            date = row['date']
            if date in daily_data:
                class_id = row['class_id']
                menu_item_id = row['menu_item_id']
                quantity = row['quantity']

                daily_data[date]['data'][class_id][menu_item_id] = quantity
                daily_data[date]['class_totals'][class_id] += quantity
                daily_data[date]['item_totals'][menu_item_id] += quantity

        return daily_data


def get_next_week_monday():
    """Get the Monday of the NEXT week"""
    today = datetime.now().date()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    next_monday = this_monday + timedelta(days=7)
    return next_monday.strftime('%Y-%m-%d')


def get_week_cycle(date_str):
    """Calculate week cycle (1-3) based on week number"""
    date = datetime.strptime(date_str, '%Y-%m-%d')
    week_number = date.isocalendar()[1]
    # Simple 3-week cycle
    cycle = ((week_number - 1) % 3) + 1
    return cycle


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

    next_monday = get_next_week_monday()
    student_choices = get_week_choices_by_class(class_id, next_monday)

    start_date = datetime.strptime(next_monday, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    week_cycle = get_week_cycle(next_monday)

    # Generate dates with menu items for each day
    week_dates = []
    for i in range(5):  # Monday to Friday
        date = start_date + timedelta(days=i)
        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),
            'day_index': i,
            'menu_items': get_menu_items_for_day(i)
        })

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        students=get_students_by_class(class_id),
        student_choices=student_choices,
        week_dates=week_dates,
        week_number=week_number,
        week_cycle=week_cycle
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
    next_monday = get_next_week_monday()
    start_date = datetime.strptime(next_monday, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    week_cycle = get_week_cycle(next_monday)

    # Generate week dates for display
    week_dates = []
    for i in range(5):
        date = start_date + timedelta(days=i)
        week_dates.append({
            'display_date': date.strftime('%d-%b'),
            'date': date.strftime('%Y-%m-%d')
        })

    # Get daily breakdown for the 5 tables
    daily_breakdown = get_daily_breakdown_by_class(next_monday)

    return render_template(
        'summary_board.html',
        weekly_totals=get_week_summary_totals(next_monday),
        daily_breakdown=daily_breakdown,
        week_number=week_number,
        week_cycle=week_cycle,
        week_dates=week_dates,
        start_date=week_dates[0]['display_date'],
        end_date=week_dates[4]['display_date']
    )


if __name__ == '__main__':
    # Verify database exists and print path
    print(f"Using database at: {os.path.abspath(DB_PATH)}")
    if not os.path.exists(DB_PATH):
        print(f"Database not found! Creating new database at: {DB_PATH}")
        init_db()
        print('Created menu_selection.db with all tables.')
    else:
        print("Database found successfully!")

    app.run(host="0.0.0.0", port=5000, debug=True)
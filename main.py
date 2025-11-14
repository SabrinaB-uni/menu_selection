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
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name    TEXT NOT NULL UNIQUE,
        mon          INTEGER DEFAULT 1,
        tue          INTEGER DEFAULT 1,
        wed          INTEGER DEFAULT 1,
        thu          INTEGER DEFAULT 1,
        fri          INTEGER DEFAULT 1,
        week_cycle1  INTEGER DEFAULT 1,
        week_cycle2  INTEGER DEFAULT 1,
        week_cycle3  INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS Student (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name   TEXT NOT NULL,
        last_name    TEXT NOT NULL,
        admission_no TEXT NOT NULL,
        class_id     INTEGER NOT NULL,
        FOREIGN KEY (class_id) REFERENCES Class(id)
    );

    CREATE TABLE IF NOT EXISTS Choices (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id   INTEGER NOT NULL,
        menu_item_id INTEGER NOT NULL,
        class_id     INTEGER NOT NULL,
        week_id      INTEGER NOT NULL,
        year         INTEGER NOT NULL,
        day_of_week  INTEGER NOT NULL,
        timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id)   REFERENCES Student(id),
        FOREIGN KEY (menu_item_id) REFERENCES Menu_Items(id),
        FOREIGN KEY (class_id)     REFERENCES Class(id),
        UNIQUE(student_id, week_id, year, day_of_week)
    );

    CREATE TABLE IF NOT EXISTS Week_Cycle (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        week_number  INTEGER NOT NULL,
        year         INTEGER NOT NULL,
        cycle_number INTEGER NOT NULL,
        UNIQUE(week_number, year)
    );
    """
    with get_db_connection() as conn:
        conn.executescript(sql)


def get_classes():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()


def get_menu_items():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()


def get_menu_items_for_day(day_of_week, week_cycle=1):
    """Get menu items available for a specific day and cycle"""
    with get_db_connection() as conn:
        # Map day_of_week (0-4) to column names
        day_columns = ['mon', 'tue', 'wed', 'thu', 'fri']
        day_col = day_columns[day_of_week]
        cycle_col = f'week_cycle{week_cycle}'

        query = f"""
            SELECT * FROM Menu_Items 
            WHERE {day_col} = 1 AND {cycle_col} = 1
            ORDER BY item_name
        """
        return conn.execute(query).fetchall()


def get_students_by_class(class_id):
    """Get students sorted by last name"""
    with get_db_connection() as conn:
        students = conn.execute(
            'SELECT * FROM Student WHERE class_id = ? ORDER BY last_name, first_name',
            (class_id,)
        ).fetchall()
        return students


def save_choice(student_id, menu_item_id, class_id, date_str):
    try:
        # Parse the date to get week info
        date = datetime.strptime(date_str, '%Y-%m-%d')
        week_number = date.isocalendar()[1]
        year = date.year
        day_of_week = date.weekday()  # 0=Monday, 4=Friday

        print(f"DEBUG: Saving choice - Student: {student_id}, MenuItem: {menu_item_id}, Date: {date_str}")
        print(f"DEBUG: Week: {week_number}, Year: {year}, Day: {day_of_week}")

        with get_db_connection() as conn:
            # Delete existing choice for this student/week/day
            conn.execute("""
                DELETE FROM Choices 
                WHERE student_id = ? AND week_id = ? AND year = ? AND day_of_week = ?
            """, (student_id, week_number, year, day_of_week))

            if menu_item_id:
                # Insert new choice with timestamp
                conn.execute("""
                    INSERT INTO Choices
                    (student_id, menu_item_id, class_id, week_id, year, day_of_week, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (student_id, menu_item_id, class_id, week_number, year, day_of_week))
                print(f"DEBUG: Choice saved successfully!")

            conn.commit()
            return True
    except Exception as e:
        print(f"Database error: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_week_choices_by_class(class_id, week_number, year):
    """Get all choices for a class for a specific week"""
    with get_db_connection() as conn:
        choices = conn.execute("""
            SELECT s.id as student_id,
                   s.first_name || ' ' || s.last_name as student_name,
                   c.day_of_week,
                   c.menu_item_id,
                   m.item_name as menu_item_name,
                   c.timestamp
            FROM Student s
            LEFT JOIN Choices c ON s.id = c.student_id 
                AND c.week_id = ? AND c.year = ?
            LEFT JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE s.class_id = ?
            ORDER BY s.last_name, s.first_name, c.day_of_week
        """, (week_number, year, class_id)).fetchall()

        student_choices = {}
        for choice in choices:
            student_id = choice['student_id']
            if student_id not in student_choices:
                student_choices[student_id] = {
                    'student_name': choice['student_name'],
                    'choices': {}
                }
            if choice['day_of_week'] is not None:
                student_choices[student_id]['choices'][choice['day_of_week']] = choice['menu_item_id']

        return student_choices


def get_week_summary(start_date):
    """Get summary of all choices for a week grouped by menu item"""
    week_number = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year = datetime.strptime(start_date, '%Y-%m-%d').year

    with get_db_connection() as conn:
        return conn.execute("""
            SELECT m.item_name as menu_item, 
                   COUNT(*) as total,
                   c.day_of_week
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.week_id = ? AND c.year = ?
            GROUP BY m.item_name, c.day_of_week
            ORDER BY c.day_of_week, m.item_name
        """, (week_number, year)).fetchall()


def get_week_summary_totals(start_date):
    """Get total quantities needed for each menu item for the week"""
    week_number = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year = datetime.strptime(start_date, '%Y-%m-%d').year

    with get_db_connection() as conn:
        results = conn.execute("""
            SELECT m.item_name as menu_item, 
                   COUNT(*) as total_portions
            FROM Choices c
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.week_id = ? AND c.year = ?
            GROUP BY m.item_name
            ORDER BY total_portions DESC
        """, (week_number, year)).fetchall()

        return results


def get_daily_breakdown_by_class(start_date):
    """Get choices broken down by day, class, and menu item"""
    week_number = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year = datetime.strptime(start_date, '%Y-%m-%d').year

    print(f"DEBUG: Getting breakdown for week {week_number}, year {year}")

    with get_db_connection() as conn:
        # Get all classes
        classes = conn.execute('SELECT * FROM Class ORDER BY name').fetchall()

        # Get all menu items
        menu_items = conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()

        # Get the data
        results = conn.execute("""
            SELECT 
                ch.day_of_week,
                cl.name as class_name,
                cl.id as class_id,
                m.item_name as menu_item,
                m.id as menu_item_id,
                COUNT(*) as quantity
            FROM Choices ch
            JOIN Class cl ON ch.class_id = cl.id
            JOIN Menu_Items m ON ch.menu_item_id = m.id
            WHERE ch.week_id = ? AND ch.year = ?
            GROUP BY ch.day_of_week, cl.name, m.item_name
            ORDER BY ch.day_of_week, cl.name, m.item_name
        """, (week_number, year)).fetchall()

        print(f"DEBUG: Found {len(results)} choice records")
        for row in results:
            print(f"  Day {row['day_of_week']}: {row['class_name']} - {row['menu_item']} = {row['quantity']}")

        # Organize by day
        daily_data = {}
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')

        # Initialize all weekdays
        for i in range(5):  # Monday to Friday
            date_obj = start_dt + timedelta(days=i)
            date = date_obj.strftime('%Y-%m-%d')
            # Format: "Monday 10 Nov 2025"
            day_name = date_obj.strftime('%A %d %b %Y')

            daily_data[date] = {
                'day_name': day_name,
                'day_of_week': i,
                'classes': [{'name': cls['name'], 'id': cls['id']} for cls in classes],
                'menu_items': [{'name': item['item_name'], 'id': item['id']} for item in menu_items],
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
            day_of_week = row['day_of_week']
            # Calculate the date from day_of_week
            date = (start_dt + timedelta(days=day_of_week)).strftime('%Y-%m-%d')

            if date in daily_data:
                class_id = row['class_id']
                menu_item_id = row['menu_item_id']
                quantity = row['quantity']

                daily_data[date]['data'][class_id][menu_item_id] = quantity
                daily_data[date]['class_totals'][class_id] += quantity
                daily_data[date]['item_totals'][menu_item_id] += quantity

        return daily_data


def get_available_weeks():
    """Get all available weeks for dropdown selection"""
    with get_db_connection() as conn:
        # First, ensure current and future weeks exist in Week_Cycle
        ensure_week_cycles_exist()

        # Get all weeks - we need to calculate start_date and end_date from week_number and year
        weeks = conn.execute("""
            SELECT 
                id,
                week_number,
                year,
                cycle_number
            FROM Week_Cycle
            ORDER BY year, week_number
        """).fetchall()

        # Convert to format expected by templates
        formatted_weeks = []
        for week in weeks:
            # Calculate Monday of the week
            # Use ISO week date calculation
            jan_4 = datetime(week['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=week['week_number'] - 1)
            friday = target_monday + timedelta(days=4)

            # Format: "17 Nov to 21 Nov 2025 - Week Cycle 2"
            display_text = f"{target_monday.strftime('%d %b')} to {friday.strftime('%d %b %Y')} - Week Cycle {week['cycle_number']}"

            formatted_weeks.append({
                'start_date': target_monday.strftime('%Y-%m-%d'),
                'end_date': friday.strftime('%Y-%m-%d'),
                'week_number': week['week_number'],
                'cycle_number': week['cycle_number'],
                'display_text': display_text
            })

        return formatted_weeks


def ensure_week_cycles_exist():
    """Ensure week cycles exist for current and next few weeks"""
    with get_db_connection() as conn:
        today = datetime.now().date()

        # Generate weeks for past 4 weeks and future 8 weeks
        for weeks_offset in range(-4, 9):
            # Calculate Monday of the target week
            days_since_monday = today.weekday()
            this_monday = today - timedelta(days=days_since_monday)
            target_monday = this_monday + timedelta(weeks=weeks_offset)

            week_number = target_monday.isocalendar()[1]
            year = target_monday.year
            cycle_number = ((week_number - 1) % 3) + 1

            # Insert if doesn't exist
            conn.execute("""
                INSERT OR IGNORE INTO Week_Cycle 
                (week_number, year, cycle_number)
                VALUES (?, ?, ?)
            """, (week_number, year, cycle_number))

        conn.commit()

def get_current_week_monday():
    """Get the Monday of the current week"""
    today = datetime.now().date()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)
    return current_monday.strftime('%Y-%m-%d')

def get_next_week_monday():
    """Get the Monday of the NEXT week"""
    today = datetime.now().date()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    next_monday = this_monday + timedelta(days=7)
    return next_monday.strftime('%Y-%m-%d')

def get_week_cycle(date_str):
    """Get week cycle from database or calculate it"""
    date = datetime.strptime(date_str, '%Y-%m-%d')
    week_number = date.isocalendar()[1]
    year = date.year

    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT cycle_number 
            FROM Week_Cycle 
            WHERE week_number = ? AND year = ?
        """, (week_number, year)).fetchone()

        if result:
            return result['cycle_number']
        else:
            # Calculate if not in database
            cycle = ((week_number - 1) % 3) + 1
            return cycle

# Routes
@app.route('/')
def index():
    return render_template('index.html', classes=get_classes())

@app.route('/teacher_menu/<int:class_id>')
def teacher_menu(class_id):
    # Get selected week from query parameter, default to next week
    selected_week = request.args.get('week', get_next_week_monday())

    with get_db_connection() as conn:
        class_info = conn.execute(
            'SELECT * FROM Class WHERE id = ?', (class_id,)
        ).fetchone()

    if class_info is None:
        flash('Class not found', 'error')
        return redirect(url_for('index'))

    # Get week info
    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)

    # Get student choices using week_number and year
    student_choices = get_week_choices_by_class(class_id, week_number, year)

    # Generate dates with menu items for each day
    week_dates = []
    for i in range(5):  # Monday to Friday
        date = start_date + timedelta(days=i)
        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),
            'day_index': i,
            'menu_items': get_menu_items_for_day(i, week_cycle)
        })

    # Get available weeks for dropdown
    available_weeks = get_available_weeks()

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        students=get_students_by_class(class_id),
        student_choices=student_choices,
        week_dates=week_dates,
        week_number=week_number,
        week_cycle=week_cycle,
        available_weeks=available_weeks,
        selected_week=selected_week
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
    # Get selected week from query parameter, default to current week
    selected_week = request.args.get('week', get_current_week_monday())

    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    week_cycle = get_week_cycle(selected_week)

    # Generate week dates for display
    week_dates = []
    for i in range(5):
        date = start_date + timedelta(days=i)
        week_dates.append({
            'display_date': date.strftime('%d-%b'),
            'date': date.strftime('%Y-%m-%d')
        })

    # Get daily breakdown for the 5 tables
    daily_breakdown = get_daily_breakdown_by_class(selected_week)

    # Get available weeks for dropdown
    available_weeks = get_available_weeks()

    return render_template(
        'summary_board.html',
        daily_breakdown=daily_breakdown,
        week_number=week_number,
        week_cycle=week_cycle,
        week_dates=week_dates,
        start_date=week_dates[0]['display_date'],
        end_date=week_dates[4]['display_date'],
        available_weeks=available_weeks,
        selected_week=selected_week
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
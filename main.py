from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
import sqlite3
from datetime import datetime, timedelta
import os
import xlsxwriter
from io import BytesIO

DB_PATH = 'menu_selection.db'

app = Flask(__name__)
app.secret_key = 'menu-app-key'


# ==================== DATABASE HELPERS ====================
def get_db_connection():
    """Get database connection with Row factory enabled"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables on first run"""
    sql = """
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS Class (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
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
        packed_lunch TEXT DEFAULT '',
        UNIQUE(week_number, year)
    );
    """
    with get_db_connection() as conn:
        conn.executescript(sql)

        # Add packed_lunch column if it doesn't exist (for existing databases)
        try:
            conn.execute("ALTER TABLE Week_Cycle ADD COLUMN packed_lunch TEXT DEFAULT ''")
            print("✓ Added packed_lunch column to Week_Cycle table")
        except sqlite3.OperationalError:
            # Column already exists
            pass


# ==================== DATA RETRIEVAL ====================
def get_classes():
    """Get all classes sorted by name"""
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()


def get_menu_items():
    """Get all menu items sorted by name"""
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()


def get_menu_items_for_day(day_of_week, week_cycle=1):
    """Get menu items available for a specific day and cycle"""
    with get_db_connection() as conn:
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
    """Get students for a class, sorted by last name"""
    with get_db_connection() as conn:
        return conn.execute(
            'SELECT * FROM Student WHERE class_id = ? ORDER BY last_name, first_name',
            (class_id,)
        ).fetchall()


def get_week_choices_by_class(class_id, week_number, year):
    """Get all student choices for a specific class and week"""
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

        # Organize by student
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


def get_daily_breakdown_by_class(start_date):
    """Get complete breakdown of choices by day, class, and menu item"""
    week_number = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year = datetime.strptime(start_date, '%Y-%m-%d').year

    # Get packed lunch days for this week
    packed_lunch_days = get_packed_lunch_days(week_number, year)

    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM Class ORDER BY name').fetchall()
        menu_items = conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()

        # Get actual choice data
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
            GROUP BY ch.day_of_week, cl.name, cl.id, m.item_name, m.id
            ORDER BY ch.day_of_week, cl.name, m.item_name
        """, (week_number, year)).fetchall()

        # Initialize data structure for all days
        daily_data = {}
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')

        for i in range(5):  # Monday to Friday
            date_obj = start_dt + timedelta(days=i)
            date = date_obj.strftime('%Y-%m-%d')
            day_name = date_obj.strftime('%A %d %b %Y')
            is_packed = i in packed_lunch_days

            daily_data[date] = {
                'day_name': day_name,
                'day_of_week': i,
                'is_packed_lunch_day': is_packed,
                'classes': [{'name': cls['name'], 'id': cls['id']} for cls in classes],
                'menu_items': [{'name': item['item_name'], 'id': item['id']} for item in menu_items],
                'data': {},
                'class_totals': {},
                'item_totals': {}
            }

            # Initialize with zeros
            for cls in classes:
                daily_data[date]['data'][cls['id']] = {}
                daily_data[date]['class_totals'][cls['id']] = 0
                for item in menu_items:
                    daily_data[date]['data'][cls['id']][item['id']] = 0

            for item in menu_items:
                daily_data[date]['item_totals'][item['id']] = 0

        # Fill in actual data
        for row in results:
            day_of_week = row['day_of_week']
            date = (start_dt + timedelta(days=day_of_week)).strftime('%Y-%m-%d')

            if date in daily_data:
                class_id = row['class_id']
                menu_item_id = row['menu_item_id']
                quantity = row['quantity']

                daily_data[date]['data'][class_id][menu_item_id] = quantity
                daily_data[date]['class_totals'][class_id] += quantity
                daily_data[date]['item_totals'][menu_item_id] += quantity

        return daily_data


# ==================== SAVE OPERATIONS ====================
def save_choice(student_id, menu_item_id, class_id, date_str):
    """Save or update a student's lunch choice"""
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
        week_number = date.isocalendar()[1]
        year = date.year
        day_of_week = date.weekday()

        with get_db_connection() as conn:
            # Delete existing choice
            conn.execute("""
                DELETE FROM Choices 
                WHERE student_id = ? AND week_id = ? AND year = ? AND day_of_week = ?
            """, (student_id, week_number, year, day_of_week))

            # Insert new choice if menu_item selected
            if menu_item_id:
                conn.execute("""
                    INSERT INTO Choices
                    (student_id, menu_item_id, class_id, week_id, year, day_of_week, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (student_id, menu_item_id, class_id, week_number, year, day_of_week))

            conn.commit()
            return True
    except Exception as e:
        print(f"Database error: {e}")
        return False


# ==================== WEEK CYCLE MANAGEMENT ====================
def get_available_weeks():
    """Get all available weeks for dropdown selection"""
    with get_db_connection() as conn:
        ensure_week_cycles_exist()

        weeks = conn.execute("""
            SELECT id, week_number, year, cycle_number
            FROM Week_Cycle
            ORDER BY year, week_number
        """).fetchall()

        formatted_weeks = []
        for week in weeks:
            jan_4 = datetime(week['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=week['week_number'] - 1)
            friday = target_monday + timedelta(days=4)

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
    """
    Check if weeks exist, but DON'T auto-generate.
    Weeks must be manually added to database.
    """
    # Do nothing - weeks are managed manually in database
    pass


def week_exists(week_monday_str):
    """Check if a week exists in the database"""
    date = datetime.strptime(week_monday_str, '%Y-%m-%d')
    week_number = date.isocalendar()[1]
    year = date.year

    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT 1 FROM Week_Cycle 
            WHERE week_number = ? AND year = ?
        """, (week_number, year)).fetchone()

        return result is not None


def get_current_week_monday():
    """Get Monday of current week"""
    today = datetime.now().date()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)
    return current_monday.strftime('%Y-%m-%d')


def get_next_week_monday():
    """
    Get Monday of next week - looks for the NEXT week that exists in database.
    If current week doesn't exist, finds the nearest future week.
    """
    today = datetime.now().date()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)

    with get_db_connection() as conn:
        # Find the next week that exists in the database after this Monday
        result = conn.execute("""
            SELECT week_number, year
            FROM Week_Cycle
            WHERE year > ? OR (year = ? AND week_number >= ?)
            ORDER BY year ASC, week_number ASC
            LIMIT 1
        """, (this_monday.year, this_monday.year, this_monday.isocalendar()[1])).fetchone()

        if result:
            # Calculate Monday for this week number
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            # Fallback: just add 7 days
            next_monday = this_monday + timedelta(days=7)
            return next_monday.strftime('%Y-%m-%d')


def get_week_cycle(date_str):
    """Get week cycle number for a specific date - Returns None if week doesn't exist"""
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
            # Return None instead of fallback calculation
            return None


def is_week_editable(selected_week_str):
    """
    Check if a week is editable.
    A week becomes read-only once it starts (on its Monday).
    Only future weeks can be edited.
    """
    selected_monday = datetime.strptime(selected_week_str, '%Y-%m-%d').date()
    today = datetime.now().date()

    # Get Monday of current week
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)

    # Only allow editing for weeks that haven't started yet
    return selected_monday > current_monday


def is_packed_lunch_day(week_number, year, day_of_week):
    """
    Check if a specific day is a packed lunch day using SQL pattern matching.

    Args:
        week_number: ISO week number (1-53)
        year: Year (e.g., 2025)
        day_of_week: Python weekday (0=Monday, 1=Tuesday, ..., 4=Friday)

    Returns:
        True if packed lunch day, False otherwise

    Database Format:
        packed_lunch column stores '1,3,5' where 1=Monday, 5=Friday

    Examples:
        is_packed_lunch_day(52, 2025, 0) → checks if Monday is packed lunch
        is_packed_lunch_day(52, 2025, 4) → checks if Friday is packed lunch
    """
    # Convert Python weekday (0-4) to database format (1-5)
    human_day = day_of_week + 1

    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT 
                CASE 
                    WHEN ',' || COALESCE(packed_lunch, '') || ',' LIKE '%,' || ? || ',%' 
                    THEN 1 
                    ELSE 0 
                END AS has_packed_lunch
            FROM Week_Cycle
            WHERE week_number = ? 
              AND year = ?
        """, (human_day, week_number, year)).fetchone()

        if result:
            return bool(result[0])

        # Week doesn't exist in database
        return False


def get_packed_lunch_days(week_number, year):
    """
    Get list of packed lunch days for a week.

    Returns:
        List of Python weekday numbers (0=Monday, 4=Friday)
        Example: [0, 2, 4] means Monday, Wednesday, Friday

    Uses SQL pattern matching for reliability - no string parsing needed!
    """
    packed_days = []

    # Check each weekday (0=Monday to 4=Friday)
    for python_day in range(5):
        if is_packed_lunch_day(week_number, year, python_day):
            packed_days.append(python_day)

    return packed_days


def get_previous_week_monday(current_week_str):
    """
    Get Monday of the previous week that EXISTS in database (skipping gaps).
    """
    current_date = datetime.strptime(current_week_str, '%Y-%m-%d').date()
    current_week_num = current_date.isocalendar()[1]
    current_year = current_date.year

    with get_db_connection() as conn:
        # Find the most recent week before current week
        result = conn.execute("""
            SELECT week_number, year
            FROM Week_Cycle
            WHERE year < ? OR (year = ? AND week_number < ?)
            ORDER BY year DESC, week_number DESC
            LIMIT 1
        """, (current_year, current_year, current_week_num)).fetchone()

        if result:
            # Calculate Monday for this week number
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            # Fallback: just subtract 7 days
            previous_monday = current_date - timedelta(days=7)
            return previous_monday.strftime('%Y-%m-%d')


def get_next_week_monday_from_date(current_week_str):
    """
    Get Monday of the next week that EXISTS in database after given date (skipping gaps).
    """
    current_date = datetime.strptime(current_week_str, '%Y-%m-%d').date()
    current_week_num = current_date.isocalendar()[1]
    current_year = current_date.year

    with get_db_connection() as conn:
        # Find the next week after current week
        result = conn.execute("""
            SELECT week_number, year
            FROM Week_Cycle
            WHERE year > ? OR (year = ? AND week_number > ?)
            ORDER BY year ASC, week_number ASC
            LIMIT 1
        """, (current_year, current_year, current_week_num)).fetchone()

        if result:
            # Calculate Monday for this week number
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            # Fallback: just add 7 days
            next_monday = current_date + timedelta(days=7)
            return next_monday.strftime('%Y-%m-%d')


def get_previous_cycle_week(class_id, week_number, year):
    """
    Find the most recent occurrence of the same week cycle for a class.
    Returns (previous_week_number, previous_year) or (None, None) if not found.
    """
    with get_db_connection() as conn:
        # Get current week's cycle number
        current_cycle = conn.execute("""
            SELECT cycle_number FROM Week_Cycle 
            WHERE week_number = ? AND year = ?
        """, (week_number, year)).fetchone()

        if not current_cycle:
            return None, None

        cycle_num = current_cycle['cycle_number']

        # Find the most recent week with the same cycle number (before current week)
        result = conn.execute("""
            SELECT wc.week_number, wc.year
            FROM Week_Cycle wc
            WHERE wc.cycle_number = ?
              AND (wc.year < ? OR (wc.year = ? AND wc.week_number < ?))
              AND EXISTS (
                  SELECT 1 FROM Choices c 
                  WHERE c.week_id = wc.week_number 
                    AND c.year = wc.year 
                    AND c.class_id = ?
              )
            ORDER BY wc.year DESC, wc.week_number DESC
            LIMIT 1
        """, (cycle_num, year, year, week_number, class_id)).fetchone()

        if result:
            return result['week_number'], result['year']

        return None, None


def duplicate_choices_from_previous_cycle(class_id, from_week, from_year, to_week, to_year):
    """
    Copy all lunch choices from one week to another for a specific class.
    """
    try:
        with get_db_connection() as conn:
            # First, delete any existing choices for the target week
            conn.execute("""
                DELETE FROM Choices 
                WHERE class_id = ? AND week_id = ? AND year = ?
            """, (class_id, to_week, to_year))

            # Copy choices from previous cycle
            conn.execute("""
                INSERT INTO Choices (student_id, menu_item_id, class_id, week_id, year, day_of_week, timestamp)
                SELECT student_id, menu_item_id, class_id, ?, ?, day_of_week, CURRENT_TIMESTAMP
                FROM Choices
                WHERE class_id = ? AND week_id = ? AND year = ?
            """, (to_week, to_year, class_id, from_week, from_year))

            conn.commit()

            # Count how many choices were copied
            count = conn.execute("""
                SELECT COUNT(*) as total FROM Choices 
                WHERE class_id = ? AND week_id = ? AND year = ?
            """, (class_id, to_week, to_year)).fetchone()['total']

            return True, count
    except Exception as e:
        print(f"Error duplicating choices: {e}")
        return False, 0


# ==================== ROUTES ====================
@app.route('/')
def index():
    """Home page with class selection"""
    return render_template('index.html', classes=get_classes())


@app.route('/teacher_menu/<int:class_id>')
def teacher_menu(class_id):
    """Teacher menu selection page for a specific class"""
    selected_week = request.args.get('week', get_next_week_monday())

    with get_db_connection() as conn:
        class_info = conn.execute(
            'SELECT * FROM Class WHERE id = ?', (class_id,)
        ).fetchone()

    if class_info is None:
        flash('Class not found', 'error')
        return redirect(url_for('index'))

    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)

    # Check if week cycle exists
    week_cycle_exists = week_cycle is not None

    # Use cycle 1 as default for menu items if week doesn't exist
    display_week_cycle = week_cycle if week_cycle else 1

    student_choices = get_week_choices_by_class(class_id, week_number, year)
    packed_lunch_days = get_packed_lunch_days(week_number, year)
    students = get_students_by_class(class_id)

    # Generate week dates with menu items
    week_dates = []
    for i in range(5):
        date = start_date + timedelta(days=i)
        is_packed = i in packed_lunch_days
        menu_items = get_menu_items_for_day(i, display_week_cycle)

        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),
            'day_index': i,
            'menu_items': menu_items,
            'is_packed_lunch_day': is_packed
        })

    available_weeks = get_available_weeks()
    is_editable = is_week_editable(selected_week) and week_cycle_exists

    # Calculate navigation weeks
    previous_week = get_previous_week_monday(selected_week)
    next_week = get_next_week_monday_from_date(selected_week)
    current_week = get_next_week_monday()

    # Check if navigation weeks exist in database
    has_previous_week = week_exists(previous_week)
    has_next_week = week_exists(next_week)

    is_current_week = (selected_week == current_week)
    is_future_week = is_editable and not is_current_week

    # Get previous cycle week info for duplication feature
    prev_cycle_week, prev_cycle_year = get_previous_cycle_week(class_id, week_number, year)
    has_previous_cycle = (prev_cycle_week is not None)

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        students=students,
        student_choices=student_choices,
        week_dates=week_dates,
        week_number=week_number,
        week_cycle=display_week_cycle,
        week_cycle_exists=week_cycle_exists,
        available_weeks=available_weeks,
        selected_week=selected_week,
        is_editable=is_editable,
        is_current_week=is_current_week,
        is_future_week=is_future_week,
        previous_week=previous_week,
        next_week=next_week,
        current_week=current_week,
        packed_lunch_days=packed_lunch_days,
        has_previous_week=has_previous_week,
        has_next_week=has_next_week,
        has_previous_cycle=has_previous_cycle,
        prev_cycle_week=prev_cycle_week,
        prev_cycle_year=prev_cycle_year,
        year=year
    )


@app.route('/auto_save', methods=['POST'])
def auto_save():
    """API endpoint for auto-saving lunch choices"""
    try:
        data = request.get_json()

        student_id = int(data['student_id'])
        date = data['date']
        class_id = int(data['class_id'])
        menu_item_id = int(data['menu_item_id']) if data['menu_item_id'] else None

        # CHECK IF WEEK HAS ALREADY STARTED (read-only protection)
        choice_date = datetime.strptime(date, '%Y-%m-%d').date()
        today = datetime.now().date()

        # Get Monday of the week being edited
        days_since_monday = choice_date.weekday()
        choice_week_monday = choice_date - timedelta(days=days_since_monday)

        # Get Monday of current week
        today_days_since_monday = today.weekday()
        current_monday = today - timedelta(days=today_days_since_monday)

        # Block editing for weeks that have started or are in the past
        if choice_week_monday <= current_monday:
            return jsonify({
                'success': False,
                'message': 'Cannot edit - this week has started. Kitchen is preparing meals.'
            }), 403

        if save_choice(student_id, menu_item_id, class_id, date):
            return jsonify({'success': True, 'message': 'Saved'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save'}), 500

    except Exception as e:
        print(f"Auto-save error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/duplicate_previous_cycle/<int:class_id>', methods=['POST'])
def duplicate_previous_cycle(class_id):
    """API endpoint to duplicate choices from previous same-cycle week"""
    try:
        data = request.get_json()
        current_week = data.get('week_number')
        current_year = data.get('year')

        # Find previous cycle week
        prev_week, prev_year = get_previous_cycle_week(class_id, current_week, current_year)

        if not prev_week or not prev_year:
            return jsonify({
                'success': False,
                'message': 'No previous cycle week found with existing choices'
            }), 404

        # Duplicate the choices
        success, count = duplicate_choices_from_previous_cycle(
            class_id, prev_week, prev_year, current_week, current_year
        )

        if success:
            return jsonify({
                'success': True,
                'message': f'Successfully copied {count} choices from Week {prev_week}/{prev_year}',
                'count': count
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to duplicate choices'
            }), 500

    except Exception as e:
        print(f"Duplicate error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/summary')
def summary_board():
    """Summary dashboard showing all choices for the week"""
    selected_week = request.args.get('week', get_current_week_monday())

    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    week_cycle = get_week_cycle(selected_week)

    # Check if week cycle exists
    week_cycle_exists = week_cycle is not None
    display_week_cycle = week_cycle if week_cycle else 1

    # Generate week dates for display
    week_dates = []
    for i in range(5):
        date = start_date + timedelta(days=i)
        week_dates.append({
            'display_date': date.strftime('%d-%b'),
            'date': date.strftime('%Y-%m-%d')
        })

    daily_breakdown = get_daily_breakdown_by_class(selected_week)
    available_weeks = get_available_weeks()

    # Calculate navigation weeks
    previous_week = get_previous_week_monday(selected_week)
    next_week = get_next_week_monday_from_date(selected_week)
    current_week = get_current_week_monday()

    # Check if navigation weeks exist in database
    has_previous_week = week_exists(previous_week)
    has_next_week = week_exists(next_week)

    # Determine week type
    is_current_week = (selected_week == current_week)
    is_future_week = (selected_week > current_week)

    return render_template(
        'summary_board.html',
        daily_breakdown=daily_breakdown,
        week_number=week_number,
        week_cycle=display_week_cycle,
        week_cycle_exists=week_cycle_exists,
        week_dates=week_dates,
        start_date=week_dates[0]['display_date'],
        end_date=week_dates[4]['display_date'],
        available_weeks=available_weeks,
        selected_week=selected_week,
        previous_week=previous_week,
        next_week=next_week,
        current_week=current_week,
        is_current_week=is_current_week,
        is_future_week=is_future_week,
        has_previous_week=has_previous_week,
        has_next_week=has_next_week
    )


@app.route('/export_summary_excel')
def export_summary_excel():
    """Export summary data to formatted Excel file with packed lunch day highlighting"""
    selected_week = request.args.get('week', get_current_week_monday())

    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)

    # Check if week exists
    if week_cycle is None:
        flash('Cannot export - this week has no cycle configured in the database', 'error')
        return redirect(url_for('summary_board', week=selected_week))

    # Get packed lunch days for this week
    packed_lunch_days = get_packed_lunch_days(week_number, year)

    # Get the summary data
    daily_breakdown = get_daily_breakdown_by_class(selected_week)

    # Create Excel file in memory
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})

    # Define formats
    title_format = workbook.add_format({
        'bold': True,
        'font_size': 16,
        'font_color': '#2c3e50',
        'align': 'left'
    })

    subtitle_format = workbook.add_format({
        'font_size': 12,
        'font_color': '#7f8c8d',
        'italic': True,
        'align': 'left'
    })

    # Normal day header (dark background)
    day_header_format = workbook.add_format({
        'bold': True,
        'font_size': 14,
        'font_color': '#2c3e50',
        'bg_color': '#ecf0f1',
        'border': 1,
        'align': 'center'
    })

    # Packed lunch day header (YELLOW background)
    packed_lunch_day_header_format = workbook.add_format({
        'bold': True,
        'font_size': 14,
        'font_color': '#000000',
        'bg_color': '#FFFF00',
        'border': 2,
        'align': 'center'
    })

    table_header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#34495e',
        'font_color': 'white',
        'border': 1,
        'align': 'center',
        'valign': 'vcenter',
        'text_wrap': True
    })

    class_name_format = workbook.add_format({
        'bold': True,
        'bg_color': '#f8f9fa',
        'border': 1,
        'align': 'left'
    })

    data_format = workbook.add_format({
        'border': 1,
        'align': 'center'
    })

    total_row_format = workbook.add_format({
        'bold': True,
        'bg_color': '#d5e8d4',
        'border': 2,
        'align': 'center'
    })

    total_label_format = workbook.add_format({
        'bold': True,
        'bg_color': '#d5e8d4',
        'border': 2,
        'align': 'left'
    })

    grand_total_format = workbook.add_format({
        'bold': True,
        'bg_color': '#6b8e65',
        'font_color': 'white',
        'border': 2,
        'align': 'center',
        'font_size': 11
    })

    # Create worksheet
    worksheet = workbook.add_worksheet('Lunch Summary')

    # Set column widths
    worksheet.set_column('A:A', 25)
    worksheet.set_column('B:Z', 15)

    # Write title and subtitle
    current_row = 0
    worksheet.write(current_row, 0, f'Lunch Selection Summary - Week {week_number} (Cycle {week_cycle})', title_format)
    current_row += 1
    worksheet.write(current_row, 0, f'Week of {start_date.strftime("%d %b %Y")}', subtitle_format)
    current_row += 2

    # Process each day
    for date, data in sorted(daily_breakdown.items()):
        if sum(data['item_totals'].values()) > 0:

            # Check if this day is a packed lunch day
            day_of_week = data['day_of_week']
            is_packed_lunch_day_flag = day_of_week in packed_lunch_days

            # Choose header format based on packed lunch status
            if is_packed_lunch_day_flag:
                header_format = packed_lunch_day_header_format
                day_header_text = f"{data['day_name']} - Packed Lunches Served in Classroom"
            else:
                header_format = day_header_format
                day_header_text = data['day_name']

            # Day header
            worksheet.merge_range(current_row, 0, current_row, len(data['menu_items']),
                                  day_header_text, header_format)
            current_row += 1

            # Table header row
            worksheet.write(current_row, 0, 'Class / Menu Item', table_header_format)
            col = 1
            for item in data['menu_items']:
                worksheet.write(current_row, col, item['name'], table_header_format)
                col += 1
            worksheet.write(current_row, col, 'Total', table_header_format)

            worksheet.set_row(current_row, 40)
            current_row += 1

            # Data rows for each class
            for cls in data['classes']:
                worksheet.write(current_row, 0, cls['name'], class_name_format)
                col = 1
                for item in data['menu_items']:
                    count = data['data'][cls['id']][item['id']]
                    if count > 0:
                        worksheet.write(current_row, col, count, data_format)
                    else:
                        worksheet.write(current_row, col, '', data_format)
                    col += 1

                class_total = data['class_totals'][cls['id']]
                if class_total > 0:
                    worksheet.write(current_row, col, class_total, data_format)
                else:
                    worksheet.write(current_row, col, '', data_format)
                current_row += 1

            # Total row
            worksheet.write(current_row, 0, 'TOTAL', total_label_format)
            col = 1
            for item in data['menu_items']:
                total = data['item_totals'][item['id']]
                if total > 0:
                    worksheet.write(current_row, col, total, total_row_format)
                else:
                    worksheet.write(current_row, col, '', total_row_format)
                col += 1

            grand_total = sum(data['item_totals'].values())
            worksheet.write(current_row, col, grand_total, grand_total_format)
            current_row += 3

    workbook.close()
    output.seek(0)

    filename = f'lunch_summary_week_{week_number}_{start_date.strftime("%Y-%m-%d")}.xlsx'

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

# ==================== APPLICATION STARTUP ====================
if __name__ == '__main__':
    print(f"Using database at: {os.path.abspath(DB_PATH)}")

    if not os.path.exists(DB_PATH):
        print(f"Database not found! Creating new database at: {DB_PATH}")
        init_db()
        print('✓ Created menu_selection.db with all tables.')
    else:
        print("✓ Database found successfully!")

    print("School Lunch Choice System")
    print(f"Access via: http://support-sab:5000/")
    print("Week cycles must be manually added to database")

    app.run(host="0.0.0.0", port=5000, debug=True)
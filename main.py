from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, make_response
import sqlite3
from datetime import datetime, timedelta
import os
import xlsxwriter
from io import BytesIO
import csv
import io

DB_PATH = 'menu_selection.db'
app = Flask(__name__)
app.secret_key = 'menu-app-key'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    sql = """
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS Class (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS Menu_Items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT NOT NULL UNIQUE, mon INTEGER DEFAULT 1, tue INTEGER DEFAULT 1, wed INTEGER DEFAULT 1, thu INTEGER DEFAULT 1, fri INTEGER DEFAULT 1, week_cycle1 INTEGER DEFAULT 1, week_cycle2 INTEGER DEFAULT 1, week_cycle3 INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS Student (id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL, last_name TEXT NOT NULL, admission_no TEXT NOT NULL, class_id INTEGER NOT NULL, FOREIGN KEY (class_id) REFERENCES Class(id));
    CREATE TABLE IF NOT EXISTS Choices (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, menu_item_id INTEGER NOT NULL, class_id INTEGER NOT NULL, week_id INTEGER NOT NULL, year INTEGER NOT NULL, day_of_week INTEGER NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (student_id) REFERENCES Student(id), FOREIGN KEY (menu_item_id) REFERENCES Menu_Items(id), FOREIGN KEY (class_id) REFERENCES Class(id), UNIQUE(student_id, week_id, year, day_of_week));
    CREATE TABLE IF NOT EXISTS Week_Cycle (id INTEGER PRIMARY KEY AUTOINCREMENT, week_number INTEGER NOT NULL, year INTEGER NOT NULL, cycle_number INTEGER NOT NULL, packed_lunch TEXT DEFAULT '', UNIQUE(week_number, year));
    """
    with get_db_connection() as conn:
        conn.executescript(sql)
        try:
            conn.execute("ALTER TABLE Week_Cycle ADD COLUMN packed_lunch TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

def get_classes():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()

def get_class_by_id(class_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class WHERE id = ?', (class_id,)).fetchone()

def get_menu_items():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()

def get_menu_items_for_day(day_of_week, week_cycle=1):

    with get_db_connection() as conn:

        day_columns = ['mon', 'tue', 'wed', 'thu', 'fri']
        day_col = day_columns[day_of_week]

        cycle_col = f'week_cycle{week_cycle}'

        query = f"""
            SELECT *
            FROM Menu_Items
            WHERE {day_col} = 1
            AND {cycle_col} = 1
            ORDER BY item_name
        """

        print("\n========== MENU DEBUG ==========")
        print("DAY COLUMN:", day_col)
        print("WEEK CYCLE COLUMN:", cycle_col)
        print("QUERY:", query)

        rows = conn.execute(query).fetchall()

        print("ROWS FOUND:", len(rows))

        for r in rows:
            print(dict(r))

        print("================================\n")

        return rows

def get_students_by_class(class_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Student WHERE class_id = ? ORDER BY last_name, first_name', (class_id,)).fetchall()

def get_all_students():
    with get_db_connection() as conn:
        return conn.execute('SELECT s.id, s.first_name, s.last_name, s.admission_no, c.name as class_name FROM Student s JOIN Class c ON s.class_id = c.id ORDER BY s.last_name, s.first_name').fetchall()

def get_week_choices_by_class(class_id, week_number, year):
    with get_db_connection() as conn:
        choices = conn.execute("""SELECT s.id as student_id, s.first_name || ' ' || s.last_name as student_name, c.day_of_week, c.menu_item_id, m.item_name as menu_item_name, c.timestamp FROM Student s LEFT JOIN Choices c ON s.id = c.student_id AND c.week_id = ? AND c.year = ? LEFT JOIN Menu_Items m ON c.menu_item_id = m.id WHERE s.class_id = ? ORDER BY s.last_name, s.first_name, c.day_of_week""", (week_number, year, class_id)).fetchall()
        student_choices = {}
        for choice in choices:
            student_id = choice['student_id']
            if student_id not in student_choices:
                student_choices[student_id] = {'student_name': choice['student_name'], 'choices': {}}
            if choice['day_of_week'] is not None:
                student_choices[student_id]['choices'][choice['day_of_week']] = choice['menu_item_id']
        return student_choices

def get_daily_breakdown_by_class(start_date):
    week_number = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year = datetime.strptime(start_date, '%Y-%m-%d').year
    packed_lunch_days = get_packed_lunch_days(week_number, year)
    with get_db_connection() as conn:
        classes = conn.execute('SELECT * FROM Class ORDER BY name').fetchall()
        menu_items = conn.execute('SELECT * FROM Menu_Items ORDER BY item_name').fetchall()
        results = conn.execute("""SELECT ch.day_of_week, cl.name as class_name, cl.id as class_id, m.item_name as menu_item, m.id as menu_item_id, COUNT(*) as quantity FROM Choices ch JOIN Class cl ON ch.class_id = cl.id JOIN Menu_Items m ON ch.menu_item_id = m.id WHERE ch.week_id = ? AND ch.year = ? GROUP BY ch.day_of_week, cl.name, cl.id, m.item_name, m.id ORDER BY ch.day_of_week, cl.name, m.item_name""", (week_number, year)).fetchall()
        daily_data = {}
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        for i in range(5):
            date_obj = start_dt + timedelta(days=i)
            date = date_obj.strftime('%Y-%m-%d')
            day_name = date_obj.strftime('%A %d %b %Y')
            is_packed = i in packed_lunch_days
            daily_data[date] = {'day_name': day_name, 'day_of_week': i, 'is_packed_lunch_day': is_packed, 'classes': [{'name': cls['name'], 'id': cls['id']} for cls in classes], 'menu_items': [{'name': item['item_name'], 'id': item['id']} for item in menu_items], 'data': {}, 'class_totals': {}, 'item_totals': {}}
            for cls in classes:
                daily_data[date]['data'][cls['id']] = {}
                daily_data[date]['class_totals'][cls['id']] = 0
                for item in menu_items:
                    daily_data[date]['data'][cls['id']][item['id']] = 0
            for item in menu_items:
                daily_data[date]['item_totals'][item['id']] = 0
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

def save_choice(student_id, menu_item_id, class_id, date_str):
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
        week_number = date.isocalendar()[1]
        year = date.year
        day_of_week = date.weekday()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM Choices WHERE student_id = ? AND week_id = ? AND year = ? AND day_of_week = ?", (student_id, week_number, year, day_of_week))
            if menu_item_id:
                conn.execute("INSERT INTO Choices (student_id, menu_item_id, class_id, week_id, year, day_of_week, timestamp) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)", (student_id, menu_item_id, class_id, week_number, year, day_of_week))
            conn.commit()
            return True
    except Exception as e:
        print(f"Database error: {e}")
        return False

def get_available_weeks():
    with get_db_connection() as conn:
        weeks = conn.execute("SELECT id, week_number, year, cycle_number FROM Week_Cycle ORDER BY year, week_number").fetchall()
        formatted_weeks = []
        for week in weeks:
            jan_4 = datetime(week['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=week['week_number'] - 1)
            friday = target_monday + timedelta(days=4)
            display_text = f"{target_monday.strftime('%d %b')} to {friday.strftime('%d %b %Y')} - Week Cycle {week['cycle_number']}"
            formatted_weeks.append({'start_date': target_monday.strftime('%Y-%m-%d'), 'end_date': friday.strftime('%Y-%m-%d'), 'week_number': week['week_number'], 'cycle_number': week['cycle_number'], 'display_text': display_text})
        return formatted_weeks

def week_exists(week_monday_str):
    date = datetime.strptime(week_monday_str, '%Y-%m-%d')
    week_number = date.isocalendar()[1]
    year = date.year
    with get_db_connection() as conn:
        result = conn.execute("SELECT 1 FROM Week_Cycle WHERE week_number = ? AND year = ?", (week_number, year)).fetchone()
        return result is not None

def get_current_week_monday():
    today = datetime.now().date()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)
    return current_monday.strftime('%Y-%m-%d')

def get_next_week_monday():
    today = datetime.now().date()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    with get_db_connection() as conn:
        result = conn.execute("SELECT week_number, year FROM Week_Cycle WHERE year > ? OR (year = ? AND week_number >= ?) ORDER BY year ASC, week_number ASC LIMIT 1", (this_monday.year, this_monday.year, this_monday.isocalendar()[1])).fetchone()
        if result:
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            next_monday = this_monday + timedelta(days=7)
            return next_monday.strftime('%Y-%m-%d')

def get_week_cycle(date_str):
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
    except Exception:
        return None
    week_number = date.isocalendar()[1]
    year = date.year
    conn = get_db_connection()
    row = conn.execute("SELECT cycle_number FROM Week_Cycle WHERE week_number = ? AND year = ?", (week_number, year)).fetchone()
    if row:
        conn.close()
        return row['cycle_number']
    row = conn.execute("SELECT cycle_number FROM Week_Cycle WHERE year = ? ORDER BY ABS(week_number - ?) LIMIT 1", (year, week_number)).fetchone()
    conn.close()
    return row['cycle_number'] if row else None

def is_week_editable(selected_week_str):
    selected_monday = datetime.strptime(selected_week_str, '%Y-%m-%d').date()
    today = datetime.now().date()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)
    previous_monday = current_monday - timedelta(days=7)
    return selected_monday > previous_monday

def is_packed_lunch_day(week_number, year, day_of_week):
    human_day = day_of_week + 1
    with get_db_connection() as conn:
        result = conn.execute("SELECT CASE WHEN ',' || COALESCE(packed_lunch, '') || ',' LIKE '%,' || ? || ',%' THEN 1 ELSE 0 END AS has_packed_lunch FROM Week_Cycle WHERE week_number = ? AND year = ?", (human_day, week_number, year)).fetchone()
        return bool(result[0]) if result else False

def get_packed_lunch_days(week_number, year):
    packed_days = []
    for python_day in range(5):
        if is_packed_lunch_day(week_number, year, python_day):
            packed_days.append(python_day)
    return packed_days

def get_previous_week_monday(current_week_str):
    current_date = datetime.strptime(current_week_str, '%Y-%m-%d').date()
    current_week_num = current_date.isocalendar()[1]
    current_year = current_date.year
    with get_db_connection() as conn:
        result = conn.execute("SELECT week_number, year FROM Week_Cycle WHERE year < ? OR (year = ? AND week_number < ?) ORDER BY year DESC, week_number DESC LIMIT 1", (current_year, current_year, current_week_num)).fetchone()
        if result:
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            previous_monday = current_date - timedelta(days=7)
            return previous_monday.strftime('%Y-%m-%d')

def get_next_week_monday_from_date(current_week_str):
    current_date = datetime.strptime(current_week_str, '%Y-%m-%d').date()
    current_week_num = current_date.isocalendar()[1]
    current_year = current_date.year
    with get_db_connection() as conn:
        result = conn.execute("SELECT week_number, year FROM Week_Cycle WHERE year > ? OR (year = ? AND week_number > ?) ORDER BY year ASC, week_number ASC LIMIT 1", (current_year, current_year, current_week_num)).fetchone()
        if result:
            jan_4 = datetime(result['year'], 1, 4)
            week_1_monday = jan_4 - timedelta(days=jan_4.weekday())
            target_monday = week_1_monday + timedelta(weeks=result['week_number'] - 1)
            return target_monday.strftime('%Y-%m-%d')
        else:
            next_monday = current_date + timedelta(days=7)
            return next_monday.strftime('%Y-%m-%d')

def get_previous_cycle_week(class_id, week_number, year):
    with get_db_connection() as conn:
        current_cycle = conn.execute("SELECT cycle_number FROM Week_Cycle WHERE week_number = ? AND year = ?", (week_number, year)).fetchone()
        if not current_cycle:
            return None, None
        cycle_num = current_cycle['cycle_number']
        result = conn.execute("SELECT wc.week_number, wc.year FROM Week_Cycle wc WHERE wc.cycle_number = ? AND (wc.year < ? OR (wc.year = ? AND wc.week_number < ?)) AND EXISTS (SELECT 1 FROM Choices c WHERE c.week_id = wc.week_number AND c.year = wc.year AND c.class_id = ?) ORDER BY wc.year DESC, wc.week_number DESC LIMIT 1", (cycle_num, year, year, week_number, class_id)).fetchone()
        return (result['week_number'], result['year']) if result else (None, None)

def duplicate_choices_from_previous_cycle(class_id, from_week, from_year, to_week, to_year):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM Choices WHERE class_id = ? AND week_id = ? AND year = ?", (class_id, to_week, to_year))
            conn.execute("INSERT INTO Choices (student_id, menu_item_id, class_id, week_id, year, day_of_week, timestamp) SELECT student_id, menu_item_id, class_id, ?, ?, day_of_week, CURRENT_TIMESTAMP FROM Choices WHERE class_id = ? AND week_id = ? AND year = ?", (to_week, to_year, class_id, from_week, from_year))
            conn.commit()
            count = conn.execute("SELECT COUNT(*) as total FROM Choices WHERE class_id = ? AND week_id = ? AND year = ?", (class_id, to_week, to_year)).fetchone()['total']
            return True, count
    except Exception as e:
        print(f"Error duplicating choices: {e}")
        return False, 0

@app.route('/')
def index():
    return render_template('index.html', classes=get_classes(), students=get_all_students(), menu_items=get_menu_items())

@app.route('/teacher_menu/<int:class_id>')
def teacher_menu(class_id):

    selected_week = request.args.get(
        'week',
        get_next_week_monday()
    )

    with get_db_connection() as conn:

        class_info = conn.execute(
            '''
            SELECT *
            FROM Class
            WHERE id = ?
            ''',
            (class_id,)
        ).fetchone()

        # ADMIN MODAL DATA
        all_students = conn.execute('''
            SELECT id, first_name, last_name
            FROM Student
            ORDER BY last_name, first_name
        ''').fetchall()

        all_classes = conn.execute('''
            SELECT id, name
            FROM Class
            ORDER BY name
        ''').fetchall()

        all_menu_items = conn.execute('''
            SELECT id, item_name
            FROM Menu_Items
            ORDER BY item_name
        ''').fetchall()

        print(conn)
        print(conn.execute("PRAGMA database_list").fetchall())

    if class_info is None:
        flash('Class not found', 'error')
        return redirect(url_for('index'))

    start_date = datetime.strptime(
        selected_week,
        '%Y-%m-%d'
    )

    week_number = start_date.isocalendar()[1]
    year = start_date.year

    week_cycle = get_week_cycle(selected_week)

    week_cycle_exists = (
        week_cycle is not None
    )

    display_week_cycle = (
        week_cycle if week_cycle else 1
    )

    student_choices = get_week_choices_by_class(
        class_id,
        week_number,
        year
    )

    packed_lunch_days = get_packed_lunch_days(
        week_number,
        year
    )

    students = get_students_by_class(class_id)

    week_dates = []

    for i in range(5):

        date = start_date + timedelta(days=i)

        is_packed = (
            i in packed_lunch_days
        )

        menu_items = get_menu_items_for_day(
            i,
            display_week_cycle
        )

        week_dates.append({
            'date': date.strftime('%Y-%m-%d'),
            'day_name': date.strftime('%A'),
            'display_date': date.strftime('%d-%b'),
            'day_index': i,
            'menu_items': menu_items,
            'is_packed_lunch_day': is_packed
        })

    available_weeks = get_available_weeks()

    is_editable = (
        is_week_editable(selected_week)
        and week_cycle_exists
    )

    previous_week = get_previous_week_monday(
        selected_week
    )

    next_week = get_next_week_monday_from_date(
        selected_week
    )

    current_week = get_next_week_monday()

    has_previous_week = week_exists(
        previous_week
    )

    has_next_week = week_exists(
        next_week
    )

    is_current_week = (
        selected_week == current_week
    )

    is_future_week = (
        is_editable and not is_current_week
    )

    prev_cycle_week, prev_cycle_year = (
        get_previous_cycle_week(
            class_id,
            week_number,
            year
        )
    )

    has_previous_cycle = (
        prev_cycle_week is not None
    )

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

        year=year,

        # ADMIN MODAL DATA
        all_students=all_students,
        all_classes=all_classes,
        all_menu_items=all_menu_items
    )
@app.route('/export_class_choices/<int:class_id>')
def export_class_choices(class_id):
    selected_week = request.args.get('week', get_next_week_monday())
    class_info = get_class_by_id(class_id)
    if not class_info:
        flash('Class not found', 'error')
        return redirect(url_for('index'))
    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)
    display_week_cycle = week_cycle if week_cycle else 1
    packed_lunch_days = get_packed_lunch_days(week_number, year)
    students = get_students_by_class(class_id)
    student_choices = get_week_choices_by_class(class_id, week_number, year)
    week_dates = []
    for i in range(5):
        date = start_date + timedelta(days=i)
        menu_items = get_menu_items_for_day(i, display_week_cycle)
        week_dates.append({'date': date.strftime('%Y-%m-%d'), 'day_name': date.strftime('%A'), 'display_date': date.strftime('%d-%b'), 'day_index': i, 'menu_items': menu_items, 'is_packed_lunch_day': i in packed_lunch_days})
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet('Class Choices')
    title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#2c3e50'})
    subtitle_fmt = workbook.add_format({'italic': True, 'font_size': 11, 'font_color': '#7f8c8d'})
    col_header_fmt = workbook.add_format({'bold': True, 'bg_color': '#2c3e50', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
    packed_col_header_fmt = workbook.add_format({'bold': True, 'bg_color': '#e74c3c', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
    student_fmt = workbook.add_format({'bold': True, 'bg_color': '#f8f9fa', 'border': 1, 'align': 'left'})
    choice_fmt = workbook.add_format({'border': 1, 'align': 'center', 'bg_color': '#ffffff'})
    empty_fmt = workbook.add_format({'border': 1, 'align': 'center', 'font_color': '#cccccc'})
    alt_choice_fmt = workbook.add_format({'border': 1, 'align': 'center', 'bg_color': '#f2f4f7'})
    alt_empty_fmt = workbook.add_format({'border': 1, 'align': 'center', 'font_color': '#cccccc', 'bg_color': '#f2f4f7'})
    ws.set_column('A:A', 28)
    ws.set_column('B:F', 22)
    row = 0
    ws.write(row, 0, f"Class: {class_info['name']}", title_fmt)
    row += 1
    ws.write(row, 0, f"Week of {start_date.strftime('%d %b %Y')}  —  Cycle {display_week_cycle}", subtitle_fmt)
    row += 2
    ws.write(row, 0, 'Student Name', col_header_fmt)
    for col_i, day in enumerate(week_dates):
        label = f"{day['day_name']}\n{day['display_date']}" + ('\n(Packed)' if day['is_packed_lunch_day'] else '')
        fmt = packed_col_header_fmt if day['is_packed_lunch_day'] else col_header_fmt
        ws.write(row, col_i + 1, label, fmt)
    ws.set_row(row, 45)
    row += 1
    for s_idx, student in enumerate(students):
        sid = student['id']
        name = f"{student['last_name']}, {student['first_name']}"
        is_alt_row = (s_idx % 2 == 1)
        ws.write(row, 0, name, student_fmt)
        for col_i, day in enumerate(week_dates):
            didx = day['day_index']
            choice_label = '-'
            if sid in student_choices and didx in student_choices[sid]['choices']:
                item_id = student_choices[sid]['choices'][didx]
                for item in day['menu_items']:
                    if item['id'] == item_id:
                        choice_label = item['item_name']
                        break
            fmt = (alt_empty_fmt if is_alt_row else empty_fmt) if choice_label == '-' else (alt_choice_fmt if is_alt_row else choice_fmt)
            ws.write(row, col_i + 1, choice_label, fmt)
        row += 1
    workbook.close()
    output.seek(0)
    safe_name = class_info['name'].replace(' ', '_')
    filename = f"{safe_name}_choices_{selected_week}.xlsx"
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)

@app.route('/auto_save', methods=['POST'])
def auto_save():
    try:
        data = request.get_json()
        student_id = int(data['student_id'])
        date = data['date']
        class_id = int(data['class_id'])
        menu_item_id = int(data['menu_item_id']) if data['menu_item_id'] else None
        choice_date = datetime.strptime(date, '%Y-%m-%d').date()
        today = datetime.now().date()
        days_since_monday = choice_date.weekday()
        choice_week_monday = choice_date - timedelta(days=days_since_monday)
        today_days_since_monday = today.weekday()
        current_monday = today - timedelta(days=today_days_since_monday)
        if choice_week_monday <= current_monday:
            return jsonify({'success': False, 'message': 'Cannot edit - this week has started. Kitchen is preparing meals.'}), 403
        if save_choice(student_id, menu_item_id, class_id, date):
            return jsonify({'success': True, 'message': 'Saved'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save'}), 500
    except Exception as e:
        print(f"Auto-save error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/duplicate_previous_cycle/<int:class_id>', methods=['POST'])
def duplicate_previous_cycle(class_id):
    try:
        data = request.get_json()
        current_week = data.get('week_number')
        current_year = data.get('year')
        prev_week, prev_year = get_previous_cycle_week(class_id, current_week, current_year)
        if not prev_week or not prev_year:
            return jsonify({'success': False, 'message': 'No previous cycle week found with existing choices'}), 404
        success, count = duplicate_choices_from_previous_cycle(class_id, prev_week, prev_year, current_week, current_year)
        if success:
            return jsonify({'success': True, 'message': f'Successfully copied {count} choices from Week {prev_week}/{prev_year}', 'count': count})
        else:
            return jsonify({'success': False, 'message': 'Failed to duplicate choices'}), 500
    except Exception as e:
        print(f"Duplicate error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/summary')
@app.route('/summary/<int:class_id>')
def summary_board(class_id=None):
    selected_week = request.args.get('week', get_current_week_monday())
    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)
    week_cycle_exists = week_cycle is not None
    display_week_cycle = week_cycle if week_cycle else 1
    if not week_cycle_exists:
        flash('This week has no cycle configured in the database', 'error')
        return redirect(url_for('teacher_menu', class_id=class_id)) if class_id else redirect(url_for('index'))
    packed_lunch_days = get_packed_lunch_days(week_number, year)
    previous_week = get_previous_week_monday(selected_week)
    next_week = get_next_week_monday_from_date(selected_week)
    current_week = get_current_week_monday()
    has_previous_week = week_exists(previous_week)
    has_next_week = week_exists(next_week)
    available_weeks = get_available_weeks()
    week_dates = [{'display_date': (start_date + timedelta(days=i)).strftime('%d %b'), 'full_date': (start_date + timedelta(days=i)).strftime('%d %b %Y'), 'date': (start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 'day_name': (start_date + timedelta(days=i)).strftime('%A')} for i in range(5)]
    class_info = None
    if class_id:
        class_info = get_class_by_id(class_id)
        if not class_info:
            flash('Class not found', 'error')
            return redirect(url_for('index'))
    daily_data = []
    for day_index in range(5):
        date = start_date + timedelta(days=day_index)
        day_name = date.strftime('%A %d %b %Y')
        is_packed = day_index in packed_lunch_days
        menu_items = get_menu_items_for_day(day_index, display_week_cycle)
        menu_item_names = [item['item_name'] for item in menu_items]
        if class_id:
            with get_db_connection() as conn:
                choices = conn.execute("SELECT m.item_name, COUNT(*) as count FROM Choices ch JOIN Menu_Items m ON ch.menu_item_id = m.id WHERE ch.class_id = ? AND ch.week_id = ? AND ch.year = ? AND ch.day_of_week = ? GROUP BY m.item_name", (class_id, week_number, year, day_index)).fetchall()
            class_data = {item_name: 0 for item_name in menu_item_names}
            for choice in choices:
                if choice['item_name'] in class_data:
                    class_data[choice['item_name']] = choice['count']
            daily_data.append({'day_name': day_name, 'is_packed_lunch_day': is_packed, 'menu_items': menu_item_names, 'classes': [{'name': class_info['name'], 'data': class_data}], 'total': {item: class_data[item] for item in menu_item_names}})
        else:
            all_classes = get_classes()
            with get_db_connection() as conn:
                choices = conn.execute("SELECT ch.class_id, cl.name as class_name, m.item_name, COUNT(*) as count FROM Choices ch JOIN Class cl ON ch.class_id = cl.id JOIN Menu_Items m ON ch.menu_item_id = m.id WHERE ch.week_id = ? AND ch.year = ? AND ch.day_of_week = ? GROUP BY ch.class_id, cl.name, m.item_name ORDER BY cl.name, m.item_name", (week_number, year, day_index)).fetchall()
            classes_data = []
            totals = {item_name: 0 for item_name in menu_item_names}
            for class_obj in all_classes:
                class_data = {item_name: 0 for item_name in menu_item_names}
                for choice in choices:
                    if choice['class_name'] == class_obj['name'] and choice['item_name'] in class_data:
                        class_data[choice['item_name']] = choice['count']
                        totals[choice['item_name']] += choice['count']
                classes_data.append({'name': class_obj['name'], 'data': class_data})
            daily_data.append({'day_name': day_name, 'is_packed_lunch_day': is_packed, 'menu_items': menu_item_names, 'classes': classes_data, 'total': totals})
    return render_template('summary_board.html', daily_data=daily_data, class_info=class_info, selected_week=selected_week, week_number=week_number, week_cycle=display_week_cycle, week_dates=week_dates, available_weeks=available_weeks, previous_week=previous_week, next_week=next_week, current_week=current_week, has_previous_week=has_previous_week, has_next_week=has_next_week, all_menu_items=all_menu_items)

@app.route('/export_summary_excel')
def export_summary_excel():
    selected_week = request.args.get('week', get_current_week_monday())
    start_date = datetime.strptime(selected_week, '%Y-%m-%d')
    week_number = start_date.isocalendar()[1]
    year = start_date.year
    week_cycle = get_week_cycle(selected_week)
    if week_cycle is None:
        flash('Cannot export - this week has no cycle configured in the database', 'error')
        return redirect(url_for('summary_board', week=selected_week))
    packed_lunch_days = get_packed_lunch_days(week_number, year)
    daily_breakdown = get_daily_breakdown_by_class(selected_week)
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    title_format = workbook.add_format({'bold': True, 'font_size': 16, 'font_color': '#2c3e50', 'align': 'left'})
    subtitle_format = workbook.add_format({'font_size': 12, 'font_color': '#7f8c8d', 'italic': True, 'align': 'left'})
    day_header_format = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#2c3e50', 'bg_color': '#ecf0f1', 'border': 1, 'align': 'center'})
    packed_lunch_day_header_format = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#000000', 'bg_color': '#FFFF00', 'border': 2, 'align': 'center'})
    table_header_format = workbook.add_format({'bold': True, 'bg_color': '#34495e', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
    class_name_format = workbook.add_format({'bold': True, 'bg_color': '#f8f9fa', 'border': 1, 'align': 'left'})
    data_format = workbook.add_format({'border': 1, 'align': 'center'})
    total_row_format = workbook.add_format({'bold': True, 'bg_color': '#d5e8d4', 'border': 2, 'align': 'center'})
    total_label_format = workbook.add_format({'bold': True, 'bg_color': '#d5e8d4', 'border': 2, 'align': 'left'})
    grand_total_format = workbook.add_format({'bold': True, 'bg_color': '#6b8e65', 'font_color': 'white', 'border': 2, 'align': 'center', 'font_size': 11})
    worksheet = workbook.add_worksheet('Lunch Summary')
    worksheet.set_column('A:A', 25)
    worksheet.set_column('B:Z', 15)
    current_row = 0
    worksheet.write(current_row, 0, f'Lunch Selection Summary - Week {week_number} (Cycle {week_cycle})', title_format)
    current_row += 1
    worksheet.write(current_row, 0, f'Week of {start_date.strftime("%d %b %Y")}', subtitle_format)
    current_row += 2
    for date, data in sorted(daily_breakdown.items()):
        if sum(data['item_totals'].values()) > 0:
            day_of_week = data['day_of_week']
            is_packed_lunch_flag = day_of_week in packed_lunch_days
            if is_packed_lunch_flag:
                header_format = packed_lunch_day_header_format
                day_header_text = f"{data['day_name']} - Packed Lunches Served in Classroom"
            else:
                header_format = day_header_format
                day_header_text = data['day_name']
            worksheet.merge_range(current_row, 0, current_row, len(data['menu_items']), day_header_text, header_format)
            current_row += 1
            worksheet.write(current_row, 0, 'Class / Menu Item', table_header_format)
            col = 1
            for item in data['menu_items']:
                worksheet.write(current_row, col, item['name'], table_header_format)
                col += 1
            worksheet.write(current_row, col, 'Total', table_header_format)
            worksheet.set_row(current_row, 40)
            current_row += 1
            for cls in data['classes']:
                worksheet.write(current_row, 0, cls['name'], class_name_format)
                col = 1
                for item in data['menu_items']:
                    count = data['data'][cls['id']][item['id']]
                    worksheet.write(current_row, col, count if count > 0 else '', data_format)
                    col += 1
                class_total = data['class_totals'][cls['id']]
                worksheet.write(current_row, col, class_total if class_total > 0 else '', data_format)
                current_row += 1
            worksheet.write(current_row, 0, 'TOTAL', total_label_format)
            col = 1
            for item in data['menu_items']:
                total = data['item_totals'][item['id']]
                worksheet.write(current_row, col, total if total > 0 else '', total_row_format)
                col += 1
            grand_total = sum(data['item_totals'].values())
            worksheet.write(current_row, col, grand_total, grand_total_format)
            current_row += 3
    workbook.close()
    output.seek(0)
    filename = f'lunch_summary_week_{week_number}_{start_date.strftime("%Y-%m-%d")}.xlsx'
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)

@app.route('/admin/student/<int:student_id>')
def get_student(student_id):
    with get_db_connection() as conn:
        student = conn.execute('SELECT * FROM Student WHERE id = ?', (student_id,)).fetchone()
    if student:
        return jsonify({'id': student['id'], 'first_name': student['first_name'], 'last_name': student['last_name'], 'admission_no': student['admission_no'], 'class_id': student['class_id']})
    return jsonify({'error': 'Student not found'}), 404

@app.route('/admin/student/save', methods=['POST'])
def save_student():
    try:
        data = request.get_json()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        admission_no = data.get('admission_no', '').strip()
        class_id = data.get('class_id')

        if class_id in [None, '', 'null']:
            return jsonify({
                'success': False,
                'message': 'Class required'
            }), 400

        class_id = int(class_id)
        student_id = data.get('student_id')
        if not first_name or not last_name or not admission_no or not class_id:
            return jsonify({'success': False, 'message': 'All fields required'}), 400
        with get_db_connection() as conn:

            if student_id:

                conn.execute(
                    """
                    UPDATE Student
                    SET first_name = ?,
                        last_name = ?,
                        admission_no = ?,
                        class_id = ?
                    WHERE id = ?
                    """,
                    (
                        first_name,
                        last_name,
                        admission_no,
                        class_id,
                        int(student_id)
                    )
                )

                message = f"Updated {last_name}, {first_name}"

            else:

                conn.execute(
                    """
                    INSERT INTO Student
                    (
                        first_name,
                        last_name,
                        admission_no,
                        class_id
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        first_name,
                        last_name,
                        admission_no,
                        class_id
                    )
                )

                message = f"Created {last_name}, {first_name}"

            print("SAVING STUDENT:", first_name, last_name, class_id)

            conn.commit()
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        print(f"Student save error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/student/delete/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    try:
        with get_db_connection() as conn:
            conn.execute('DELETE FROM Choices WHERE student_id = ?', (student_id,))
            conn.execute('DELETE FROM Student WHERE id = ?', (student_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Student deleted'})
    except Exception as e:
        print(f"Student delete error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/menu_item/<int:item_id>')
def get_menu_item(item_id):
    with get_db_connection() as conn:
        item = conn.execute('SELECT * FROM Menu_Items WHERE id = ?', (item_id,)).fetchone()
    if item:
        return jsonify({'id': item['id'], 'item_name': item['item_name'], 'mon': item['mon'], 'tue': item['tue'], 'wed': item['wed'], 'thu': item['thu'], 'fri': item['fri'], 'week_cycle1': item['week_cycle1'], 'week_cycle2': item['week_cycle2'], 'week_cycle3': item['week_cycle3']})
    return jsonify({'error': 'Menu item not found'}), 404

@app.route('/admin/menu_item/save', methods=['POST'])
def save_menu_item():
    try:
        data = request.get_json()
        item_name = data.get('item_name', '').strip()
        mon = 1 if data.get('mon') else 0
        tue = 1 if data.get('tue') else 0
        wed = 1 if data.get('wed') else 0
        thu = 1 if data.get('thu') else 0
        fri = 1 if data.get('fri') else 0
        week_cycle1 = 1 if data.get('week_cycle1') else 0
        week_cycle2 = 1 if data.get('week_cycle2') else 0
        week_cycle3 = 1 if data.get('week_cycle3') else 0
        item_id = data.get('item_id')
        if not item_name:
            return jsonify({'success': False, 'message': 'Item name required'}), 400
        with get_db_connection() as conn:
            print(conn)
            print(conn.execute("PRAGMA database_list").fetchall())

            if item_id:
                conn.execute("UPDATE Menu_Items SET item_name = ?, mon = ?, tue = ?, wed = ?, thu = ?, fri = ?, week_cycle1 = ?, week_cycle2 = ?, week_cycle3 = ? WHERE id = ?", (item_name, mon, tue, wed, thu, fri, week_cycle1, week_cycle2, week_cycle3, int(item_id)))
                message = f"Updated '{item_name}'"
            else:
                conn.execute("INSERT INTO Menu_Items (item_name, mon, tue, wed, thu, fri, week_cycle1, week_cycle2, week_cycle3) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (item_name, mon, tue, wed, thu, fri, week_cycle1, week_cycle2, week_cycle3))
                message = f"Created '{item_name}'"
                print("SAVING:")
                print({
                    "item_name": item_name,
                    "mon": mon,
                    "tue": tue,
                    "wed": wed,
                    "thu": thu,
                    "fri": fri,
                    "week_cycle1": week_cycle1,
                    "week_cycle2": week_cycle2,
                    "week_cycle3": week_cycle3
                })
            conn.commit()
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        print(f"Menu item save error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/menu_item/delete/<int:item_id>', methods=['POST'])
def delete_menu_item(item_id):
    try:
        with get_db_connection() as conn:
            conn.execute('DELETE FROM Choices WHERE menu_item_id = ?', (item_id,))
            conn.execute('DELETE FROM Menu_Items WHERE id = ?', (item_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Menu item deleted'})
    except Exception as e:
        print(f"Menu item delete error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
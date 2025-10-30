from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import os

DB_PATH = 'cafeteria.db'

app = Flask(__name__)
app.secret_key = 'my-cafeteria-app-secret-key-2024'


# ---------------------------------------------------------------------
#  Database helpers
# ---------------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_classes():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Class ORDER BY name').fetchall()


def get_menu_items():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM Menu_Items ORDER BY name').fetchall()


def get_students_by_class(class_id):
    with get_db_connection() as conn:
        return conn.execute(
            'SELECT * FROM Student WHERE class_id = ? ORDER BY name',
            (class_id,)
        ).fetchall()


def save_choice(student_id, menu_item_id, class_id):
    try:
        with get_db_connection() as conn:
            # First, delete any existing choice for this student today
            today = datetime.now().date()
            conn.execute("""
                DELETE FROM Choices 
                WHERE student_id = ? AND date = ?
            """, (student_id, today))

            # Then insert the new choice
            conn.execute("""
                INSERT INTO Choices
                (student_id, menu_item_id, date, class_id)
                VALUES (?, ?, ?, ?)
            """, (student_id, menu_item_id, today, class_id))
            conn.commit()
            return True
    except sqlite3.IntegrityError as e:
        print(f"Database integrity error: {e}")
        return False
    except Exception as e:
        print(f"Database error: {e}")
        return False


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


def get_today_choices_by_class(class_id):
    with get_db_connection() as conn:
        return conn.execute("""
            SELECT s.name as student_name,
                   m.name as menu_item_name
            FROM Choices c
            JOIN Student s ON c.student_id = s.id
            JOIN Menu_Items m ON c.menu_item_id = m.id
            WHERE c.class_id = ? AND DATE(c.date) = DATE('now')
            ORDER BY s.name
        """, (class_id,)).fetchall()


# ---------------------------------------------------------------------
#  Routes
# ---------------------------------------------------------------------
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

    # Get today's choices for this class
    today_choices = get_today_choices_by_class(class_id)

    return render_template(
        'teacher_menu.html',
        class_info=class_info,
        menu_items=get_menu_items(),
        students=get_students_by_class(class_id),
        today_choices=today_choices
    )


@app.route('/save_selections', methods=['POST'])
def save_selections():
    try:
        class_id = request.form.get('class_id')
        if not class_id:
            flash('Class ID missing', 'error')
            return redirect(url_for('index'))

        # Convert class_id to integer
        class_id = int(class_id)

        # Track if any selections were saved
        selections_saved = 0
        errors = 0

        # Process each student selection
        for key, value in request.form.items():
            if key.startswith('student_'):
                try:
                    student_id = int(key.split('_', 1)[1])
                    if value:  # Only save if a menu item was selected
                        menu_item_id = int(value)
                        if save_choice(student_id, menu_item_id, class_id):
                            selections_saved += 1
                        else:
                            errors += 1
                except ValueError as e:
                    errors += 1
                    print(f"Invalid ID format: {e}")
                except Exception as e:
                    errors += 1
                    print(f"Error saving choice: {e}")

        # Provide feedback
        if selections_saved > 0 and errors == 0:
            flash(f'Successfully saved {selections_saved} selections!', 'success')
        elif selections_saved > 0 and errors > 0:
            flash(f'Saved {selections_saved} selections, but {errors} failed.', 'warning')
        elif errors > 0:
            flash(f'Failed to save selections. {errors} errors occurred.', 'error')
        else:
            flash('No selections to save', 'info')

        return redirect(url_for('teacher_menu', class_id=class_id))

    except Exception as e:
        flash(f'An unexpected error occurred: {str(e)}', 'error')
        print(f"Unexpected error in save_selections: {e}")
        return redirect(url_for('index'))


@app.route('/admin')
def admin_board():
    return render_template(
        'admin_board.html',
        choices=get_all_choices(),
        stats=get_choice_statistics()
    )


@app.route('/clear_today_choices/<int:class_id>')
def clear_today_choices(class_id):
    """Clear all choices for today for a specific class"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                DELETE FROM Choices 
                WHERE class_id = ? AND DATE(date) = DATE('now')
            """, (class_id,))
            conn.commit()
        flash('Today\'s choices cleared successfully!', 'success')
    except Exception as e:
        flash(f'Error clearing choices: {str(e)}', 'error')

    return redirect(url_for('teacher_menu', class_id=class_id))


# ---------------------------------------------------------------------
#  Boot-up
# ---------------------------------------------------------------------
if __name__ == '__main__':
    # Check if database exists
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found!")
        print("Please run database.py first to create and populate the database.")
        exit(1)

    print(f"Using database: {DB_PATH}")
    print("Starting Flask application...")
    print("Navigate to http://127.0.0.1:5000 in your browser")

    app.run(debug=True)
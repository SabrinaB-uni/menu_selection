from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date, timedelta
from database import db, Teacher, Student, MenuItem, Choice, WeekCycle, Class

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cafeteria.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'change-me-to-something-secure'

db.init_app(app)


def current_teacher():
    tid = session.get('teacher_id')
    return Teacher.query.get(tid) if tid else None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        teacher = Teacher.query.get(request.form['teacher_id'])
        if teacher:
            session['teacher_id'] = teacher.teacher_id
            return redirect(url_for('teacher_board'))
    teachers = Teacher.query.order_by(Teacher.last_name).all()
    return render_template('login.html', teachers=teachers)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/teacher')
def teacher_board():
    teacher = current_teacher()
    if not teacher:
        return redirect(url_for('login'))

    # Which Monday? Default = current week's Monday
    week_start_str = request.args.get('week_start')
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date() if week_start_str else monday

    students = Student.query.filter_by(class_id=teacher.class_id) \
        .order_by(Student.last_name, Student.first_name).all()
    menu_items = MenuItem.query.order_by(MenuItem.item_name).all()

    # Load existing choices for this week
    existing_choices = {}
    choices = Choice.query.filter_by(class_id=teacher.class_id) \
        .filter(Choice.choice_date.between(week_start, week_start + timedelta(days=4))) \
        .all()
    for choice in choices:
        key = f"{choice.student_id}-{choice.day_of_week}"
        existing_choices[key] = choice.item_id

    return render_template('teacher_board.html',
                           teacher=teacher,
                           students=students,
                           menu_items=menu_items,
                           week_start=week_start,
                           DAYS=DAYS,
                           existing_choices=existing_choices)


@app.route('/submit_week', methods=['POST'])
def submit_week():
    teacher = current_teacher()
    if not teacher:
        return redirect(url_for('login'))

    week_start = datetime.strptime(request.form['week_start'], '%Y-%m-%d').date()

    # Clear existing choices for that class & week
    Choice.query.filter_by(class_id=teacher.class_id) \
        .filter(Choice.choice_date.between(week_start, week_start + timedelta(days=4))) \
        .delete()
    db.session.commit()

    choices_to_add = []
    students = Student.query.filter_by(class_id=teacher.class_id).all()

    for student in students:
        for offset, day in enumerate(DAYS):
            field = f"c-{student.student_id}-{day}"
            item_id = request.form.get(field)
            if not item_id:
                continue

            choice_date = week_start + timedelta(days=offset)
            wc = WeekCycle.query.filter(WeekCycle.start_date <= choice_date,
                                        WeekCycle.end_date >= choice_date).first()

            choices_to_add.append(
                Choice(student_id=student.student_id,
                       class_id=teacher.class_id,
                       choice_date=choice_date,
                       day_of_week=day,
                       item_id=item_id,
                       week_number=wc.week_number if wc else None,
                       cycle_number=wc.cycle_number if wc else None)
            )

    db.session.bulk_save_objects(choices_to_add)
    db.session.commit()
    flash('Lunch orders saved successfully!', 'success')
    return redirect(url_for('teacher_board', week_start=week_start.isoformat()))


@app.route('/admin')
def admin_menu():
    # Get filter parameters
    filter_date = request.args.get('filter_date')
    filter_class = request.args.get('filter_class')

    query = Choice.query.join(Student).join(MenuItem)

    if filter_date:
        query = query.filter(Choice.choice_date == filter_date)
    if filter_class:
        query = query.filter(Choice.class_id == filter_class)

    choices = query.order_by(Choice.choice_date.desc(), Student.last_name).all()
    classes = Class.query.all()

    return render_template('admin_menu.html', choices=choices, classes=classes)


# Initialize database with sample data
def init_sample_data():
    if Class.query.count() == 0:
        # Add sample classes
        class1 = Class(class_name="Grade 1A")
        class2 = Class(class_name="Grade 1B")
        db.session.add_all([class1, class2])
        db.session.commit()

        # Add sample teacher
        teacher1 = Teacher(first_name="Jane", last_name="Smith",
                           email="jane.smith@school.com", class_id=class1.class_id)
        db.session.add(teacher1)

        # Add sample students
        students = [
            Student(first_name="John", last_name="Doe", class_id=class1.class_id, admission_number="001"),
            Student(first_name="Mary", last_name="Johnson", class_id=class1.class_id, admission_number="002"),
            Student(first_name="Peter", last_name="Brown", class_id=class1.class_id, admission_number="003")
        ]
        db.session.add_all(students)

        # Add sample menu items
        menu_items = [
            MenuItem(item_name="Pizza", monday=True, tuesday=True, wednesday=True, thursday=True, friday=True),
            MenuItem(item_name="Burger", monday=True, tuesday=True, wednesday=True, thursday=True, friday=True),
            MenuItem(item_name="Pasta", monday=True, tuesday=True, wednesday=True, thursday=True, friday=True),
            MenuItem(item_name="Sandwich", monday=True, tuesday=True, wednesday=True, thursday=True, friday=True),
            MenuItem(item_name="Salad", monday=True, tuesday=True, wednesday=True, thursday=True, friday=True)
        ]
        db.session.add_all(menu_items)

        # Add sample week cycle
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_cycle = WeekCycle(cycle_number=1, week_number=1,
                               start_date=monday, end_date=monday + timedelta(days=4))
        db.session.add(week_cycle)

        db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_sample_data()
    app.run(debug=True)
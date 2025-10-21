from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

class Class(db.Model):
    __tablename__ = 'classes'
    class_id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50), nullable=False)
    students = db.relationship('Student', backref='class_ref', lazy=True)
    teachers = db.relationship('Teacher', backref='class_ref', lazy=True)

class Student(db.Model):
    __tablename__ = 'students'
    student_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.class_id'))
    admission_number = db.Column(db.String(20), unique=True)
    choices = db.relationship('Choice', backref='student', lazy=True)

class Teacher(db.Model):
    __tablename__ = 'teachers'
    teacher_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.class_id'))

class WeekCycle(db.Model):
    __tablename__ = 'week_cycles'
    cycle_id = db.Column(db.Integer, primary_key=True)
    cycle_number = db.Column(db.Integer, nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)

class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    item_id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    monday = db.Column(db.Boolean, default=False)
    tuesday = db.Column(db.Boolean, default=False)
    wednesday = db.Column(db.Boolean, default=False)
    thursday = db.Column(db.Boolean, default=False)
    friday = db.Column(db.Boolean, default=False)
    choices = db.relationship('Choice', backref='menu_item', lazy=True)

class MenuAvailability(db.Model):
    __tablename__ = 'menu_availability'
    availability_id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('menu_items.item_id'))
    week_number = db.Column(db.Integer)
    cycle_number = db.Column(db.Integer)

class Choice(db.Model):
    __tablename__ = 'choices'
    choice_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.student_id'))
    class_id = db.Column(db.Integer, db.ForeignKey('classes.class_id'))
    choice_date = db.Column(db.Date)
    day_of_week = db.Column(db.String(10))
    item_id = db.Column(db.Integer, db.ForeignKey('menu_items.item_id'))
    week_number = db.Column(db.Integer)
    cycle_number = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
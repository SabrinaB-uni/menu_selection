from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def select_class():
    conn = get_db()
    classes = conn.execute('SELECT * FROM classes ORDER BY name').fetchall()
    conn.close()
    return render_template('select_class.html', classes=classes)

@app.route('/class/<int:class_id>')
def class_grid(class_id):
    week_number = request.args.get('week', get_current_week())

    conn = get_db()



import sqlite3
import os
from datetime import datetime


def init_database():
    """Initialize the database with tables"""
    conn = sqlite3.connect('cafeteria.db')
    cursor = conn.cursor()

    # Enable foreign key constraints
    cursor.execute("PRAGMA foreign_keys = ON")

    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Class (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Menu_Items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Student (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES Class(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Week_Cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Choices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            date DATE NOT NULL,
            FOREIGN KEY (student_id) REFERENCES Student(id),
            FOREIGN KEY (menu_item_id) REFERENCES Menu_Items(id),
            FOREIGN KEY (class_id) REFERENCES Class(id),
            UNIQUE(student_id, date)
        )
    ''')

    conn.commit()
    conn.close()
    print("Database tables created successfully!")


def add_sample_data():
    """Add sample data for testing"""
    conn = sqlite3.connect('cafeteria.db')
    cursor = conn.cursor()

    # Enable foreign key constraints
    cursor.execute("PRAGMA foreign_keys = ON")

    try:
        # Sample classes
        sample_classes = [
            'Reception A', 'Reception B',
            'Year 1A', 'Year 1B',
            'Year 2A', 'Year 2B',
            'Year 3A', 'Year 3B'
        ]

        for class_name in sample_classes:
            cursor.execute('INSERT OR IGNORE INTO Class (name) VALUES (?)', (class_name,))

        conn.commit()

        # Sample menu items
        sample_menu = [
            'Pizza Slice',
            'Chicken Sandwich',
            'Vegetable Soup',
            'Fruit Salad',
            'Hamburger',
            'Fish Fillet',
            'Pasta',
            'Grilled Chicken',
            'Jacket Potato with Beans',
            'Jacket Potato with Cheese',
            'No Lunch'
        ]

        for menu_item in sample_menu:
            cursor.execute('INSERT OR IGNORE INTO Menu_Items (name) VALUES (?)', (menu_item,))

        conn.commit()

        # Get class IDs and add students
        class_students = {
            'Reception A': ['Emma Thompson', 'Oliver James', 'Sophie Chen', 'Noah Williams', 'Ava Brown'],
            'Reception B': ['Liam Davis', 'Isabella Garcia', 'Mason Miller', 'Mia Wilson', 'Lucas Moore'],
            'Year 1A': ['Alice Johnson', 'Bob Smith', 'Charlie Brown', 'Diana Prince', 'Eve Wilson'],
            'Year 1B': ['Frank Miller', 'Grace Lee', 'Henry Davis', 'Iris Chen', 'Jack Wilson'],
            'Year 2A': ['Kate Anderson', 'Leo Martinez', 'Maya Patel', 'Nathan Taylor', 'Olivia White'],
            'Year 2B': ['Peter Parker', 'Quinn Roberts', 'Ruby Singh', 'Sam Jackson', 'Tara Kumar']
        }

        for class_name, students in class_students.items():
            cursor.execute("SELECT id FROM Class WHERE name = ?", (class_name,))
            result = cursor.fetchone()
            if result:
                class_id = result[0]
                for student_name in students:
                    cursor.execute('''
                        INSERT OR IGNORE INTO Student (name, class_id) 
                        VALUES (?, ?)
                    ''', (student_name, class_id))

        conn.commit()
        print("Sample data added successfully!")

    except sqlite3.IntegrityError as e:
        print(f"Error adding sample data: {e}")
        conn.rollback()
    except Exception as e:
        print(f"Unexpected error: {e}")
        conn.rollback()
    finally:
        conn.close()


def reset_database():
    """Drop all tables and recreate them"""
    if os.path.exists('cafeteria.db'):
        os.remove('cafeteria.db')
        print("Existing database removed.")

    init_database()
    add_sample_data()
    print("Database reset complete!")


def view_data():
    """View current data in the database"""
    conn = sqlite3.connect('cafeteria.db')
    cursor = conn.cursor()

    print("\n--- Classes ---")
    cursor.execute("SELECT * FROM Class")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, Name: {row[1]}")

    print("\n--- Menu Items ---")
    cursor.execute("SELECT * FROM Menu_Items")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, Name: {row[1]}")

    print("\n--- Students (first 10) ---")
    cursor.execute("SELECT s.id, s.name, c.name FROM Student s JOIN Class c ON s.class_id = c.id LIMIT 10")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, Name: {row[1]}, Class: {row[2]}")

    conn.close()


if __name__ == '__main__':
    # Check if database exists
    if not os.path.exists('cafeteria.db'):
        print("Creating new database...")
        init_database()
        add_sample_data()
    else:
        print("Database already exists.")
        response = input("Do you want to reset it? (yes/no): ").lower()
        if response == 'yes':
            reset_database()

    # Show some data
    view_data()
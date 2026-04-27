import sqlite3
import os
import time
from datetime import datetime

class AttendanceManager:
    def __init__(self, db_path="attendance.db"):
        self.db_path = db_path
        self._cache = {} # memory debounce
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite database tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Students Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    gesture_name TEXT NOT NULL UNIQUE,
                    roll_number TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Attendance Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'PRESENT',
                    FOREIGN KEY (student_id) REFERENCES students (id)
                )
            ''')
            conn.commit()

    def register_student(self, name, gesture_name, roll_number=None):
        """Registers a new student linked to a gesture name."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Check for roll number duplicate manually since schema wasn't UNIQUE on roll_number
                cursor.execute("SELECT id FROM students WHERE roll_number = ?", (roll_number,))
                if cursor.fetchone():
                    return False, f"Error: Roll number '{roll_number}' is already registered to someone else."

                cursor.execute(
                    "INSERT INTO students (name, gesture_name, roll_number) VALUES (?, ?, ?)",
                    (name, gesture_name, roll_number)
                )
                conn.commit()
                return True, f"Student {name} registered successfully."
        except sqlite3.IntegrityError:
            return False, f"Error: Gesture '{gesture_name}' is already assigned to a student."
        except Exception as e:
            return False, str(e)

    def mark_attendance(self, gesture_name):
        """Marks attendance for a student based on a detected gesture with memory debounce."""
        # 1. Very fast memory debounce (10 seconds minimum between same gesture queries)
        current_time = time.time()
        if gesture_name in self._cache:
            if current_time - self._cache[gesture_name] < 10:
                # Silently ignore to avoid spamming the database thread 30 times a second
                return None, "Memory debounce"
        
        self._cache[gesture_name] = current_time

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Find student by gesture
                cursor.execute("SELECT id, name FROM students WHERE gesture_name = ?", (gesture_name,))
                student = cursor.fetchone()
                
                if not student:
                    return None, f"No student found for gesture: {gesture_name}"
                
                student_id, student_name = student
                
                # Check for duplicate attendance within the last hour (to prevent multiple logs for one gesture)
                cursor.execute("""
                    SELECT id FROM attendance 
                    WHERE student_id = ? AND timestamp > datetime('now', '-1 hour')
                """, (student_id,))
                
                if cursor.fetchone():
                    return student_name, "Duplicate check avoided (recently marked)."

                # Log attendance
                cursor.execute(
                    "INSERT INTO attendance (student_id) VALUES (?)",
                    (student_id,)
                )
                conn.commit()
                return student_name, "Attendance marked successfully."
        except Exception as e:
            return None, str(e)

    def get_logs(self, limit=100):
        """Fetches the latest attendance logs."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT a.id, s.name, s.roll_number, a.timestamp, a.status 
                    FROM attendance a 
                    JOIN students s ON a.student_id = s.id 
                    ORDER BY a.timestamp DESC 
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching logs: {e}")
            return []

    def get_students(self):
        """Fetches all registered students."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, gesture_name, roll_number FROM students")
                return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching students: {e}")
            return []

if __name__ == "__main__":
    # Quick Test
    mgr = AttendanceManager()
    print("Database initialized.")

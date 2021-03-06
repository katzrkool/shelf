import sqlite3
import json
import random

from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

MAX_DAYS = 365

# This function has to be outside of the DB manager, or the scheduler jobstore
# won't function correctly
def remove_note(note_id, db_path):
    c = sqlite3.connect(db_path).cursor()
    c.execute('DELETE FROM shelf WHERE id = ?', (note_id,))
    c.connection.commit()


class DBManager:

    def __init__(self, db_path: str, word_path: str):

        with sqlite3.connect(db_path) as conn:
            # connecting to the database and creating the shelf table if
            # it doesn't exist
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS shelf 
            (id text PRIMARY KEY UNIQUE, data text, visits INTEGER DEFAULT 0, max_visits INTEGER DEFAULT 1, insert_date TIMESTAMP, expiry_date TIMESTAMP)''')

        with open(word_path, 'r') as f:
            self.words = json.load(f)

        # creates a task scheduler using the same db as taskstore
        self.scheduler = BackgroundScheduler(timezone='utc')
        self.scheduler.add_jobstore('sqlalchemy', url=f'sqlite:///{db_path}')
        self.scheduler.start()
        self.db_path = db_path

    def insert(self, id: str, data: str, ttl_days: int, max_visits: int, c: sqlite3.Cursor):
        # gets the current time (in utc)
        utc_date = datetime.utcnow()

        # calculates the day the note should expire
        ttl_days = ttl_days if ttl_days < MAX_DAYS else MAX_DAYS
        expiry_date = utc_date + timedelta(days=ttl_days)

        c.execute('INSERT INTO shelf (id, data, insert_date, expiry_date, max_visits) VALUES (?, ?, ?, ?, ?)',
                  (id, data, utc_date, expiry_date, max_visits))
        c.connection.commit()

        self.add_task(id, expiry_date)

        # Returns the expiry date and id which can be presented to the client
        # Also format expiry date in iso format for API, and for client side JS
        # to convert into local time zone
        return {'id': id, 'expiry_date': expiry_date.isoformat()+'Z',
                'max_visits': max_visits}

    def fetch_one(self, id: str, c: sqlite3.Cursor):
        c.execute('SELECT * FROM shelf WHERE id = ?', (id,))
        return c.fetchone()

    def generate_id(self, c: sqlite3.Cursor) -> str:
        # generates a word id from simple word list
        id = f'{random.choice(self.words)}-{random.choice(self.words)}'

        # checks if ID already exists. The chances of two identical IDs are
        # one in a million, but just to be safe, it checks.

        c.execute('SELECT EXISTS(SELECT 1 FROM shelf WHERE id=? LIMIT 1)', (id,))

        # if another ID happens to exist, just grab a new one
        if c.fetchone()[0] == 1:
            return self.generate_id(c)

        return id



    def update_visits(self, visitCount: int, note_id: str, c: sqlite3.Cursor):
        # increment visit count
        c.execute('UPDATE shelf SET visits = ? WHERE id = ?', (visitCount, note_id))
        c.connection.commit()

    def add_task(self, note_id, expiry_date):
        # adds a task in APScheduler to delete note after its expiry time/date
        # Sets misfire_grace_time to None, (infinite), so if a deletion job is
        # missed, it is fired whenever the program is turned back on
        self.scheduler.add_job(remove_note, trigger='date', run_date=expiry_date,
                               id=note_id, timezone='UTC',
                               misfire_grace_time=None, args=(note_id, self.db_path))

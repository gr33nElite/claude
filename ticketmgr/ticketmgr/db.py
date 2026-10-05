import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    pages INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    review INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    invoice_no TEXT NOT NULL UNIQUE,
    cust_no TEXT,
    bill_to TEXT,
    ship_to TEXT,
    cust_po TEXT,
    phone TEXT,
    sold_by TEXT,
    ticket_date TEXT,
    ticket_time TEXT,
    status TEXT NOT NULL DEFAULT 'New',
    priority TEXT NOT NULL DEFAULT 'Normal',
    assigned_to TEXT,
    follow_up TEXT,
    -- Set when a scan had something OCR couldn't read; cleared once checked.
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    qord INTEGER,
    qshp INTEGER,
    part TEXT NOT NULL,
    description TEXT,
    bin TEXT,
    jb TEXT,
    -- Set when someone edits the line by hand; later scans leave it alone.
    edited INTEGER NOT NULL DEFAULT 0
);

-- Every scanned page that belongs to a ticket, newest last.
CREATE TABLE IF NOT EXISTS ticket_pages (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    page_index INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    unreadable TEXT,
    imported_at TEXT NOT NULL
);

-- The ticket's worklog: notes people write plus system entries
-- (status changes, scan imports, field edits).
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'note',
    author TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

STATUSES = ["New", "Waiting on Parts", "Parts Ready", "On Hold", "Closed"]
PRIORITIES = ["Low", "Normal", "High", "Urgent"]
HEADER_FIELDS = ["cust_no", "bill_to", "ship_to", "cust_po", "phone", "sold_by",
                 "ticket_date", "ticket_time"]
FIELD_LABELS = {
    "invoice_no": "Invoice #", "cust_no": "Cust #", "bill_to": "Bill to",
    "ship_to": "Ship to", "cust_po": "Cust PO #", "phone": "Phone",
    "sold_by": "Sold by", "ticket_date": "Ticket date", "ticket_time": "Ticket time",
    "status": "Status", "priority": "Priority", "assigned_to": "Assigned to",
    "follow_up": "Follow up",
}


def now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def connect(path):
    # Several people can use the app at once; wait for a busy database
    # instead of failing straight away.
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn):
    # WAL lets readers keep working while someone else is writing.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.commit()


def add_entry(conn, ticket_id, body, kind="note", author=None):
    conn.execute(
        "INSERT INTO notes (ticket_id, kind, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, kind, author, body, now()),
    )

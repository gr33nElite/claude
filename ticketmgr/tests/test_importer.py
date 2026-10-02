import copy

import pypdfium2 as pdfium
import pytest
from PIL import Image

from ticketmgr import db
from ticketmgr.importer import Importer


def make_pdf(path, pages):
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(612, 792)
    pdf.save(str(path))


def header(invoice, page=1, **kw):
    h = {"invoice_no": invoice, "cust_no": "121186", "ticket_date": "10/01/2026",
         "ticket_time": "08:42:08", "page": page, "bill_to": "AMALIA MATEO\n6 LELAND CIR",
         "ship_to": None, "sold_by": "JESSE", "cust_po": None, "phone": None}
    h.update(kw)
    return h


def item(part, qord, qshp, desc="GASKET"):
    return {"qord": qord, "qshp": qshp, "part": part, "description": desc, "bin": "127", "jb": "1"}


class FakeReader:
    def __init__(self, pages):
        self.pages = pages

    def __call__(self, pdf_path, i):
        page = copy.deepcopy(self.pages[i])
        page.setdefault("unreadable", [])
        page["image"] = Image.new("L", (100, 130), 255)
        return page


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init(c)
    return c


def run(conn, tmp_path, pages, name="scan.pdf"):
    pdf = tmp_path / name
    make_pdf(pdf, len(pages))
    return Importer(conn, tmp_path / "data", reader=FakeReader(pages)).import_pdf(pdf)


def ticket(conn, invoice):
    return conn.execute("SELECT * FROM tickets WHERE invoice_no = ?", (invoice,)).fetchone()


def items(conn, t):
    return [(r["part"], r["qord"], r["qshp"]) for r in
            conn.execute("SELECT * FROM items WHERE ticket_id = ? ORDER BY position", (t["id"],))]


def test_import_creates_tickets(conn, tmp_path):
    r = run(conn, tmp_path, [
        {"header": header("RO1"), "items": [item("A-1", 1, 0), item("B-2", 2, 2)]},
        {"header": header("RO2"), "items": [item("C-3", 1, 1)]},
    ])
    assert len(r["created"]) == 2 and r["updated"] == []
    assert ticket(conn, "RO1")["status"] == "Waiting on Parts"
    assert ticket(conn, "RO2")["status"] == "Parts Ready"
    assert items(conn, ticket(conn, "RO1")) == [("A-1", 1, 0), ("B-2", 2, 2)]


def test_rescan_updates_without_duplicates_and_keeps_notes(conn, tmp_path):
    run(conn, tmp_path, [{"header": header("RO1"), "items": [item("A-1", 1, 0), item("B-2", 2, 2)]}])
    t = ticket(conn, "RO1")
    db.add_entry(conn, t["id"], "Called customer, parts ETA Friday", author="Jesse")
    conn.execute("UPDATE tickets SET assigned_to = 'Scott' WHERE id = ?", (t["id"],))
    conn.commit()

    r = run(conn, tmp_path, [{"header": header("RO1", cust_po="PO-9"),
                              "items": [item("A-1", 1, 1), item("B-2", 2, 2), item("D-4", 1, 0)]}],
            name="rescan.pdf")
    assert r["created"] == [] and r["updated"] == [t["id"]]
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
    t2 = ticket(conn, "RO1")
    assert t2["assigned_to"] == "Scott"
    assert t2["cust_po"] == "PO-9"  # blank field filled in
    assert items(conn, t2) == [("A-1", 1, 1), ("B-2", 2, 2), ("D-4", 1, 0)]
    log = [n["body"] for n in conn.execute("SELECT body FROM notes WHERE ticket_id = ?", (t["id"],))]
    assert "Called customer, parts ETA Friday" in log
    assert any("A-1: shipped 0 → 1 of 1" in b for b in log)
    assert any("New line from scan: D-4" in b for b in log)
    assert conn.execute("SELECT COUNT(*) FROM ticket_pages WHERE ticket_id = ?", (t["id"],)).fetchone()[0] == 2


def test_rescan_marks_parts_ready_and_respects_hand_edits(conn, tmp_path):
    run(conn, tmp_path, [{"header": header("RO1"), "items": [item("A-1", 1, 0), item("B-2", 2, 0)]}])
    t = ticket(conn, "RO1")
    conn.execute("UPDATE items SET qshp = 2, edited = 1 WHERE part = 'B-2'")
    conn.commit()
    # Second scan misreads B-2's shipped qty; the hand edit wins.
    run(conn, tmp_path, [{"header": header("RO1"), "items": [item("A-1", 1, 1), item("B-2", 2, 0)]}],
        name="rescan.pdf")
    assert items(conn, t) == [("A-1", 1, 1), ("B-2", 2, 2)]
    assert ticket(conn, "RO1")["status"] == "Parts Ready"


def test_continuation_page_and_unreadable_invoice(conn, tmp_path):
    r = run(conn, tmp_path, [
        {"header": header("RO1"), "items": [item("A-1", 1, 0)]},
        {"header": header(None, page=2), "items": [item("B-2", 1, 0)]},
        {"header": header(None), "items": [item("C-3", 1, 0)], "unreadable": ["1 1 ?? SEAL 138 1"]},
    ])
    assert len(r["created"]) == 2
    assert items(conn, ticket(conn, "RO1")) == [("A-1", 1, 0), ("B-2", 1, 0)]
    unread = conn.execute("SELECT * FROM tickets WHERE invoice_no LIKE 'UNREAD-%'").fetchone()
    assert unread["needs_review"] == 1
    assert unread["id"] in r["review"]


def test_repeated_part_numbers_match_in_order(conn, tmp_path):
    lines = [item("FL-910S", 1, 1), item("FL-910S", 1, 0)]
    run(conn, tmp_path, [{"header": header("RO1"), "items": lines}])
    lines[1]["qshp"] = 1
    run(conn, tmp_path, [{"header": header("RO1"), "items": lines}], name="again.pdf")
    assert items(conn, ticket(conn, "RO1")) == [("FL-910S", 1, 1), ("FL-910S", 1, 1)]

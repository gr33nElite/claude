import os
import tempfile
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

from . import db
from .extract import TESSERACT_MISSING, find_tesseract
from .importer import Importer

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def create_app(data_dir=None, reader=None):
    app = Flask(__name__)
    data_dir = Path(data_dir or os.environ.get("TICKETMGR_DATA") or DEFAULT_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(
        DATA_DIR=data_dir,
        DB_PATH=data_dir / "tickets.db",
        SECRET_KEY=os.environ.get("TICKETMGR_SECRET", "ticketmgr-local"),
        MAX_CONTENT_LENGTH=500 * 1024 * 1024,
        READER=reader,
    )
    with db.connect(app.config["DB_PATH"]) as conn:
        db.init(conn)

    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def globals_():
        return {"STATUSES": db.STATUSES, "PRIORITIES": db.PRIORITIES}

    def get_ticket(ticket_id):
        row = get_db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    def author():
        return request.cookies.get("author", "")

    @app.route("/")
    def ticket_list():
        status = request.args.get("status", "open")
        q = request.args.get("q", "").strip()
        sql = """
            SELECT t.*,
                   (SELECT COUNT(*) FROM items i WHERE i.ticket_id = t.id) AS lines,
                   (SELECT COUNT(*) FROM items i WHERE i.ticket_id = t.id
                      AND (i.qshp IS NULL OR i.qord IS NULL OR i.qshp < i.qord)) AS short,
                   (SELECT body FROM notes n WHERE n.ticket_id = t.id AND n.kind = 'note'
                      ORDER BY n.id DESC LIMIT 1) AS last_note
            FROM tickets t WHERE 1 = 1"""
        args = []
        if status == "open":
            sql += " AND t.status != 'Closed'"
        elif status == "review":
            sql += " AND t.needs_review = 1"
        elif status != "all":
            sql += " AND t.status = ?"
            args.append(status)
        if q:
            like = f"%{q}%"
            sql += """ AND (t.invoice_no LIKE ? OR t.bill_to LIKE ? OR t.ship_to LIKE ?
                       OR t.cust_no LIKE ? OR t.cust_po LIKE ? OR t.assigned_to LIKE ?
                       OR EXISTS (SELECT 1 FROM items i WHERE i.ticket_id = t.id
                                  AND (i.part LIKE ? OR i.description LIKE ?))
                       OR EXISTS (SELECT 1 FROM notes n WHERE n.ticket_id = t.id AND n.body LIKE ?))"""
            args += [like] * 9
        sql += """ ORDER BY CASE t.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1
                   WHEN 'Normal' THEN 2 ELSE 3 END,
                   substr(t.ticket_date, 7, 4) || substr(t.ticket_date, 1, 2) || substr(t.ticket_date, 4, 2) DESC,
                   t.id DESC"""
        tickets = get_db().execute(sql, args).fetchall()
        counts = dict(get_db().execute("SELECT status, COUNT(*) FROM tickets GROUP BY status").fetchall())
        to_check = get_db().execute("SELECT COUNT(*) FROM tickets WHERE needs_review = 1").fetchone()[0]
        return render_template("list.html", tickets=tickets, status=status, q=q, counts=counts,
                               to_check=to_check)

    @app.route("/import", methods=["GET", "POST"])
    def import_scans():
        if request.method == "GET":
            scans = get_db().execute("SELECT * FROM scans ORDER BY id DESC LIMIT 50").fetchall()
            missing = None if app.config["READER"] or find_tesseract() else TESSERACT_MISSING
            return render_template("import.html", scans=scans, missing=missing)
        files = [f for f in request.files.getlist("pdfs") if f and f.filename]
        if not files:
            flash("Choose one or more PDF files first.")
            return redirect(url_for("import_scans"))
        if not app.config["READER"] and not find_tesseract():
            flash(TESSERACT_MISSING)
            return redirect(url_for("import_scans"))
        kwargs = {"reader": app.config["READER"]} if app.config["READER"] else {}
        importer = Importer(get_db(), app.config["DATA_DIR"], **kwargs)
        results = []
        for f in files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                f.save(tmp.name)
            try:
                results.append((f.filename, importer.import_pdf(tmp.name, f.filename), None))
            except Exception as exc:  # a bad file shouldn't stop the others
                get_db().rollback()
                results.append((f.filename, None, str(exc)))
            finally:
                os.unlink(tmp.name)
        ids = {i for _, r, _ in results if r for i in r["created"] + r["updated"]}
        tickets = {}
        if ids:
            marks = ",".join("?" * len(ids))
            for row in get_db().execute(f"SELECT * FROM tickets WHERE id IN ({marks})", list(ids)):
                tickets[row["id"]] = row
        return render_template("import_result.html", results=results, tickets=tickets)

    @app.route("/tickets/<int:ticket_id>")
    def ticket_detail(ticket_id):
        conn = get_db()
        ticket = get_ticket(ticket_id)
        items = conn.execute("SELECT * FROM items WHERE ticket_id = ? ORDER BY position", (ticket_id,)).fetchall()
        notes = conn.execute("SELECT * FROM notes WHERE ticket_id = ? ORDER BY id DESC", (ticket_id,)).fetchall()
        pages = conn.execute(
            "SELECT p.*, s.filename FROM ticket_pages p JOIN scans s ON s.id = p.scan_id"
            " WHERE p.ticket_id = ? ORDER BY p.id DESC", (ticket_id,)).fetchall()
        return render_template("ticket.html", t=ticket, items=items, notes=notes, pages=pages,
                               author=author())

    @app.post("/tickets/<int:ticket_id>/update")
    def ticket_update(ticket_id):
        conn = get_db()
        t = get_ticket(ticket_id)
        fields = ["invoice_no", "status", "priority", "assigned_to", "follow_up"] + db.HEADER_FIELDS
        changes = []
        for f in fields:
            if f not in request.form:
                continue
            new = request.form[f].strip() or None
            if f == "invoice_no":
                new = (new or "").upper()
                if not new:
                    continue
                clash = conn.execute("SELECT id FROM tickets WHERE invoice_no = ? AND id != ?",
                                     (new, ticket_id)).fetchone()
                if clash:
                    flash(f"Invoice {new} is already another ticket; not changed.")
                    continue
            if new != t[f]:
                conn.execute(f"UPDATE tickets SET {f} = ? WHERE id = ?", (new, ticket_id))
                changes.append(f"{db.FIELD_LABELS[f]}: {t[f] or '—'} → {new or '—'}")
        if changes:
            conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (db.now(), ticket_id))
            db.add_entry(conn, ticket_id, "\n".join(changes), kind="change", author=author() or None)
            conn.commit()
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    @app.post("/tickets/<int:ticket_id>/checked")
    def mark_checked(ticket_id):
        get_ticket(ticket_id)
        conn = get_db()
        conn.execute("UPDATE tickets SET needs_review = 0 WHERE id = ?", (ticket_id,))
        db.add_entry(conn, ticket_id, "Checked against the scan.", kind="change", author=author() or None)
        conn.commit()
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    @app.post("/tickets/<int:ticket_id>/notes")
    def add_note(ticket_id):
        get_ticket(ticket_id)
        body = request.form.get("body", "").strip()
        name = request.form.get("author", "").strip()
        resp = redirect(url_for("ticket_detail", ticket_id=ticket_id) + "#worklog")
        if body:
            conn = get_db()
            db.add_entry(conn, ticket_id, body, author=name or None)
            conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (db.now(), ticket_id))
            conn.commit()
        if name:
            resp.set_cookie("author", name, max_age=10 * 365 * 24 * 3600)
        return resp

    def _item_values(form):
        def num(v):
            v = (v or "").strip()
            return int(v) if v.isdigit() else None
        return {
            "qord": num(form.get("qord")), "qshp": num(form.get("qshp")),
            "part": (form.get("part") or "").strip().upper(),
            "description": (form.get("description") or "").strip(),
            "bin": (form.get("bin") or "").strip().upper(),
            "jb": (form.get("jb") or "").strip(),
        }

    def _blank(x):
        return None if x in ("", None) else x

    @app.post("/tickets/<int:ticket_id>/items")
    def add_item(ticket_id):
        get_ticket(ticket_id)
        conn = get_db()
        v = _item_values(request.form)
        if v["part"]:
            pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM items WHERE ticket_id = ?",
                               (ticket_id,)).fetchone()[0]
            conn.execute("INSERT INTO items (ticket_id, position, qord, qshp, part, description, bin, jb, edited)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)", (ticket_id, pos, *v.values()))
            db.add_entry(conn, ticket_id, f"Line added: {v['part']} {v['description']}".strip(),
                         kind="change", author=author() or None)
            conn.commit()
        return redirect(url_for("ticket_detail", ticket_id=ticket_id) + "#items")

    @app.post("/tickets/<int:ticket_id>/items/<int:item_id>")
    def edit_item(ticket_id, item_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM items WHERE id = ? AND ticket_id = ?", (item_id, ticket_id)).fetchone()
        if row is None:
            abort(404)
        if request.form.get("delete"):
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            db.add_entry(conn, ticket_id, f"Line removed: {row['part']}", kind="change", author=author() or None)
        else:
            v = _item_values(request.form)
            if not v["part"]:
                v["part"] = row["part"]
            changed = [f"{k}: {row[k] if row[k] is not None else '—'} → {v[k] if v[k] is not None else '—'}"
                       for k in v if _blank(v[k]) != _blank(row[k])]
            if changed:
                conn.execute("UPDATE items SET qord=?, qshp=?, part=?, description=?, bin=?, jb=?, edited=1"
                             " WHERE id = ?", (*v.values(), item_id))
                db.add_entry(conn, ticket_id, f"Line {row['part']} edited: " + ", ".join(changed),
                             kind="change", author=author() or None)
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (db.now(), ticket_id))
        conn.commit()
        return redirect(url_for("ticket_detail", ticket_id=ticket_id) + "#items")

    @app.post("/tickets/<int:ticket_id>/delete")
    def delete_ticket(ticket_id):
        get_ticket(ticket_id)
        conn = get_db()
        conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        conn.commit()
        flash("Ticket deleted.")
        return redirect(url_for("ticket_list"))

    @app.route("/pages/<int:page_id>.png")
    def page_image(page_id):
        row = get_db().execute("SELECT image_path FROM ticket_pages WHERE id = ?", (page_id,)).fetchone()
        if row is None or not Path(row["image_path"]).exists():
            abort(404)
        return send_file(row["image_path"], mimetype="image/png")

    @app.route("/scans/<int:scan_id>.pdf")
    def scan_pdf(scan_id):
        row = get_db().execute("SELECT stored_path FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if row is None or not Path(row["stored_path"]).exists():
            abort(404)
        return send_file(row["stored_path"], mimetype="application/pdf")

    @app.template_filter("first_line")
    def first_line(text):
        return (text or "").splitlines()[0] if text else ""

    return app

"""Import a PDF of scanned pick tickets into the ticket database.

Each page is matched to a ticket by invoice number. A new invoice creates a
ticket; an invoice already on file is updated in place (shipped quantities,
new lines, a fresh copy of the scan) while its notes, status and hand edits
are kept.
"""

import shutil
from pathlib import Path

from . import db, extract, parse

PAGE_IMAGE_WIDTH = 1275  # 150 dpi for a letter page; plenty to read handwriting


def read_page(pdf_path, page_index):
    header_lines, table_lines, image = extract.ocr_page(pdf_path, page_index)
    width = image.size[0]
    header = parse.parse_header(header_lines, width)
    items, unreadable = parse.parse_items(table_lines, header_lines, width)
    return {"header": header, "items": items, "unreadable": unreadable, "image": image}


def _save_image(image, path):
    w, h = image.size
    small = image.resize((PAGE_IMAGE_WIDTH, round(h * PAGE_IMAGE_WIDTH / w)))
    small.save(path, optimize=True)


def _short(item):
    return f'{item["part"]} {item["description"] or ""}'.strip()


def _qty(n):
    return "?" if n is None else str(n)


def _all_shipped(conn, ticket_id):
    rows = conn.execute("SELECT qord, qshp FROM items WHERE ticket_id = ?", (ticket_id,)).fetchall()
    return bool(rows) and all(r["qord"] is not None and r["qshp"] is not None
                              and r["qshp"] >= r["qord"] for r in rows)


class Importer:
    def __init__(self, conn, data_dir, reader=read_page):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.reader = reader
        (self.data_dir / "scans").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "pages").mkdir(parents=True, exist_ok=True)

    def import_pdf(self, src_path, filename=None, progress=None):
        conn = self.conn
        filename = filename or Path(src_path).name
        cur = conn.execute(
            "INSERT INTO scans (filename, stored_path, imported_at) VALUES (?, '', ?)",
            (filename, db.now()),
        )
        scan_id = cur.lastrowid
        stored = self.data_dir / "scans" / f"{scan_id:05d}_{Path(filename).name}"
        shutil.copyfile(src_path, stored)
        conn.execute("UPDATE scans SET stored_path = ? WHERE id = ?", (str(stored), scan_id))
        # Commit page by page: OCR is slow, and on a shared install other
        # people need to save notes while a stack is being imported.
        conn.commit()

        pages = extract.page_count(stored)
        created, updated, review = [], [], []
        seen = {}          # ticket_id -> {part: occurrences seen in this scan}
        prev_ticket = None
        for i in range(pages):
            if progress:
                progress(i, pages)
            page = self.reader(stored, i)
            header = page["header"]
            image_path = self.data_dir / "pages" / f"scan{scan_id:05d}_p{i + 1:03d}.png"
            _save_image(page["image"], image_path)

            invoice = header["invoice_no"]
            if not invoice and header["page"] > 1 and prev_ticket:
                # Continuation page of the ticket before it.
                invoice, ticket_id, is_new = "", prev_ticket, False
            else:
                invoice = invoice or f"UNREAD-{scan_id}-{i + 1}"
                ticket_id, is_new = self._upsert_ticket(invoice, header, scan_id, i)
            prev_ticket = ticket_id

            counts = seen.setdefault(ticket_id, {})
            self._merge_items(ticket_id, page["items"], counts, log=not is_new and ticket_id not in created)

            conn.execute(
                "INSERT INTO ticket_pages (ticket_id, scan_id, page_index, image_path, unreadable, imported_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ticket_id, scan_id, i, str(image_path), "\n".join(page["unreadable"]) or None, db.now()),
            )
            missing_qty = [it for it in page["items"] if it["qord"] is None or it["qshp"] is None]
            needs_review = invoice.startswith("UNREAD-") or bool(page["unreadable"] or missing_qty)
            if is_new:
                created.append(ticket_id)
                status = "Parts Ready" if _all_shipped(conn, ticket_id) else "Waiting on Parts"
                conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
                db.add_entry(conn, ticket_id, f"Created from scan {filename} (page {i + 1}).", kind="system")
            elif ticket_id not in created and ticket_id not in updated:
                updated.append(ticket_id)
                db.add_entry(conn, ticket_id, f"Updated from scan {filename} (page {i + 1}).", kind="system")
                self._maybe_parts_ready(ticket_id)
            if needs_review:
                review.append(ticket_id)
                conn.execute("UPDATE tickets SET needs_review = 1 WHERE id = ?", (ticket_id,))
                problems = []
                if invoice.startswith("UNREAD-"):
                    problems.append("The invoice number could not be read; fix it under Ticket details.")
                if missing_qty:
                    problems.append("Quantity unreadable for: " + ", ".join(it["part"] for it in missing_qty))
                if page["unreadable"]:
                    problems.append(f"{len(page['unreadable'])} line(s) could not be read; "
                                    "add them from the scan:\n" + "\n".join(page["unreadable"]))
                db.add_entry(conn, ticket_id, f"Check page {i + 1} against the scan. " + "\n".join(problems),
                             kind="system")
            conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (db.now(), ticket_id))
            conn.commit()

        conn.execute(
            "UPDATE scans SET pages = ?, created = ?, updated = ?, review = ? WHERE id = ?",
            (pages, len(created), len(updated), len(set(review)), scan_id),
        )
        conn.commit()
        return {"scan_id": scan_id, "pages": pages, "created": created,
                "updated": updated, "review": sorted(set(review))}

    def _upsert_ticket(self, invoice, header, scan_id, page_index):
        conn = self.conn
        row = conn.execute("SELECT * FROM tickets WHERE invoice_no = ?", (invoice,)).fetchone()
        if row is None:
            fields = {f: header.get(f) for f in db.HEADER_FIELDS}
            cols = ", ".join(fields)
            marks = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO tickets (invoice_no, {cols}, created_at, updated_at) VALUES (?, {marks}, ?, ?)",
                (invoice, *fields.values(), db.now(), db.now()),
            )
            return cur.lastrowid, True
        # Header text is printed once and doesn't change, so a rescan only
        # fills in fields that are still blank (OCR noise never overwrites).
        for f in db.HEADER_FIELDS:
            if header.get(f) and not row[f]:
                conn.execute(f"UPDATE tickets SET {f} = ? WHERE id = ?", (header[f], row["id"]))
        return row["id"], False

    def _merge_items(self, ticket_id, items, counts, log):
        conn = self.conn
        existing = conn.execute(
            "SELECT * FROM items WHERE ticket_id = ? ORDER BY position", (ticket_id,)).fetchall()
        by_key, occ = {}, {}
        for row in existing:
            n = occ[row["part"]] = occ.get(row["part"], 0) + 1
            by_key[(row["part"], n)] = row
        position = max((r["position"] for r in existing), default=0)

        for item in items:
            n = counts[item["part"]] = counts.get(item["part"], 0) + 1
            row = by_key.get((item["part"], n))
            if row is None:
                position += 1
                conn.execute(
                    "INSERT INTO items (ticket_id, position, qord, qshp, part, description, bin, jb)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ticket_id, position, item["qord"], item["qshp"], item["part"],
                     item["description"], item["bin"], item["jb"]),
                )
                if log:
                    db.add_entry(conn, ticket_id, f"New line from scan: {_short(item)} "
                                 f"(ordered {_qty(item['qord'])}, shipped {_qty(item['qshp'])}).",
                                 kind="system")
                continue
            if row["edited"]:
                continue
            changes = {k: item[k] for k in ("qord", "qshp", "description", "bin", "jb")
                       if item[k] not in (None, "") and item[k] != row[k]}
            if not changes:
                continue
            sets = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(f"UPDATE items SET {sets} WHERE id = ?", (*changes.values(), row["id"]))
            if log and "qshp" in changes:
                db.add_entry(conn, ticket_id,
                             f"{row['part']}: shipped {_qty(row['qshp'])} → {_qty(item['qshp'])}"
                             f" of {_qty(changes.get('qord', row['qord']))}.", kind="system")

    def _maybe_parts_ready(self, ticket_id):
        row = self.conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row["status"] == "Waiting on Parts" and _all_shipped(self.conn, ticket_id):
            self.conn.execute("UPDATE tickets SET status = 'Parts Ready' WHERE id = ?", (ticket_id,))
            db.add_entry(self.conn, ticket_id, "Status: Waiting on Parts → Parts Ready (all lines shipped).",
                         kind="system")

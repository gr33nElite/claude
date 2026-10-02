"""Turn OCR output of one "PICKING TICKET" page into structured fields.

Layout (fixed-width print):

    10/01/2026            PICKING TICKET            NET518
    08:42:08                                         PAGE  1
    INVOICE#  CUST#  BILL TO          SHIP TO        SOLD BY
    RO478342  121186 AMALIA MATEO                    JESSE
                     6 LELAND CIR
    CUST PO#         GREENVILLE,SC 29617
    QORD QSHP PART# / DESCRIPTION     BIN   JB PF
       1    1 PZ1Z-5A215-B  CLAMP     114   1
"""

import re

DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
TIME = re.compile(r"\b(\d{1,2}:\d{2}:\d{2})\b")
PHONE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")
INVOICE = re.compile(r"^([A-Z0]{2})([0-9OIlS]{5,7})(-\d{1,2})?$", re.IGNORECASE)

PART = re.compile(r"^(?=.*\d)-?[A-Z0-9][A-Z0-9-]{2,}[A-Z0-9]$")
QTY_FIX = str.maketrans("OoQDIilL|", "000011111")

# Item table columns as fractions of page width, used when the
# "QORD QSHP PART# / DESCRIPTION BIN JB PF" heading can't be read.
DEFAULT_ITEM_COLUMNS = {"qshp": 0.068, "part": 0.105, "bin": 0.355,
                        "jb": 0.405, "pf": 0.428}

def normalize_invoice(token):
    """Fix the usual OCR mix-ups in invoice numbers like RO478342 / AP141248-1."""
    m = INVOICE.match(token.strip(".,:;~-_"))
    if not m:
        return None
    prefix = m.group(1).upper().replace("0", "O")
    digits = m.group(2).upper().translate(str.maketrans("OILS", "0115"))
    return prefix + digits + (m.group(3) or "")


def _texts(words):
    return [t for _, _, t in words]


def _line_text(words):
    return " ".join(_texts(words))


def _find_line(lines, *labels):
    for i, words in enumerate(lines):
        upper = _line_text(words).upper()
        if all(label in upper for label in labels):
            return i
    return None


def _columns(header_words, width_hint):
    """x boundaries of the CUST#, BILL TO, SHIP TO and SOLD BY columns."""
    xs = {}
    for x, _, t in header_words:
        t = t.upper()
        if t.startswith("CUST") and "cust" not in xs:
            xs["cust"] = x
        elif t == "BILL":
            xs["bill"] = x
        elif t == "SHIP":
            xs["ship"] = x
        elif t == "SOLD":
            xs["sold"] = x
    # Fallbacks match the print layout when a heading is unreadable.
    defaults = {"cust": 0.12, "bill": 0.18, "ship": 0.36, "sold": 0.53}
    return {k: xs.get(k, defaults[k] * width_hint) - 10 for k in defaults}


def _column_of(x, cols):
    if x < cols["cust"]:
        return "invoice"
    if x < cols["bill"]:
        return "cust"
    if x < cols["ship"]:
        return "bill"
    if x < cols["sold"]:
        return "ship"
    return "sold"


def parse_header(lines, page_width=2550):
    """Parse the header from OCR lines of positioned words."""
    result = {
        "invoice_no": None, "cust_no": None, "ticket_date": None, "ticket_time": None,
        "page": 1, "bill_to": None, "ship_to": None, "sold_by": None,
        "cust_po": None, "phone": None,
    }
    all_text = "\n".join(_line_text(w) for w in lines)
    if m := DATE.search(all_text):
        result["ticket_date"] = m.group(1)
    if m := TIME.search(all_text):
        result["ticket_time"] = m.group(1)
    if m := re.search(r"PAGE\s+(\d+)", all_text, re.IGNORECASE):
        result["page"] = int(m.group(1))
    if m := PHONE.search(all_text):
        result["phone"] = m.group(1)

    head = _find_line(lines, "INVOICE")
    if head is None:
        head = _find_line(lines, "BILL", "TO")
    if head is None:
        return result
    cols = _columns(lines[head], page_width)

    stop = _find_line(lines, "QORD")
    body = lines[head + 1: stop if stop is not None else len(lines)]
    cells = {"invoice": [], "cust": [], "bill": [], "ship": [], "sold": []}
    po_line = None
    for n, words in enumerate(body):
        row = {}
        is_po_label = "PO" in _line_text(words).upper() and _line_text(words).upper().lstrip("~ ").startswith(("CUST", "CCUST"))
        if is_po_label:
            po_line = n
        for x, _, t in words:
            if PHONE.fullmatch(t):
                continue
            row.setdefault(_column_of(x, cols), []).append(t)
        if is_po_label:
            # Label words sit in the invoice/cust columns; anything after them is the PO.
            left = row.pop("invoice", []) + row.pop("cust", [])
            rest = [t for t in left if not re.match(r"^C*CUST$|^PO.?$|^PO#?H?$", t, re.IGNORECASE)]
            if rest:
                result["cust_po"] = " ".join(rest)
        for col, toks in row.items():
            cells[col].append(" ".join(toks))

    for token in " ".join(cells["invoice"][:1]).split():
        if inv := normalize_invoice(token):
            result["invoice_no"] = inv
            break
    if cells["cust"]:
        result["cust_no"] = re.sub(r"[^0-9]", "", cells["cust"][0]) or None
    if po_line is not None and not result["cust_po"] and len(cells["invoice"]) > 1:
        # PO number printed on the line under the "CUST PO#" label.
        result["cust_po"] = cells["invoice"][-1].strip()
    if cells["bill"]:
        result["bill_to"] = "\n".join(cells["bill"])
    if cells["ship"]:
        result["ship_to"] = "\n".join(cells["ship"])
    if cells["sold"]:
        result["sold_by"] = cells["sold"][0]
    return result


def item_columns(header_lines, page_width=2550):
    """x boundaries of the item table columns, from its heading if readable."""
    cols = {k: v * page_width for k, v in DEFAULT_ITEM_COLUMNS.items()}
    i = _find_line(header_lines, "QORD")
    for x, _, t in header_lines[i] if i is not None else []:
        t = t.upper()
        if t.startswith("QSHP"):
            cols["qshp"] = x
        elif t.startswith("PART"):
            cols["part"] = x
        elif t == "BIN":
            cols["bin"] = x
        elif t == "JB":
            cols["jb"] = x
        elif t == "PF":
            cols["pf"] = x
    # Descriptions are printed a little over halfway from PART# to BIN.
    cols["desc"] = cols["part"] + 0.55 * (cols["bin"] - cols["part"])
    return cols


def _qty(text):
    text = text.translate(QTY_FIX)
    return int(text) if text.isdigit() else None


def _split_row(words, cols, slack):
    cells = {k: [] for k in ("qord", "qshp", "part", "desc", "bin", "jb")}
    left = []
    for x, _, t in words:
        if x < cols["qshp"] - slack:
            cells["qord"].append(t)
        elif x < cols["desc"]:
            left.append(t)
        elif x < cols["bin"] - slack:
            cells["desc"].append(t)
        elif x < cols["jb"] - slack:
            cells["bin"].append(t)
        elif x < cols["pf"] + 3 * slack:
            cells["jb"].append(t)
    # Shipped qty and part number sit close together, so split them by
    # shape rather than position: a short number first, then the part.
    if left:
        first = left[0]
        glued = re.match(r"^([0-9OoQIil|]{1,3})[_~.:,]+(.+)$", first)  # pen underline
        if re.fullmatch(r"[0-9OoQIil|]{1,3}[_~.:,})\]|]*", first) or (len(first) <= 3 and len(left) > 1):
            # A pen mark over the qty still leaves the part number readable.
            cells["qshp"].append(first)
            left = left[1:]
        elif glued:
            cells["qshp"].append(glued.group(1))
            left = [glued.group(2)] + left[1:]
        cells["part"] = left
    return cells


def parse_items(table_lines, header_lines=(), page_width=2550):
    """Return (items, unreadable_lines) from positioned OCR words of the item table."""
    cols = item_columns(header_lines, page_width)
    slack = int(0.006 * page_width)
    items, unreadable = [], []
    for words in table_lines:
        text = _line_text(words)
        if set(text) <= set("-—_ ."):
            continue
        cells = _split_row(words, cols, slack)
        part = _part_number(cells["part"])
        qord = _qty("".join(cells["qord"]).strip("_~.:,|-"))
        qshp = _qty("".join(cells["qshp"]).strip("_~.:,|-})]"))
        if part and (qord is not None or qshp is not None):
            items.append({
                "qord": qord,
                "qshp": qshp,
                "part": part,
                "description": " ".join(cells["desc"]).strip(" _~|"),
                "bin": " ".join(cells["bin"]).strip(" _~|=").upper(),
                "jb": re.sub(r"\D", "", "".join(cells["jb"]).translate(QTY_FIX)),
            })
        elif (re.search(r"[A-Z0-9]{2,}-[A-Z0-9]", " ".join(cells["part"]), re.IGNORECASE)
              or (any(re.fullmatch(r"[A-Z0-9]{2,6}", b) for b in cells["bin"]) and cells["part"])):
            # Looks like a printed row but couldn't be read cleanly.
            unreadable.append(text)
    return items, unreadable


def _part_number(tokens):
    """The printed part number is the first token in the PART# column;
    anything after it is usually handwriting."""
    if not tokens:
        return None
    part = tokens[0].strip("_~.:,|'\"").upper()
    part = re.sub(r"^-+", "-", part.replace("—", "-"))
    return part if PART.match(part) else None

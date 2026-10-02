from ticketmgr.parse import normalize_invoice, parse_header, parse_items

# Positioned OCR words (x, y, text) at 300 dpi, laid out like a real ticket.
HEADER = [
    [(91, 252, "10/01/2026"), (668, 253, "PICKING"), (810, 253, "TICKET"), (1351, 253, "NET518")],
    [(91, 304, "09:14:33"), (1388, 302, "PAGE"), (1515, 302, "1")],
    [(91, 403, "INVOICE#"), (306, 403, "CUST#"), (468, 404, "BILL"), (558, 403, "TO"),
     (919, 403, "SHIP"), (1008, 403, "TO"), (1368, 403, "SOLD"), (1459, 403, "BY")],
    [(89, 454, "R0478105"), (307, 454, "3359"), (468, 454, "SC"), (540, 450, "DOT/PICKENS"),
     (1368, 453, "JESSE")],
    [(468, 504, "975"), (539, 504, "BREAZEALE"), (719, 504, "RD")],
    [(88, 556, "CUST"), (179, 554, "PO#"), (468, 556, "LIBERTY,SC"), (666, 556, "29657")],
    [(88, 606, "4601075083")],
    [(324, 655, "864-859-5869")],
    [(87, 753, "QORD"), (177, 753, "QSHP"), (269, 752, "PART#"), (378, 750, "/"),
     (412, 754, "DESCRIPTION"), (917, 754, "BIN"), (1044, 754, "JB"), (1098, 754, "PF")],
]


def test_header_fields():
    h = parse_header(HEADER)
    assert h["invoice_no"] == "RO478105"  # OCR zero fixed to letter O
    assert h["cust_no"] == "3359"
    assert h["ticket_date"] == "10/01/2026"
    assert h["ticket_time"] == "09:14:33"
    assert h["page"] == 1
    assert h["bill_to"] == "SC DOT/PICKENS\n975 BREAZEALE RD\nLIBERTY,SC 29657"
    assert h["sold_by"] == "JESSE"
    assert h["cust_po"] == "4601075083"
    assert h["phone"] == "864-859-5869"
    assert h["ship_to"] is None


def test_normalize_invoice():
    assert normalize_invoice("R0477112") == "RO477112"
    assert normalize_invoice("RO476859-1") == "RO476859-1"
    assert normalize_invoice("AP14I248") == "AP141248"
    assert normalize_invoice("INVOICE#") is None


def test_items_by_column():
    table = [
        [(140, 870, "1"), (215, 870, "1"), (270, 870, "PZ1Z-5A215-B"), (645, 870, "CLAMP"),
         (760, 870, "-"), (790, 870, "EXHAUS"), (918, 870, "114"), (1060, 870, "1")],
        # Pen underline glued to the shipped quantity.
        [(140, 920, "2"), (200, 920, "2_FT4Z-6N652-D"), (645, 920, "GASKET"), (918, 920, "127"),
         (1060, 920, "1")],
        # Handwriting after the JB column is ignored; PART column keeps only the first token.
        [(140, 970, "4"), (215, 970, "0"), (270, 970, "--W719190-S901"), (520, 970, "FMP"),
         (645, 970, "STUD"), (918, 970, "197"), (1060, 970, "1"), (1500, 970, "Cross")],
        # Pure handwriting line.
        [(300, 1100, "10/2"), (420, 1100, "719190"), (560, 1100, "is"), (640, 1100, "x-ship")],
        # Printed row with a struck-through part number.
        [(140, 1150, "1"), (215, 1150, "1"), (270, 1150, "P%#&"), (645, 1150, "SEAL"),
         (918, 1150, "138"), (1060, 1150, "1")],
    ]
    items, unreadable = parse_items(table, HEADER)
    assert [(i["qord"], i["qshp"], i["part"]) for i in items] == [
        (1, 1, "PZ1Z-5A215-B"), (2, 2, "FT4Z-6N652-D"), (4, 0, "-W719190-S901")]
    assert items[0]["description"] == "CLAMP - EXHAUS"
    assert items[0]["bin"] == "114"
    assert items[2]["description"] == "STUD"
    assert unreadable == ["1 1 P%#& SEAL 138 1"]

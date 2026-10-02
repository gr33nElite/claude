"""Build a fake scanned pick ticket (image-only PDF) for tests and demos.

    python tests/sample.py out.pdf
"""

import io
import sys

import pypdfium2 as pdfium

TICKETS = [
    {
        "date": "10/01/2026", "time": "08:42:08", "invoice": "RO478342", "cust": "121186",
        "bill": ["AMALIA MIGUEL MATEO", "6 LELAND CIR", "GREENVILLE,SC 29617"],
        "items": [(1, 1, "PZ1Z-5A215-B", "CLAMP - EXHAUS", "114", "1"),
                  (2, 2, "FT4Z-6N652-D", "GASKET", "127", "1"),
                  (4, 0, "-W719190-S901", "STUD", "197", "1")],
    },
    {
        "date": "09/30/2026", "time": "11:38:37", "invoice": "RO478327", "cust": "72289",
        "bill": ["WILLIAM HARKINS", "405 HUNTINGTON ROAD", "EASLEY,SC 29640"],
        "items": [(1, 0, "F2GZ-9J279-B", "PIPE - FUEL", "NS", "1")],
    },
]


def build(path, tickets=TICKETS):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for t in tickets:
        c.setFont("Courier", 7.5)
        y = 792 - 64

        def line(x, text):
            c.drawString(x, y, text)

        line(22, t["date"]); line(160, "PICKING TICKET"); line(325, "NET518"); y -= 12
        line(22, t["time"]); line(333, "PAGE   1"); y -= 24
        for x, s in [(22, "INVOICE#"), (73, "CUST#"), (112, "BILL TO"), (220, "SHIP TO"), (328, "SOLD BY")]:
            line(x, s)
        y -= 12
        line(22, t["invoice"]); line(73, t["cust"]); line(112, t["bill"][0]); line(328, "JESSE"); y -= 12
        line(112, t["bill"][1]); y -= 12
        line(22, "CUST PO#"); line(112, t["bill"][2]); y -= 36
        line(22, "QORD QSHP PART# / DESCRIPTION"); line(220, "BIN"); line(250, "JB PF"); y -= 10
        line(22, "---- ---- ------------------------------ ------ -- --"); y -= 22
        for qord, qshp, part, desc, bin_, jb in t["items"]:
            c.drawRightString(36, y, str(qord)); c.drawRightString(58, y, str(qshp))
            line(64, part); line(155, desc); line(220, bin_); line(255, jb)
            y -= 12
        c.showPage()
    c.save()

    # Rasterise so the result is a picture of a page, like a real scan.
    src = pdfium.PdfDocument(buf.getvalue())
    images = [src[i].render(scale=200 / 72).to_pil().convert("L") for i in range(len(src))]
    images[0].save(path, save_all=True, append_images=images[1:], resolution=200)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "sample_tickets.pdf")

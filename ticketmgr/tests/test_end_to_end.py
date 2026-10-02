import io
import shutil

import pytest

pytest.importorskip("reportlab")
if not shutil.which("tesseract"):
    pytest.skip("Tesseract OCR is not installed", allow_module_level=True)

from sample import build  # noqa: E402
from ticketmgr.app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    app.config["TESTING"] = True
    return app.test_client()


def upload(client, path):
    with open(path, "rb") as f:
        return client.post("/import", data={"pdfs": (io.BytesIO(f.read()), "scan.pdf")},
                           content_type="multipart/form-data")


def test_scan_to_ticket_round_trip(client, tmp_path):
    pdf = tmp_path / "scan.pdf"
    build(pdf)

    r = upload(client, pdf)
    assert r.status_code == 200
    assert b"2 new ticket(s)" in r.data

    page = client.get("/").data.decode()
    assert "RO478342" in page and "RO478327" in page
    assert "AMALIA MIGUEL MATEO" in page
    assert "1 of 3 short" in page

    detail = client.get("/tickets/1").data.decode()
    for text in ("PZ1Z-5A215-B", "FT4Z-6N652-D", "-W719190-S901", "CLAMP - EXHAUS", "6 LELAND CIR"):
        assert text in detail

    client.post("/tickets/1/notes", data={"body": "Stud on order, ETA Friday", "author": "Jesse"})
    client.post("/tickets/1/update", data={"status": "On Hold", "priority": "High"})
    detail = client.get("/tickets/1").data.decode()
    assert "Stud on order, ETA Friday" in detail
    assert "Status: Waiting on Parts → On Hold" in detail

    # Importing the same stack again updates, never duplicates.
    r = upload(client, pdf)
    assert b"0 new ticket(s)" in r.data and b"2 updated" in r.data
    assert client.get("/tickets/3").status_code == 404
    assert "Stud on order, ETA Friday" in client.get("/tickets/1").data.decode()
    assert client.get("/pages/1.png").status_code == 200

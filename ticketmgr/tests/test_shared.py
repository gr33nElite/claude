"""Several computers using one TicketMgr host."""

import pytest
from PIL import Image

from test_importer import FakeReader, header, item, make_pdf
from ticketmgr.app import create_app


@pytest.fixture
def app(tmp_path):
    pages = [{"header": header("RO1"), "items": [item("A-1", 1, 0)]}]
    app = create_app(tmp_path / "data", reader=FakeReader(pages), shared=True)
    app.config["TESTING"] = True
    pdf = tmp_path / "scan.pdf"
    make_pdf(pdf, 1)
    with open(pdf, "rb") as f:
        app.test_client().post("/import", data={"pdfs": (f, "scan.pdf")},
                               content_type="multipart/form-data")
    return app


def test_notes_from_each_computer_are_shared_and_signed(app):
    front, back = app.test_client(), app.test_client()
    front.post("/me", data={"name": "Jesse"})
    back.post("/me", data={"name": "Scott"})

    before = front.get("/api/stamp").get_json()["stamp"]
    front.post("/tickets/1/notes", data={"body": "Called customer"})
    back.post("/tickets/1/notes", data={"body": "Parts on the blue shelf"})
    back.post("/tickets/1/update", data={"status": "Parts Ready"})
    assert front.get("/api/stamp").get_json()["stamp"] != before

    page = front.get("/tickets/1").data.decode()
    assert "Called customer" in page and "Parts on the blue shelf" in page
    assert "Jesse" in page and "Scott" in page
    assert "Status: Waiting on Parts → Parts Ready" in page


def test_note_needs_a_name(app):
    anon = app.test_client()
    anon.post("/tickets/1/notes", data={"body": "Who wrote this?"})
    assert "Who wrote this?" not in anon.get("/tickets/1").data.decode()
    anon.post("/tickets/1/notes", data={"body": "Now signed", "author": "Max"})
    page = anon.get("/tickets/1").data.decode()
    assert "Now signed" in page and "You: Max" in page


def test_share_page_lists_addresses(app, monkeypatch):
    monkeypatch.setattr("ticketmgr.app.lan_addresses", lambda: ["192.168.1.20"])
    assert "http://192.168.1.20:5000" in app.test_client().get("/share").data.decode()

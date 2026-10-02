"""Command line entry point.

    python -m ticketmgr                 start the web app on http://127.0.0.1:5000
    python -m ticketmgr import a.pdf    import scans without opening the app
"""

import argparse
import threading
import webbrowser

from . import db
from .app import create_app
from .extract import TESSERACT_MISSING, find_tesseract
from .importer import Importer


def main():
    parser = argparse.ArgumentParser(prog="ticketmgr")
    parser.add_argument("--data", help="folder for the database and scans (default: ./data)")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="start the web app (default)")
    serve.add_argument("--port", type=int, default=5000)
    serve.add_argument("--no-browser", action="store_true")
    imp = sub.add_parser("import", help="import one or more PDF scans")
    imp.add_argument("pdfs", nargs="+")
    args = parser.parse_args()

    app = create_app(args.data)
    if args.cmd == "import":
        if not find_tesseract():
            raise SystemExit(TESSERACT_MISSING)
        conn = db.connect(app.config["DB_PATH"])
        importer = Importer(conn, app.config["DATA_DIR"])
        for path in args.pdfs:
            r = importer.import_pdf(path, progress=lambda i, n: print(f"  page {i + 1}/{n}", end="\r"))
            print(f"{path}: {r['pages']} pages, {len(r['created'])} new, "
                  f"{len(r['updated'])} updated, {len(r['review'])} need review")
        return

    port = getattr(args, "port", 5000)
    if not getattr(args, "no_browser", False):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

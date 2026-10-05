"""Command line entry point.

    python -m ticketmgr                 start the web app on http://127.0.0.1:5000
    python -m ticketmgr serve --share   also let other computers on the network use it
    python -m ticketmgr import a.pdf    import scans without opening the app
"""

import argparse
import threading
import webbrowser

from . import db
from .app import create_app
from .extract import TESSERACT_MISSING, find_tesseract
from .importer import Importer
from .net import lan_addresses


def main():
    parser = argparse.ArgumentParser(prog="ticketmgr")
    parser.add_argument("--data", help="folder for the database and scans (default: ./data)")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="start the web app (default)")
    serve.add_argument("--port", type=int, default=5000)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--share", action="store_true",
                       help="let other computers on this network open TicketMgr")
    imp = sub.add_parser("import", help="import one or more PDF scans")
    imp.add_argument("pdfs", nargs="+")
    args = parser.parse_args()

    port = getattr(args, "port", 5000)
    shared = getattr(args, "share", False)
    app = create_app(args.data, shared=shared, port=port)
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

    host = "0.0.0.0" if shared else "127.0.0.1"
    print(f"TicketMgr is running. On this computer: http://127.0.0.1:{port}")
    if shared:
        for ip in lan_addresses():
            print(f"On other computers on the network:  http://{ip}:{port}")
    print("Keep this window open while TicketMgr is in use. Close it to stop.")
    if not getattr(args, "no_browser", False):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        # waitress handles several people at once better than Flask's built-in server.
        from waitress import serve as waitress_serve
    except ImportError:
        app.run(host=host, port=port, threaded=True)
    else:
        waitress_serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()

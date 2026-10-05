# TicketMgr

Turn scanned pick tickets into digital tickets you can track and keep notes on.

Scan a stack of printed **PICKING TICKET** pages to a PDF and import it. Every
page becomes a ticket keyed by its invoice number. The ticket holds the
customer, PO and phone, plus every line: ordered, shipped, part #, description
and bin. Each ticket also has a status, a priority, an assignee, a follow-up
date and a worklog of notes. The scanned page is kept too, so the handwriting
stays visible.

Importing the same tickets again (for example after more parts arrive and you
rescan) **updates** the existing tickets instead of making duplicates. Shipped
quantities and new lines are logged in the worklog, and your notes, status and
any lines you corrected by hand are kept. When every line on a ticket that was
waiting on parts has shipped, the ticket moves to *Parts Ready* on its own.

Everything runs on your own computer, and nothing is sent anywhere.

## Install (Windows)

1. Install **Python 3.10+** from <https://www.python.org/downloads/>. If the
   installer offers *Add python.exe to PATH*, tick it. Newer installers set
   up the `py` command instead, which works the same way.
2. Install **Tesseract OCR** (the free text reader). The simplest way is to
   run `winget install UB-Mannheim.TesseractOCR` in a Command Prompt, or use
   the installer from <https://github.com/UB-Mannheim/tesseract/wiki>. The
   default install location is fine, since TicketMgr looks for it there.
3. Open a Command Prompt in this `ticketmgr` folder and run:

   ```
   py -m pip install -r requirements.txt
   ```

   (Use `python` in place of `py` if `py` isn't recognized.)

4. Double-click `start.bat` (or run `py -m ticketmgr`). Your browser opens
   at <http://127.0.0.1:5000>.

On macOS, run `brew install tesseract`. On Debian or Ubuntu, run
`sudo apt install tesseract-ocr`. Then follow steps 3 and 4.

## Sharing with other computers

One computer (the host) runs TicketMgr and keeps the tickets. Other
computers on the same network open it in a web browser, so they don't need
Python or Tesseract installed, and everyone sees the same tickets and notes.

1. On the host, start TicketMgr with **`start-shared.bat`** (or
   `py -m ticketmgr serve --share`). If Windows asks whether to let Python
   through the firewall, allow it on **private** networks.
2. On the host, open **Other computers** in TicketMgr. It shows the address
   to use, such as `http://192.168.1.20:5000`.
3. On each other computer, open that address in a browser and bookmark it.

The host has to stay on with TicketMgr running. Everyone on the network can
open it, and there's no password, so only share it on your own business
network. Each computer asks for a name once, and notes and changes are
signed with it. Open pages refresh by themselves when someone else makes a
change; if you're typing at the time, a banner asks you to refresh instead.

## Using it

- **Import scans**: choose one or more PDFs. Picking them straight from the
  flash drive is fine. Each page takes a second or two, and each one is read on
  its own, so a single PDF of the whole stack works.
- **Tickets**: open tickets appear newest first, with a tab for each status. The
  search box looks through invoice numbers, customers, POs, part numbers and
  notes. "3 of 12 short" means three lines shipped less than was ordered.
- **A ticket**: change the status, priority, assignee and follow-up date; add
  notes; fix or add lines. The scan is shown alongside.
- **"check scan" flag**: OCR can't read lines that are crossed out or written
  over, so tickets with those lines get flagged and the worklog lists what was
  missed. Compare the ticket with the scan, fix the lines, then press
  *Mark as checked*.

Your data lives in `ticketmgr/data/`: the `tickets.db` database, the original
PDFs and the page images. Back up that folder to keep your tickets.

To import from the command line without opening the app:

```
python -m ticketmgr import scan1.pdf scan2.pdf
```

## How it reads a ticket

`ticketmgr/extract.py` renders each page at 300 dpi and runs Tesseract on the
left 62% of the page, where the printout is. The right side and the margin are
mostly handwriting. `ticketmgr/parse.py` finds the `INVOICE# CUST# BILL TO SHIP
TO SOLD BY` heading and the `QORD QSHP PART# / DESCRIPTION BIN JB PF` heading,
then assigns each word to a column by where it sits under those headings. Words
to the right of the PF column are ignored. If the ticket layout ever changes,
`parse.py` is the file to adjust.

## Development

```
python -m pip install -r requirements-dev.txt
python -m pytest tests
python tests/sample.py sample.pdf   # make a fake two-ticket scan to try the app with
```

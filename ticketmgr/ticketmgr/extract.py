"""Render scanned pick ticket pages and run OCR on the printed areas.

The printed ticket only occupies the upper-left part of the page; the rest
is where people write by hand. OCR is limited to the printed regions so
handwriting doesn't scramble the text.
"""

import os
import shutil

import pypdfium2 as pdfium
import pytesseract

TESSERACT_MISSING = ("Tesseract OCR isn't installed, so scans can't be read. Install it "
                     "(in a Command Prompt: winget install UB-Mannheim.TesseractOCR), "
                     "then import again.")


def find_tesseract():
    """Point pytesseract at Tesseract; return False if it isn't installed.

    Checked on every import, so installing Tesseract while the app is
    running works without a restart. On Windows the installer doesn't add
    itself to PATH, so look in the usual install folders too.
    """
    if shutil.which("tesseract"):
        pytesseract.pytesseract.tesseract_cmd = "tesseract"
        return True
    for candidate in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                      os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True
    return False

OCR_DPI = 300

# The printed ticket sits in the left part of the page; the right side is
# mostly handwriting. Fraction of the page width to OCR.
PRINT_WIDTH = 0.62


def page_count(pdf_path):
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(pdf_path, page_index, dpi=OCR_DPI):
    """Render one page to a PIL image."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[page_index].render(scale=dpi / 72).to_pil()
    finally:
        pdf.close()


def _crop(image, region):
    w, h = image.size
    left, top, right, bottom = region
    return image.crop((int(w * left), int(h * top), int(w * right), int(h * bottom)))


def ocr_words(image):
    """OCR an image into lines of positioned words: [[(x, y, text), ...], ...]."""
    data = pytesseract.image_to_data(image, config="--psm 6", output_type=pytesseract.Output.DICT)
    lines = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((data["left"][i], data["top"][i], text))
    ordered = sorted(lines.values(), key=lambda words: min(w[1] for w in words))
    return [sorted(words) for words in ordered]


def ocr_page(pdf_path, page_index):
    """Return (header_lines, table_lines, image) for one scanned page.

    Header and item table are read in one pass: Tesseract keeps the printed
    rows together far better when it sees the header above them.
    """
    image = render_page(pdf_path, page_index).convert("L")
    w, h = image.size
    lines = ocr_words(_crop(image, (0, 0, PRINT_WIDTH, 1)))
    # The item table starts under the "QORD QSHP PART#" heading.
    split = next((i + 1 for i, words in enumerate(lines)
                  if any(t.upper().startswith("QORD") for _, _, t in words)), None)
    if split is None:
        split = next((i for i, words in enumerate(lines)
                      if min(y for _, y, _ in words) > 0.22 * h), len(lines))
    return lines[:split], lines[split:], image

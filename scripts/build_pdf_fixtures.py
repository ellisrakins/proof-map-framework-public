"""Rebuild original, deterministic PDF fixtures (no third-party manuscripts)."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "papers" / "pdf"
    root.mkdir(parents=True, exist_ok=True)
    born = Canvas(str(root / "born_digital.pdf"), pagesize=(500, 320), invariant=1)
    born.setTitle("ProofMap original born-digital fixture")
    born.setFont("Helvetica-Bold", 18)
    born.drawString(35, 270, "An elementary identity")
    born.setFont("Helvetica", 12)
    born.drawString(35, 230, "Theorem 1. For every integer x, 2*x = x+x.")
    born.drawString(35, 200, "Proof. This is the distributive law.")
    born.drawString(35, 155, "Original synthetic fixture; not a research publication.")
    born.save()
    image = Image.new("RGB", (900, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 40), "SCANNED FIXTURE: x + x = 2*x", fill="black", font_size=28)
    draw.text((30, 110), "No embedded text. OCR is required.", fill="black", font_size=25)
    data = BytesIO()
    image.save(data, format="PNG")
    scan = Canvas(str(root / "scan.pdf"), pagesize=(500, 320), invariant=1)
    scan.setTitle("ProofMap original scanned fixture")
    scan.drawImage(ImageReader(data), 20, 70, width=460, height=205)
    scan.save()


if __name__ == "__main__":
    main()

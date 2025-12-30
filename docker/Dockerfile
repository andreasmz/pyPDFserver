# pyPDFserver by Andreas Brilka 2026

FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ocrmypdf \
        tesseract-ocr-data-osd \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-deu \
        tesseract-ocr-data-fra \
        tesseract-ocr-data-spa \
        
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pypdfserver

VOLUME ["/tmp"]

EXPOSE 21
CMD ["python", "-m", "pypdfserver"]
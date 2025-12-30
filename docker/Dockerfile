# pyPDFserver by Andreas Brilka 2026

FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ocrmypdf \
        tesseract-data-osd \
        tesseract-data-eng \
        tesseract-data-deu \
        tesseract-data-fra \
        tesseract-data-spa \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pypdfserver

VOLUME ["/tmp", "/etc/pyPDFserver/", "~/.local/state/pyPDFserver/"]

EXPOSE 21
EXPOSE 23000-23020
CMD ["python", "-m", "pypdfserver"]
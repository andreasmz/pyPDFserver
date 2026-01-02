# pyPDFserver by Andreas Brilka 2026

# Stage 1: Build jbig2enc
FROM debian:bookworm-slim AS jbig2enc-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    libleptonica-dev \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/agl/jbig2enc.git /src/jbig2enc \
 && cd /src/jbig2enc \
 && ./autogen.sh \
 && ./configure \
 && make -j$(nproc) \
 && make install

# Stage 2: Runtime image
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ocrmypdf \
        ghostscript \
        jbig2dec \
        pngquant \
        unpaper \
        tesseract-ocr \
        tesseract-ocr-osd \
        tesseract-ocr-eng \
        tesseract-ocr-deu \
        tesseract-ocr-fra \
        tesseract-ocr-spa \
        tesseract-ocr-ita \
        tesseract-ocr-pol \
        tesseract-ocr-por \
        tesseract-ocr-nld \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the binaries of jbig2enc to this docker image
COPY --from=jbig2enc-builder /usr/local/bin/jbig2enc /usr/local/bin/jbig2

# Build python package
COPY dist/python-package-distributions /tmp/dist

RUN pip install --no-cache-dir /tmp/dist/*.whl && rm -rf /tmp/dist

# Optimization
RUN strip /usr/local/bin/jbig2 || true && \
    strip /usr/bin/ocrmypdf || true

EXPOSE 80 21 23000-23010
CMD ["python", "-m", "pypdfserver"]
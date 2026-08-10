# Sales Canvas Bot — image untuk server API + dashboard + bot Telegram
FROM python:3.12-slim

# Tesseract OCR + bahasa Indonesia, plus lib yang dibutuhkan opencv/pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ind \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

# Gunakan tesseract sistem (di dalam container sudah diinstall via apt)
ENV TESSERACT_CMD=tesseract
ENV OCR_LANG=ind+eng

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "run.py"]

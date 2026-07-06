FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y curl_cffi || true

COPY . .

RUN mkdir -p data && rm -f /root/.cache/py-yfinance && mkdir -p /root/.cache/py-yfinance

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

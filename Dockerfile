FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x scripts/*.sh load/*.sh || true

EXPOSE 8080

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
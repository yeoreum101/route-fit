FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY routefit routefit
COPY data data
COPY web web

EXPOSE 8000
CMD ["uvicorn", "routefit.api:app", "--host", "0.0.0.0", "--port", "8000"]

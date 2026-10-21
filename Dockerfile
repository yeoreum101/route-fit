# 1단계: 화면(React) 빌드
FROM node:22-alpine AS fe
WORKDIR /fe
COPY fe/package.json fe/package-lock.json ./
RUN npm ci
COPY fe .
RUN npm run build

# 2단계: 서버. 빌드된 화면(fe/dist)만 가져온다
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY routefit routefit
COPY data data
COPY --from=fe /fe/dist fe/dist

EXPOSE 8000
CMD ["uvicorn", "routefit.api:app", "--host", "0.0.0.0", "--port", "8000"]

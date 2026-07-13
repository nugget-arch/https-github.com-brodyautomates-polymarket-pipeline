# API image. No CryptOption connectivity; research/paper/shadow only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# quant_engine is a workspace dependency installed from source.
COPY packages/quant_engine /app/packages/quant_engine
COPY apps/api /app/apps/api

RUN pip install --no-cache-dir -e /app/packages/quant_engine \
 && pip install --no-cache-dir -e "/app/apps/api"

WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "cryptoption_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

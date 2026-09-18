# OrderFlow Pro — zero-dependency image (Python stdlib only).
FROM python:3.12-slim

WORKDIR /app
COPY . /app

ENV ORDERFLOW_HOST=0.0.0.0 \
    ORDERFLOW_PORT=8787 \
    PYTHONUNBUFFERED=1

EXPOSE 8787

# Basic container healthcheck against the app's own endpoint.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=4).status==200 else 1)"

CMD ["python3", "server.py"]

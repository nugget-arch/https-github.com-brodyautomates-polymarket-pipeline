# otc_lab — research image. No broker connectivity: the platform is
# paper/shadow only and live execution is disabled in code.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

WORKDIR /app

COPY pyproject.toml README.md ./
COPY otc_lab ./otc_lab
COPY config ./config
COPY tests ./tests

RUN pip install --no-cache-dir .[dev]

# default: generate sample data, run the test suite, then a full research pass
CMD ["bash", "-lc", "python -m otc_lab.cli synth --out data/sample && pytest && python -m otc_lab.cli research --config config/default.yaml"]

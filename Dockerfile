FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp/jpjobs-home

WORKDIR /app

COPY pyproject.toml README.md USAGE.md AGENTS.md LICENSE ./
COPY jpjobs ./jpjobs
COPY deploy/constraints.txt ./deploy/constraints.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        --constraint deploy/constraints.txt . \
    && python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && groupadd --gid 10001 jpjobs \
    && useradd --uid 10001 --gid 10001 --no-create-home jpjobs

COPY deploy ./deploy
RUN chmod 0755 /app/deploy/run-daily.sh

USER 10001:10001

CMD ["python", "-m", "jpjobs.scheduler"]

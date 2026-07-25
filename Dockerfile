FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

COPY pyproject.toml README.md USAGE.md AGENTS.md LICENSE ./
COPY jpjobs ./jpjobs

RUN python -m pip wheel --no-deps --wheel-dir /wheels .


FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp/jpjobs-home

WORKDIR /app

COPY deploy/constraints.txt ./deploy/constraints.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        --constraint deploy/constraints.txt \
        "httpx>=0.27" "playwright>=1.40" "selectolax>=0.3.21" \
    && python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && groupadd --gid 10001 jpjobs \
    && useradd --uid 10001 --gid 10001 --no-create-home jpjobs

COPY --from=builder /wheels/jpjobs-*.whl /tmp/
RUN python -m pip install --no-cache-dir --no-deps /tmp/jpjobs-*.whl \
    && find /tmp -maxdepth 1 -name 'jpjobs-*.whl' -delete

COPY deploy ./deploy
RUN chmod 0755 /app/deploy/run-daily.sh

USER 10001:10001

CMD ["python", "-m", "jpjobs.scheduler"]

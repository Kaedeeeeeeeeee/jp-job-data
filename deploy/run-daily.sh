#!/bin/sh
set -eu

umask 077

data_dir="${JPJOBS_DATA_DIR:-/data}"
database="${JPJOBS_DATABASE:-${data_dir}/jobs.sqlite3}"
backup_dir="${JPJOBS_BACKUP_DIR:-${data_dir}/backups}"
as_of="${JPJOBS_AS_OF:-$(TZ=Asia/Tokyo date +%F)}"
checkpoint_dir="${data_dir}/checkpoints"
state_dir="${data_dir}/state"
checkpoint="${checkpoint_dir}/daily-${as_of}.json"

mkdir -p "${backup_dir}" "${checkpoint_dir}" "${state_dir}"
printf '%s\n' "${as_of}" > "${state_dir}/last-attempt"

jpjobs \
    --sources=all \
    --days=30 \
    --as-of="${as_of}" \
    --pages=auto \
    --max-pages=100 \
    --source-max-pages=hellowork=500 \
    --source-max-pages=daijob=500 \
    --source-max-pages=wantedly=200 \
    --checkpoint="${checkpoint}" \
    --rate-limit=1000 \
    --fetch-details \
    --fetch-details-new-only \
    --database="${database}" \
    --maintain-database \
    --missing-threshold="${JPJOBS_MISSING_THRESHOLD:-3}" \
    --retention-days="${JPJOBS_RETENTION_DAYS:-90}" \
    --purge-grace-days="${JPJOBS_PURGE_GRACE_DAYS:-30}" \
    --format=llm \
    --output="${data_dir}/latest-summary.md"

rm -f "${checkpoint}"
python -m jpjobs.backup \
    --database="${database}" \
    --output-dir="${backup_dir}" \
    --keep="${JPJOBS_BACKUP_KEEP:-14}"
printf '%s\n' "${as_of}" > "${state_dir}/last-success"

#!/usr/bin/env bash
# Local-only re-backfill of ensemble_v1 over 2026 YTD to measure the
# PR 1+2+3 coverage delta vs R&D. Not for prod use — prod backfill is on
# Cloud Run via the bastion tunnel.
#
# Usage: bash scripts/_backfill_ensemble_local.sh
set -uo pipefail

START="${START_DATE:-2026-01-02}"
END="${END_DATE:-2026-05-11}"
LOG="tmp/backfill_$(date +%Y%m%d_%H%M%S).log"
mkdir -p tmp

export DATABASE_SYNC_URL="postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass"
export DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5433/commodities_compass"

DATES=$(PGPASSWORD=password psql -h localhost -p 5433 -U postgres -d commodities_compass -tA -c \
  "SELECT to_char(d, 'YYYY-MM-DD') FROM (SELECT DISTINCT date AS d FROM pl_contract_data_daily WHERE date BETWEEN '${START}' AND '${END}' AND close IS NOT NULL) s ORDER BY d ASC")

N_TOTAL=$(echo "$DATES" | wc -l | tr -d ' ')
N=0
N_OK=0
N_FAIL=0

echo "Backfilling ensemble_v1 across ${N_TOTAL} business days [${START} → ${END}]" | tee "${LOG}"
echo "Log: ${LOG}" | tee -a "${LOG}"

for d in $DATES; do
  N=$((N + 1))
  RC=$(poetry run ensemble-compute --session-date "$d" --historical 2>>"${LOG}" >>"${LOG}"; echo $?)
  if [ "$RC" = "0" ]; then
    N_OK=$((N_OK + 1))
    printf "[%3d/%3d] %s OK\n" "$N" "$N_TOTAL" "$d"
  else
    N_FAIL=$((N_FAIL + 1))
    printf "[%3d/%3d] %s FAIL (rc=%s)\n" "$N" "$N_TOTAL" "$d" "$RC"
  fi
done

echo "" | tee -a "${LOG}"
echo "DONE — ${N_OK}/${N_TOTAL} ok, ${N_FAIL} failed" | tee -a "${LOG}"

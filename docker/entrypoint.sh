#!/usr/bin/env bash
# Modes:
#   web        gunicorn serving the site
#   scheduler  the newsroom pipeline every $SCHEDULE_MINUTES minutes
#   all        both in one container (for hosts where only one container can mount the disk)
#   anything else is run as a command, e.g.
#              python scripts/download_football_data.py --replace
set -euo pipefail

mode="${1:-all}"
mkdir -p /data/models /data/results /data/keras 2>/dev/null || true

seed_results() {
  # Opt-in: RESULTS_SEASONS="2425 2526 2627" downloads Football-Data.co.uk CSVs into
  # RESULTS_DIR on first start (when it holds no CSVs yet). RESULTS_LEAGUE defaults to E0.
  local dir="${RESULTS_DIR:-/data/results}"
  if [ -n "${RESULTS_SEASONS:-}" ] && ! compgen -G "$dir/*.csv" >/dev/null; then
    echo "Downloading results for seasons ${RESULTS_SEASONS} into $dir ..."
    # shellcheck disable=SC2086
    python scripts/download_football_data.py --league "${RESULTS_LEAGUE:-E0}" \
      --seasons ${RESULTS_SEASONS} || echo "Results download failed (see above)." >&2
  fi
}

preflight() {
  seed_results
  # Prints every problem; in production a failure stops the container.
  if ! python -m touchline_takes.preflight && [ "${TOUCHLINE_ENV:-}" = "production" ]; then
    echo "Preflight failed: fix the errors above (see DEPLOY.md)." >&2
    exit 1
  fi
}

web_cmd=(gunicorn touchline_takes.wsgi:app
         --bind "0.0.0.0:${PORT:-8000}"
         --workers "${WEB_CONCURRENCY:-2}" --threads 4 --timeout 60
         --access-logfile - --error-logfile -)
scheduler_cmd=(python -m touchline_takes.run --schedule "${SCHEDULE_MINUTES:-30}" --quiet)

case "$mode" in
  web)
    preflight
    exec "${web_cmd[@]}"
    ;;
  scheduler)
    preflight
    exec "${scheduler_cmd[@]}"
    ;;
  all)
    preflight
    "${scheduler_cmd[@]}" &
    scheduler_pid=$!
    "${web_cmd[@]}" &
    web_pid=$!
    stopping=0
    stop() {
      if [ "$stopping" = 0 ]; then
        stopping=1
        kill -TERM "$scheduler_pid" "$web_pid" 2>/dev/null || true
      fi
    }
    trap stop TERM INT
    # If either process exits, stop the other so the platform restarts the container.
    set +e
    wait -n "$scheduler_pid" "$web_pid"
    status=$?
    requested=$stopping
    stop
    wait
    # A requested stop (docker stop / redeploy) is a clean exit.
    if [ "$requested" = 1 ]; then exit 0; fi
    exit "$status"
    ;;
  *)
    exec "$@"
    ;;
esac

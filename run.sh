#!/usr/bin/env sh
set -eu

docker build -t digital-detective .
if [ "$#" -eq 0 ]; then
    set -- --help
fi
docker run --rm -v "$(pwd)/reports:/reports" digital-detective "$@" --output-dir /reports

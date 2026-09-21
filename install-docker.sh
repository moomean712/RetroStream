#!/bin/sh
exec sh "$(dirname "$0")/docker/install-docker.sh" "$@"

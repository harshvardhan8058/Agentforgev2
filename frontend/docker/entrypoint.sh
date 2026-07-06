#!/bin/sh
# Runtime_Config generator for the Frontend_Image (deployment Req 8.1-8.5).
#
# Renders /config.js at container start from the API_BASE_URL environment variable
# so a single build-once image runs anywhere without a rebuild. When API_BASE_URL
# is unset, an empty config object is emitted and the Web_Client falls back to its
# documented default. Only the non-secret base URL is ever written — no credential
# path exists here (Req 8.5). After rendering, exec the passed command (nginx).
#
# The Dockerfile that consumes this entrypoint ships in Task 3; the CONFIG_TEMPLATE
# and CONFIG_OUTPUT paths below match the locations that image will use, but are
# overridable for testing.
set -eu

CONFIG_TEMPLATE="${CONFIG_TEMPLATE:-/etc/nginx/templates/config.js.template}"
CONFIG_OUTPUT="${CONFIG_OUTPUT:-/usr/share/nginx/html/config.js}"
API_BASE_URL="${API_BASE_URL:-}"

if [ -n "${API_BASE_URL}" ]; then
  export API_BASE_URL
  # Substitute ONLY ${API_BASE_URL}; leave any other $-sequences untouched.
  envsubst '${API_BASE_URL}' <"${CONFIG_TEMPLATE}" >"${CONFIG_OUTPUT}"
else
  printf 'window.__AGENTFORGE_CONFIG__ = {};\n' >"${CONFIG_OUTPUT}"
fi

exec "$@"

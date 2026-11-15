#!/bin/sh
# The web functions' start, run by the Lambda Web Adapter (AWS_LAMBDA_EXEC_WRAPPER).
# No access log (it would log paths and addresses) and --no-proxy-headers (uvicorn
# would otherwise trust the adapter's loopback and set request.client to the caller):
# the client's address is read only by web.security.client_address, from the last
# X-Forwarded-For value, which API Gateway's HTTP API appends.
export PYTHONPATH="${LAMBDA_TASK_ROOT:-.}${PYTHONPATH:+:$PYTHONPATH}"
exec python -m uvicorn asmbly_ceramics.web.app:create_from_environment --factory \
  --host 0.0.0.0 --port "$PORT" --no-access-log --no-proxy-headers

# Build context is the REPOSITORY ROOT (the API depends on apps/agents):
#   docker build -f apps/api/Dockerfile -t cold-call-api .
FROM registry.access.redhat.com/ubi9/python-312-minimal:latest AS build

WORKDIR /opt/app-root/src
RUN pip install --no-cache-dir "uv==0.13.6"

# Copy the agents package and the API; install from the committed lockfile only.
COPY --chown=1001:0 apps/agents ./apps/agents
COPY --chown=1001:0 apps/api ./apps/api
WORKDIR /opt/app-root/src/apps/api
RUN uv sync --frozen --no-dev --extra mongodb --no-editable

FROM registry.access.redhat.com/ubi9/python-312-minimal:latest

WORKDIR /opt/app-root/src/apps/api
COPY --from=build --chown=1001:0 /opt/app-root/src/apps/api/.venv ./.venv
ENV PATH="/opt/app-root/src/apps/api/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root (UBI default user is 1001). BIND_HOST must be set to the container's
# specific internal IP by the deployer; there is intentionally no all-interfaces default.
USER 1001
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn cold_call_api.main:app --host \"${BIND_HOST:?BIND_HOST must be set}\" --port 8000"]

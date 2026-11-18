# Build context: apps/web
#   docker build -t cold-call-web apps/web
FROM registry.access.redhat.com/ubi9/nodejs-22-minimal:latest AS build

WORKDIR /opt/app-root/src
COPY --chown=1001:0 package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY --chown=1001:0 . .
RUN npm run build && npm prune --omit=dev --ignore-scripts

FROM registry.access.redhat.com/ubi9/nodejs-22-minimal:latest

WORKDIR /opt/app-root/src
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=1001:0 /opt/app-root/src/package.json ./package.json
COPY --from=build --chown=1001:0 /opt/app-root/src/node_modules ./node_modules
COPY --from=build --chown=1001:0 /opt/app-root/src/.next ./.next
COPY --from=build --chown=1001:0 /opt/app-root/src/next.config.ts ./next.config.ts

# Non-root (UBI default user is 1001). BIND_HOST must be set to the container's
# specific internal IP by the deployer; there is intentionally no all-interfaces default.
USER 1001
EXPOSE 3000
CMD ["sh", "-c", "exec node_modules/.bin/next start --hostname \"${BIND_HOST:?BIND_HOST must be set}\" --port 3000"]

# AgentForge Frontend_Image — multi-stage, non-root static SPA server (Req 2.1-2.5, 1.3, 8.x).
#
# Stage 1 compiles the Vite/React SPA with the Node 22 toolchain. Stage 2 serves the
# compiled static assets with a NON-ROOT nginx (nginxinc/nginx-unprivileged, uid 101,
# listens on 8080). The final image contains ONLY the built `dist/` output plus the
# nginx config and the Runtime_Config entrypoint — no Node toolchain, no node_modules,
# and no application source (Req 2.2). The application is NOT modified.

# ---------------------------------------------------------------------------
# Stage 1: build — install deps and compile the SPA to /app/dist.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Dependency layer first (cached unless the lockfile/manifest changes), so a
# source-only change reuses the installed node_modules layer.
COPY package.json package-lock.json ./
RUN npm ci

# Application source, then the production build (`tsc --noEmit && vite build`).
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime — non-root nginx serving the compiled static assets only.
# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:alpine AS runtime

# Briefly become root only to place config/assets and fix ownership so the
# non-root runtime user (uid 101, "nginx") can write the rendered /config.js.
USER root

# SPA server config (try_files fallback + /healthz + runtime /config.js), replacing
# the stock default server.
COPY docker/default.conf /etc/nginx/conf.d/default.conf

# Runtime_Config template + entrypoint (reused from Task 2). The entrypoint renders
# /usr/share/nginx/html/config.js from API_BASE_URL at container start, then execs
# nginx. CONFIG_TEMPLATE default (/etc/nginx/templates/config.js.template) matches
# the copy destination below.
COPY docker/config.js.template /etc/nginx/templates/config.js.template
COPY docker/entrypoint.sh /docker-entrypoint-agentforge.sh

# Compiled static assets ONLY — no node_modules, no source, no Node toolchain.
COPY --from=build /app/dist /usr/share/nginx/html

# Normalize line endings so the entrypoint execs correctly even when the repo was
# checked out with CRLF on a Windows host. A CRLF shebang makes the Linux kernel
# look for the interpreter "/bin/sh\r" (which does not exist), failing at container
# start with: exec /docker-entrypoint-agentforge.sh: no such file or directory.
# Stripping CR here makes the image build correct regardless of the developer's OS
# or git core.autocrlf setting (belt-and-suspenders with the repo .gitattributes).
RUN sed -i 's/\r$//' /docker-entrypoint-agentforge.sh /etc/nginx/templates/config.js.template \
    && chmod +x /docker-entrypoint-agentforge.sh \
    && chown -R nginx:nginx /usr/share/nginx/html

# Drop back to the built-in unprivileged user for all runtime processes (Req 1.3).
USER nginx

# Non-privileged listen port; the container runtime publishes the host port to 8080.
EXPOSE 8080

# Render /config.js from API_BASE_URL, then exec nginx (foreground).
ENTRYPOINT ["/docker-entrypoint-agentforge.sh"]
CMD ["nginx", "-g", "daemon off;"]

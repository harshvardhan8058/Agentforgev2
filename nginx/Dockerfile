# AgentForge Reverse_Proxy image — non-root nginx (deployment Req 6.x, 7.x, 1.3).
#
# Based on nginxinc/nginx-unprivileged so every process runs as uid 101 (no root).
# Ships the routing/security config and the SSE-safe proxy behavior. TLS is NOT baked
# in: the TLS server block and certificate material are mounted at runtime in
# production (see nginx/tls/agentforge-tls.conf). Build context is the nginx/ dir.
FROM nginxinc/nginx-unprivileged:alpine

# Briefly root only to place config and prepare the (empty) runtime TLS mount point.
USER root

# Main config (defines upstreams + non-root temp paths) and the HTTP server + shared
# snippets. The stock default server is removed so only our routing is active.
COPY nginx.conf              /etc/nginx/nginx.conf
COPY conf.d/agentforge.conf  /etc/nginx/conf.d/agentforge.conf
COPY snippets/               /etc/nginx/snippets/

# TLS server block is carried in the image for reference but NOT enabled by default
# (kept outside conf.d so a keyless local `nginx -t` passes without certs). Production
# mounts it into conf.d together with the cert/key.
COPY tls/agentforge-tls.conf /etc/nginx/tls-available/agentforge-tls.conf

RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /etc/nginx/tls \
    && chown -R nginx:nginx /etc/nginx/tls

# Back to the unprivileged runtime user for all processes (Req 1.3).
USER nginx

# Non-privileged listen ports; the runtime publishes host :80 -> 8080 and :443 -> 8443.
EXPOSE 8080 8443

# syntax=docker/dockerfile:1
FROM node:22.14.0-alpine3.21 AS build

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY public/ ./public/
COPY src/ ./src/

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN test "${VITE_API_BASE_URL}" = "/api" && npm run build

FROM nginxinc/nginx-unprivileged:1.27.4-alpine

COPY --chown=101:101 nginx.conf /etc/nginx/nginx.conf
COPY --from=build --chown=101:101 /build/dist/ /usr/share/nginx/html/

USER 101:101
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=6 \
  CMD ["wget", "--quiet", "--output-document=/dev/null", "http://127.0.0.1:8080/healthz"]

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]

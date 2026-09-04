# syntax=docker/dockerfile:1.6

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

# OpenShift assigns a random non-root UID. Group 0 permissions let that UID
# read the app and configuration without granting root privileges.
RUN chgrp -R 0 /etc/nginx /usr/share/nginx/html \
    && chmod -R g=u /etc/nginx /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1 || exit 1

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]

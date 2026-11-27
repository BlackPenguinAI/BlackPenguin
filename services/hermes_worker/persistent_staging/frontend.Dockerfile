FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY services/hermes_worker/persistent_staging/rewrite-origin.cjs /tmp/rewrite-origin.cjs
RUN node /tmp/rewrite-origin.cjs /app/src
ARG APP_COMMIT_SHA
RUN npm run build -- --configuration=production && APP_COMMIT_SHA=$APP_COMMIT_SHA npm run stamp:release
FROM nginx:alpine
COPY services/hermes_worker/persistent_staging/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
EXPOSE 8080

ARG APP_COMMIT_SHA=unknown

FROM node:20-alpine AS build
ARG APP_COMMIT_SHA
ARG BP_BUILD_CONFIGURATION=production
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build -- --configuration=$BP_BUILD_CONFIGURATION
RUN APP_COMMIT_SHA=$APP_COMMIT_SHA npm run stamp:release

FROM nginx:alpine
ARG APP_COMMIT_SHA
LABEL org.opencontainers.image.revision=$APP_COMMIT_SHA
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]


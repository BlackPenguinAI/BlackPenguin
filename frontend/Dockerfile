# Etapa 1: Construcción (Node)
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# 🚀 Compila Angular para producción
RUN npm run build --configuration=production

# Etapa 2: Servidor (Nginx)
FROM nginx:alpine
# Copiamos la configuración de Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Copiamos los archivos compilados de Angular al servidor Nginx
# NOTA: Si tu proyecto no se llama "frontend" en el package.json, cambia esta ruta.
# Por lo general en Angular 17+ es /dist/[nombre-proyecto]/browser
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
# 1) Build the app
FROM node:22.12.0-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

ARG VITE_LANGCONNECT_API_URL
ARG VITE_LANGCONNECT_API_SECRET_TOKEN
ARG VITE_MCP_PROXY_URL
ARG VITE_MEMORY_ENABLED
ENV VITE_LANGCONNECT_API_URL=$VITE_LANGCONNECT_API_URL
ENV VITE_LANGCONNECT_API_SECRET_TOKEN=$VITE_LANGCONNECT_API_SECRET_TOKEN
ENV VITE_MCP_PROXY_URL=$VITE_MCP_PROXY_URL
ENV VITE_MEMORY_ENABLED=$VITE_MEMORY_ENABLED

COPY . .
RUN npm run build

# 2) Nginx with DO-specific config
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.do.conf /etc/nginx/nginx.conf
COPY nginx.do.main.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

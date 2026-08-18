FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ---- runtime ----
FROM node:20-alpine

WORKDIR /app
RUN npm install -g serve --silent

COPY --from=build /app/dist /app/dist

EXPOSE 5173
# `serve` is the simplest static host that respects SPA routing and
# binds to all interfaces, which is what docker-compose needs.
CMD ["serve", "-s", "dist", "-l", "5173"]

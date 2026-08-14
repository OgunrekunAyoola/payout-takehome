# Multi-stage: the final image carries the built app and production deps only.
# BACKEND_URL and PROVIDER_WEBHOOK_SECRET are read at request time on the server (they
# are deliberately not NEXT_PUBLIC_), so nothing here bakes an environment into the
# bundle — the same image serves any backend it is pointed at.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.ts ./

EXPOSE 3000
CMD ["npm", "start"]

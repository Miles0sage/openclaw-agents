FROM node:20-alpine AS build

WORKDIR /app

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/. .
RUN npm run build

FROM node:20-alpine AS production

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/.next ./.next
COPY --from=build /app/app ./app
COPY --from=build /app/components ./components
COPY --from=build /app/hooks ./hooks
COPY --from=build /app/lib ./lib
COPY --from=build /app/next.config.js ./next.config.js
COPY --from=build /app/next.config.mjs ./next.config.mjs
COPY --from=build /app/postcss.config.js ./postcss.config.js
COPY --from=build /app/tailwind.config.js ./tailwind.config.js
COPY --from=build /app/tsconfig.json ./tsconfig.json
COPY --from=build /app/next-env.d.ts ./next-env.d.ts

EXPOSE 3000

CMD ["npm", "start", "--", "-H", "0.0.0.0"]

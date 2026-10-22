# Builder stage
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Pass NEXT_PUBLIC_API_URL during build time so client-side API requests point to the backend service
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL:-http://localhost:8000}
ENV NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL:-http://localhost:3000}
RUN npm run build

# Runner stage
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Preserve deployment platforms with an existing "npm start" override.
RUN node -e "const fs = require('node:fs'); const file = 'package.json'; const pkg = JSON.parse(fs.readFileSync(file, 'utf8')); pkg.scripts = { ...pkg.scripts, start: 'node server.js' }; fs.writeFileSync(file, JSON.stringify(pkg, null, 2) + '\n');"

EXPOSE 3000
CMD ["node", "server.js"]

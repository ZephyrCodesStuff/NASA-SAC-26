FROM oven/bun:1-alpine

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

RUN bun run build

ENV PORT=3000
ENV HOSTNAME=0.0.0.0
EXPOSE 3000

CMD ["bun", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]

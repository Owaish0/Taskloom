FROM node:22-slim

WORKDIR /app

ENV CI=true
RUN corepack enable

COPY frontend/package.json ./
RUN pnpm install

COPY frontend .

EXPOSE 5173

CMD ["pnpm", "dev", "--host"]

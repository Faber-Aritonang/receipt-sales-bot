# Sales Canvas Bot — image untuk bridge WhatsApp (Node.js + Baileys)
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

COPY index.js .

EXPOSE 3100

# Session WhatsApp disimpan di /app/auth (mount volume ke sini)
VOLUME ["/app/auth"]

CMD ["node", "index.js"]

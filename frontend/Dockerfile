# Dev image — production builds happen in CI; local uses Vite dev server with bind mount.
FROM node:24-alpine

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

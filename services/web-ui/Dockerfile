FROM node:20-slim AS frontend-build
WORKDIR /build
COPY services/web-ui/frontend/package.json services/web-ui/frontend/package-lock.json ./
RUN npm ci
COPY services/web-ui/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY services/web-ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/web-ui/main.py services/web-ui/auth.py ./
COPY --from=frontend-build /build/dist ./static
EXPOSE 3200
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3200"]

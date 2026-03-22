FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py auth.py ./
COPY --from=frontend-build /build/dist ./static
EXPOSE 3200
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3200"]

FROM python:3.11-slim
WORKDIR /app
COPY services/rl-train/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/rl-train/ .
EXPOSE 8004
CMD ["python", "main.py"]

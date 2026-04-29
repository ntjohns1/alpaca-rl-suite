FROM python:3.11-slim
WORKDIR /app
COPY services/backtest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared /shared
COPY services/backtest/ .
EXPOSE 8001
CMD ["python", "main.py"]

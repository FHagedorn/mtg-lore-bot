FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# seen.json landet im Volume /data und überlebt so Container-Neustarts
ENV DATA_DIR=/data
VOLUME /data

CMD ["python", "-u", "bot.py"]

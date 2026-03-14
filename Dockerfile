FROM python:3.11-slim

# Chromium, ChromeDriver, and VNC tools for one-time manual login session
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        xvfb \
        x11vnc \
        xterm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py publisher.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh

# data/ and chrome_profile/ are mounted as volumes at runtime
RUN mkdir -p /app/data /app/chrome_profile

CMD ["/app/entrypoint.sh"]

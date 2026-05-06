FROM python:3.12-slim

# Metadata
LABEL org.opencontainers.image.title="NapiProjekt Stremio Addon"
LABEL org.opencontainers.image.description="Polskie napisy dla Stremio z NapiProjekt i OpenSubtitles"
LABEL org.opencontainers.image.source="https://github.com/piotrek1488/napiprojekt-stremio-addon"

# System dependencies (7z for subtitle extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Default env vars (override in docker-compose or -e flags)
ENV PORT=8081
ENV BASE_URL=""
ENV TMDB_API_KEY=""
ENV OS_API_KEY=""
ENV RD_TOKEN=""

EXPOSE 8081

CMD ["python", "run.py"]

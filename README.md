## 🌍 Language
- 🇬🇧 English (default)
- 🇵🇱 [Polski](README.pl.md)

# NapiProjekt Stremio Addon 🎬

A Stremio addon that fetches **Polish subtitles** from [NapiProjekt](https://www.napiprojekt.pl) with optional fallback to [OpenSubtitles](https://www.opensubtitles.com).

You can install addon from here: [napiprojekt-stremio-addon.duckdns.org](https://napiprojekt-stremio-addon.duckdns.org)

---

## How it works

1. When you watch a movie in Stremio (via Torrentio + Real-Debrid), the file lands in your RD account
2. The addon finds the file on RD by matching the video size
3. It downloads the first 10MB of the file and computes an MD5 hash (NapiProjekt format)
4. It fetches subtitles from NapiProjekt using that hash
5. Subtitles are served as an SRT file directly to Stremio

---

## Requirements

- [Real-Debrid](https://real-debrid.com) account (required)
- [OpenSubtitles](https://www.opensubtitles.com/consumers) API key (optional, for fallback)
- [TMDB](https://www.themoviedb.org/settings/api) API key (optional, for movie title display)
- Docker or Python 3.12+

---

## Quick start (docker)
You can run this project as a Docker container using the pre-built image. This is the fastest way to deploy the addon without the need to set up a local Python environment.

Run the container:
```bash
docker run -d \
  --name napiprojekt-stremio-addon \
  -p 8081:8081 \
  -e BASE_URL=http://localhost:8081 \
  docker.io/ludvickpro/napiprojekt-stremio-addon:latest
```

## Docker deployment (recommended)

### Build locally

```bash
git clone https://github.com/piotrek1488/napiprojekt-stremio-addon.git
cd napiprojekt-stremio-addon
git checkout gemini

docker build -t napiprojekt-addon .

docker run -d \
  --name napiprojekt-addon \
  --restart unless-stopped \
  -p 8081:8081 \
  -e BASE_URL=https://your.duckdns.org \
  -e TMDB_API_KEY=your_tmdb_key \
  napiprojekt-addon
```

### Docker Compose

```yaml
services:
  napiprojekt-addon:
    build: .
    container_name: napiprojekt-addon
    restart: unless-stopped
    ports:
      - "8081:8081"
    environment:
      - BASE_URL=https://your.duckdns.org
      - TMDB_API_KEY=your_tmdb_key
      - PORT=8081
```

---

## Python deployment

```bash
git clone https://github.com/piotrek1488/napiprojekt-stremio-addon.git
cd napiprojekt-stremio-addon
git checkout gemini

pip install -r requirements.txt

cat > .env << EOF
BASE_URL=https://your.duckdns.org
TMDB_API_KEY=your_tmdb_key
PORT=8081
EOF

python run.py
```

---

## Configuration in Stremio

1. Open `https://your.duckdns.org` in your browser
2. Paste your Real-Debrid token (find it at [real-debrid.com/apitoken](https://real-debrid.com/apitoken))
3. (Optional) Paste your OpenSubtitles API key
4. Choose options:
   - **OpenSubtitles fallback** — search OS when no subtitles found on NapiProjekt *(enabled by default)*
   - **Always search OpenSubtitles** — show subtitles from both sources simultaneously
5. Click **Generate link** and install the addon in Stremio

---

## Environment variables

| Variable | Description | Required |
|----------|-------------|----------|
| `BASE_URL` | Public server URL e.g. `https://your.duckdns.org` | ✅ |
| `PORT` | Server port (default `8081`) | ❌ |
| `TMDB_API_KEY` | TMDB API key for movie title display | ❌ |

Real-Debrid and OpenSubtitles tokens are passed via the configuration URL — they are not stored on the server.

---

## Reverse proxy (Caddy)

```caddy
your.duckdns.org {
    reverse_proxy localhost:8081
}
```

---

## Debug endpoints

| Endpoint | Description |
|----------|-------------|
| `/debug/rd-files?rd_token=X` | List all RD files with sizes |
| `/debug/rd-napi?rd_token=X&video_size=Y` | Test full RD → NapiProjekt pipeline |
| `/debug/napi?hash=X` | Test subtitle download by MD5 hash |
| `/debug/napi-raw?hash=X` | Raw NapiProjekt response before format conversion |

---

## License

MIT

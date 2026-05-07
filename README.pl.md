## 🌍 Język
- 🇬🇧 [English](README.md)
- 🇵🇱 Polski

# NapiProjekt Stremio Addon 🎬

Addon do Stremio pobierający **polskie napisy** z [NapiProjekt](https://www.napiprojekt.pl) z opcjonalnym fallbackiem do [OpenSubtitles](https://www.opensubtitles.com).

Addon można zainstalować stąd: [napiprojekt-stremio-addon.duckdns.org](https://napiprojekt-stremio-addon.duckdns.org)

---

## Jak to działa

1. Gdy oglądasz film w Stremio (przez Torrentio + Real-Debrid), plik trafia na Twoje konto RD
2. Addon znajduje ten plik w RD po jego rozmiarze
3. Pobiera pierwsze 10MB pliku i oblicza hash MD5 (format NapiProjekt)
4. Pobiera napisy z NapiProjekt używając tego hasha
5. Serwuje napisy jako plik SRT bezpośrednio do Stremio

---

## Wymagania

- Konto [Real-Debrid](https://real-debrid.com) (wymagane)
- Klucz API [OpenSubtitles](https://www.opensubtitles.com/pl/consumers) (opcjonalne, do fallbacku)
- Klucz API [TMDB](https://www.themoviedb.org/settings/api) (opcjonalne, do wyświetlania tytułów)
- Docker lub Python 3.12+

---
## Szybki start (docker)
Możesz uruchomić ten projekt jako kontener Docker, korzystając z gotowego obrazu. Jest to najszybszy sposób na wdrożenie addonu bez konieczności konfigurowania lokalnego środowiska Pythona.

Uruchomienie kontenera:
```bash
docker run -d \
  --name napiprojekt-stremio-addon \
  -p 8081:8081 \
  -e BASE_URL=http://localhost:8081 \
  docker.io/ludvickpro/napiprojekt-stremio-addon:latest
```

## Deploy z Dockerem (zalecane)

### Zbuduj obraz lokalnie

```bash
git clone https://github.com/piotrek1488/napiprojekt-stremio-addon.git
cd napiprojekt-stremio-addon
git checkout gemini

docker build -t napiprojekt-addon .

docker run -d \
  --name napiprojekt-addon \
  --restart unless-stopped \
  -p 8081:8081 \
  -e BASE_URL=https://twoj.duckdns.org \
  -e TMDB_API_KEY=twój_klucz_tmdb \
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
      - BASE_URL=https://twoj.duckdns.org
      - TMDB_API_KEY=twój_klucz_tmdb
      - PORT=8081
```

---

## Deploy z Pythonem

```bash
git clone https://github.com/piotrek1488/napiprojekt-stremio-addon.git
cd napiprojekt-stremio-addon
git checkout gemini

pip install -r requirements.txt

cat > .env << EOF
BASE_URL=https://twoj.duckdns.org
TMDB_API_KEY=twój_klucz_tmdb
PORT=8081
EOF

python run.py
```

---

## Konfiguracja w Stremio

1. Otwórz `https://twoj.duckdns.org` w przeglądarce
2. Wklej token Real-Debrid (znajdziesz go na [real-debrid.com/apitoken](https://real-debrid.com/apitoken))
3. (Opcjonalnie) Wklej klucz API OpenSubtitles
4. Wybierz opcje:
   - **Fallback do OpenSubtitles** — szukaj w OS gdy brak napisów w NapiProjekt *(domyślnie włączony)*
   - **Zawsze szukaj w OpenSubtitles** — pokazuj napisy z obu źródeł jednocześnie
5. Kliknij **Generuj link** i zainstaluj addon w Stremio

---

## Zmienne środowiskowe

| Zmienna | Opis | Wymagana |
|---------|------|----------|
| `BASE_URL` | Publiczny URL serwera np. `https://twoj.duckdns.org` | ✅ |
| `PORT` | Port serwera (domyślnie `8081`) | ❌ |
| `TMDB_API_KEY` | Klucz API TMDB do wyświetlania tytułów filmów | ❌ |

Tokeny Real-Debrid i OpenSubtitles są przekazywane przez URL konfiguracyjny — nie są przechowywane na serwerze.

---

## Reverse proxy (Caddy)

```caddy
twoj.duckdns.org {
    reverse_proxy localhost:8081
}
```

---

## Endpointy diagnostyczne

| Endpoint | Opis |
|----------|------|
| `/debug/rd-files?rd_token=X` | Lista plików na koncie RD z rozmiarami |
| `/debug/rd-napi?rd_token=X&video_size=Y` | Test pełnego pipeline RD → NapiProjekt |
| `/debug/napi?hash=X` | Test pobierania napisów po hashu MD5 |
| `/debug/napi-raw?hash=X` | Surowa odpowiedź NapiProjekt przed konwersją formatu |

---

## Licencja

MIT

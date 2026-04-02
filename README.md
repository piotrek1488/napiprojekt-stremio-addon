# NapiProjekt + OpenSubtitles Stremio Addon

Addon do Stremio, który pobiera polskie napisy z NapiProjekt oraz OpenSubtitles jeśli na pierwszym serwisie ich nie ma.

## Funkcje

- Scraping NapiProjekt

- Pobieranie najlepszych wersji napisów `.srt`

- Fallback do OpenSubtitles

- Cache w pamięci

- Retry i timeout przy pobieraniu

- Kompatybilne z Stremio

## Instalacja

1. Zainstaluj zależności:
```bash
npm  install
```

2. Ustaw zmienne środowiskowe (opcjonalnie):
```bash
export  PUBLIC_URL="https://twojadomena.com"
export  PORT=7000
#Klucz API do OpenSubtitles:
export  OS_API_KEY="TWÓJ_KLUCZ_API"
#Jeśli nie znajdzie napisów w Napiprojekt, wyszukaj w OpenSubtitles:
export  ENABLE_OS_FALLBACK=true
```

3. Uruchom serwer:
```bash
npm  start
```

4. Dodaj addon do Stremio używając URL: http://localhost:7000/manifest.json

## Uwagi dotyczące działania

- Addon najpierw próbuje NapiProjekt. Jeśli nie znajdzie napisów, automatycznie przechodzi do OpenSubtitles.

- Nazwy plików wideo mają duże znaczenie dla dopasowania napisów. Najlepsze efekty dają nazwy w stylu *The.Matrix.1999.1080p.BluRay.x264*.

- Jeśli OpenSubtitles zwraca wiele wyników, addon wybiera 3 pierwsze.

- Można modyfikować scoring i ranking w [scoring.service.js](./src/services/scoring.service.js).
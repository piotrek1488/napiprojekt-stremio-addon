# Stremio NapiProjekt Pro (Python Edition)

W pełni obiektowy dodatek do Stremio, zbudowany w Pythonie (FastAPI). Wykorzystuje zaawansowany scraping (NapiProjekt) oraz wbudowane systemy oceny i buforowania danych.

## Co go wyróżnia na tle innych?
- **Python + FastAPI**: Szybki, bezbłędny serwer na miarę dzisiejszych standardów.
- **Scraping + `BeautifulSoup`**: Realistyczne zbieranie danych i formatowanie ich.
- **Smart Scoring (`thefuzz`)**: Dodatek szuka podobieństw do nazwy Twojego pliku wideo.

## Instalacja na własnym komputerze

1. Upewnij się, że posiadasz **Pythona 3.9+**.
2. Stwórz opcjonalne wirtualne środowisko (Virtual Environment):
   ```bash
   python -m venv venv
   source venv/bin/activate  # (Dla Windowsa: venv\Scripts\activate)
   ```
3. Zainstaluj wymagane pakiety z pliku requirements.txt:
   ```bash
    pip install -r requirements.txt
    ```
4. Uruchom serwer dodatku:
   ```bash
    python run.py
    ```
5. Serwer zadziała pod linkiem: 
```text
http://127.0.0.1:7000/manifest.json
```
Skopiuj ten link.
6. Otwórz aplikację Stremio -> Dodatki (Addons) -> wklej URL w pasku i kliknij Instaluj lub [kliknij tu](https://web.strem.io/#/addons?addon=http://127.0.0.1:7000/manifest.json).
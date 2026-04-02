# NapiProjekt Stremio addon

To jest best-effort addon do polskich napisów z NapiProjekt.

## Co robi

Addon:
- bierze `id`, `filename` i dostępne metadane z requestu napisów w Stremio,
- próbuje znaleźć stronę filmu w NapiProjekt,
- ocenia pasujące napisy po długości i po słowach z release/nazwy pliku,
- pobiera wybrany plik przez API NapiProjekt i wystawia go lokalnie pod URL-em dla Stremio.

## Ważne ograniczenie

Stremio w requestach napisów przekazuje tylko metadane, `videoHash` w formacie OpenSubtitles, rozmiar pliku i nazwę pliku. Nie przekazuje samych bajtów filmu, więc napiprojektowy hash z pliku nie da się policzyć 1:1 bez dodatkowego lokalnego bridge'a.

## Uruchomienie

```bash
npm install
PUBLIC_URL=http://localhost:7000 npm start
```

Jeśli hostujesz to zdalnie, ustaw `PUBLIC_URL` na publiczny adres tego serwera.

## Instalacja w Stremio

Wklej URL manifestu:

```text
http://localhost:7000/manifest.json
```

albo publiczny adres swojego serwera.

## Uwagi

Jeśli NapiProjekt zwróci wiele wersji, addon próbuje wybrać najlepszą na podstawie:
- zgodności czasu trwania,
- dopasowania słów z release i nazwy pliku,
- zgodności tytułu z metadanymi z Cinemeta.

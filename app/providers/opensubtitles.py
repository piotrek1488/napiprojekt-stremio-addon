async def search_opensubtitles(imdb_id: str):
    print(f"Szukam awaryjnie w OpenSubtitles dla ID: {imdb_id}")
    # Tu zazwyczaj wrzuca się wywołanie REST API
    return [{
        "id": f"os_{imdb_id}",
        "url": "https://mock-url.opensubtitles.org/sub.srt",
        "lang": "pol",
        "releaseName": f"Movie.{imdb_id}.1080p.WEBRip",
        "source": "OpenSubtitles"
    }]
import requests
import hashlib

# --- 1. pobierz ostatnie pliki z Real-Debrid ---

def get_rd_downloads(rd_token):
    r = requests.get(
        "https://api.real-debrid.com/rest/1.0/downloads",
        headers={"Authorization": f"Bearer {rd_token}"},
        timeout=10
    )
    if r.status_code != 200:
        return []
    return r.json()

# --- 2. znajdź pasujący plik ---

def find_matching_file(downloads, video_size):
    for d in downloads:
        if str(d.get("filesize")) == str(video_size):
            return d
    return None

# --- 3. policz hash Napi (pierwsze 10MB) ---

def napi_hash_from_url(url):
    headers = {
        "Range": "bytes=0-10485759"
    }

    r = requests.get(url, headers=headers, timeout=15)

    if r.status_code not in (200, 206):
        return None

    data = r.content
    return hashlib.md5(data).hexdigest()[:16]

# --- 4. pobierz napisy z Napi ---

def fetch_napi_subtitles(hash_, file_size):
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"

    params = {
        "mode": "1",
        "client": "QNapi",
        "client_ver": "2.2.0",
        "downloaded_subtitles_txt": "1",
        "film_hash": hash_,
        "file_size": str(file_size)
    }

    r = requests.get(url, params=params, timeout=10)

    if r.status_code != 200 or not r.content:
        return None

    try:
        return r.content.decode("utf-8")
    except:
        return r.content.decode("cp1250", errors="ignore")

# --- 5. MAIN: wszystko razem ---

def get_napi_from_rd(rd_token, video_size):
    downloads = get_rd_downloads(rd_token)

    if not downloads:
        return None

    match = find_matching_file(downloads, video_size)

    if not match:
        return None

    download_url = match.get("download")

    if not download_url:
        return None

    hash_ = napi_hash_from_url(download_url)

    if not hash_:
        return None

    return fetch_napi_subtitles(hash_, video_size)
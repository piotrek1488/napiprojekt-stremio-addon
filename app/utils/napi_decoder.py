import httpx
import base64
import io
import py7zr
import xml.etree.ElementTree as ET
import re

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"

async def get_napi_subtitles_text(title: str):
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"
    
    # Czyszczenie tytułu - Napi nie lubi śmieci
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', title).strip()
    
    # Przygotowanie danych DOKŁADNIE tak jak chce API
    data = {
        "mode": "3",
        "client": "NapiProjekt",
        "client_ver": "2.2.0.2399",
        "search_title": clean_title,
        "downloaded_subtitles_lang": "PL",
        "the": "end"
    }

    # Nagłówki udające oficjalny program - BEZ TEGO JEST 404
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "NapiProjekt/2.2.0.2399 (Windows NT)"
    }

    try:
        async with httpx.AsyncClient() as client:
            # Używamy POST z zakodowanymi danymi
            resp = await client.post(url, data=data, headers=headers, timeout=10.0)
            
            if "success" not in resp.text:
                print(f"ℹ️ Napi: Brak wyników dla '{clean_title}'")
                return None

            root = ET.fromstring(resp.text)
            content_node = root.find(".//content")
            
            if content_node is not None and content_node.text:
                # Dekodowanie base64 -> 7zip -> SRT
                compressed_data = base64.b64decode(content_node.text)
                archive = io.BytesIO(compressed_data)
                with py7zr.SevenZipFile(archive, mode='r', password=NAPI_PASSWORD) as z:
                    extracted = z.readall()
                    for filename, bio in extracted.items():
                        # Konwersja z Windows-1250 na UTF-8
                        return bio.read().decode('cp1250', errors='replace')
    except Exception as e:
        print(f"❌ Napi Error: {e}")
    return None
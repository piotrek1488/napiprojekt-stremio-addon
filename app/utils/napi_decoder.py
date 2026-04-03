import base64
import io
import py7zr
import httpx
import xml.etree.ElementTree as ET

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"

async def get_napi_subtitles_text(v_hash: str):
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"
    
    # Dane udające oficjalnego klienta NapiProjekt
    data = {
        "mode": "17",
        "client": "NapiProjekt",
        "client_ver": "2.2.0.2399",
        "downloaded_subtitles_id": v_hash,
        "downloaded_subtitles_lang": "PL",
        "the": "end"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data, timeout=10.0)
            if resp.status_code != 200:
                print(f"❌ Napi API Error: {resp.status_code}")
                return None
            
            # Parsowanie odpowiedzi XML
            root = ET.fromstring(resp.text)
            status_node = root.find("status")
            
            if status_node is not None and status_node.text == "success":
                content_node = root.find(".//content")
                if content_node is not None and content_node.text:
                    # Dekodowanie Base64 do bajtów
                    compressed_data = base64.b64decode(content_node.text)
                    
                    # Rozpakowanie 7zip z hasłem bezpośrednio w pamięci
                    archive = io.BytesIO(compressed_data)
                    with py7zr.SevenZipFile(archive, mode='r', password=NAPI_PASSWORD) as z:
                        extracted = z.readall()
                        # Napi zawsze wysyła jeden plik w paczce
                        for filename, bio in extracted.items():
                            # Używamy CP1250 (standard polskich napisów Windows)
                            return bio.read().decode('cp1250', errors='replace')
            else:
                print(f"🔍 Napi API: Brak napisów dla hasha {v_hash}")
    except Exception as e:
        print(f"❌ Błąd dekodowania Napi: {e}")
    return None
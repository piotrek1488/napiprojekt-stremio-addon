import base64
import io
import py7zr
import httpx
import xml.etree.ElementTree as ET

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"

# KLUCZOWA ZMIANA: Dodanie v_hash=None i title=None
async def get_napi_subtitles_text(v_hash: str = None, title: str = None):
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"
    
    # Decyzja: czy szukamy po hashu, czy po tytule
    if v_hash:
        data = {
            "mode": "1",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "downloaded_subtitles_id": v_hash,
            "downloaded_subtitles_lang": "PL",
            "the": "end"
        }
    elif title:
        data = {
            "mode": "3",
            "client": "NapiProjekt",
            "search_title": title,
            "downloaded_subtitles_lang": "PL",
            "the": "end"
        }
    else:
        return None

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data, timeout=10.0)
            if resp.status_code != 200:
                return None
            
            root = ET.fromstring(resp.text)
            status_node = root.find("status")
            
            if status_node is not None and status_node.text == "success":
                content_node = root.find(".//content")
                if content_node is not None and content_node.text:
                    compressed_data = base64.b64decode(content_node.text)
                    archive = io.BytesIO(compressed_data)
                    with py7zr.SevenZipFile(archive, mode='r', password=NAPI_PASSWORD) as z:
                        extracted = z.readall()
                        for filename, bio in extracted.items():
                            # Napiprojekt to standard Windows-1250 dla polskich znaków
                            return bio.read().decode('cp1250', errors='replace')
    except Exception as e:
        print(f"❌ Błąd w Napi Decoderze: {e}")
    return None
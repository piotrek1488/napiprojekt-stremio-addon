"""
NapiProjekt subtitle downloader — hash-based.

dl.php returns various formats:
  - 7z archive (most common)
  - Raw subtitle text (sometimes)
  - Gzip compressed text
  - "NPc0" = no subtitles
"""

import io, re, gzip, traceback
import httpx, py7zr

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"


def get_subhash(md5hash: str) -> str:
    idx = [0xe, 0x3, 0x6, 0x8, 0x2]
    mul = [2, 2, 5, 4, 3]
    add = [0, 0xd, 0x10, 0xb, 0x5]
    b = []
    for i in range(5):
        t = add[i] + int(md5hash[idx[i]], 16)
        v = int(md5hash[t:t + 2], 16)
        b.append(("%x" % (v * mul[i]))[-1])
    return ''.join(b)


def _extract_subtitle(data: bytes) -> str | None:
    """Try multiple formats to extract subtitle text from NapiProjekt response."""

    # 1. Check for "no subtitles" marker
    if data[:4] == b'NPc0':
        return None

    # 2. Try 7z archive
    if data[:2] == b'7z' or data[:6] == b'\x37\x7a\xbc\xaf\x27\x1c':
        try:
            archive = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
            extracted = archive.read(archive.getnames())
            archive.close()
            for name, bio in extracted.items():
                text = _decode_text(bio.read())
                if text: return _ensure_srt(text)
        except Exception as e:
            print(f"  ⚠️ 7z failed: {e}")

    # 3. Try gzip
    if data[:2] == b'\x1f\x8b':
        try:
            decompressed = gzip.decompress(data)
            text = _decode_text(decompressed)
            if text:
                print(f"  📦 Format: gzip ({len(decompressed)} bytes)")
                return _ensure_srt(text)
        except Exception as e:
            print(f"  ⚠️ gzip failed: {e}")

    # 4. Try raw text (various encodings)
    text = _decode_text(data)
    if text and _looks_like_subtitle(text):
        print(f"  📦 Format: raw text")
        return _ensure_srt(text)

    # 5. Try 7z with different detection (some 7z files don't have standard header)
    try:
        archive = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
        extracted = archive.read(archive.getnames())
        archive.close()
        for name, bio in extracted.items():
            text = _decode_text(bio.read())
            if text: return _ensure_srt(text)
    except:
        pass

    print(f"  ⚠️ Unknown format (first 20 bytes: {data[:20]})")
    return None


def _decode_text(raw: bytes) -> str | None:
    """Try multiple encodings to decode bytes to string."""
    # Check for UTF-16 BOM first
    if raw[:2] == b'\xff\xfe':
        try:
            return raw.decode('utf-16-le').lstrip('\ufeff')
        except: pass
    if raw[:2] == b'\xfe\xff':
        try:
            return raw.decode('utf-16-be').lstrip('\ufeff')
        except: pass
    # UTF-16 without BOM (null bytes pattern)
    if len(raw) > 4 and raw[1] == 0 and raw[3] == 0:
        try:
            return raw.decode('utf-16-le')
        except: pass

    for enc in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
        try:
            text = raw.decode(enc)
            if text.strip():
                return text
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _looks_like_subtitle(text: str) -> bool:
    """Check if text looks like subtitle content."""
    if re.search(r'\d{2}:\d{2}:\d{2}', text): return True
    if re.match(r'^\{\d+\}\{\d+\}', text): return True
    if re.match(r'^\[\d+\]\[\d+\]', text): return True
    if re.match(r'^\d{1,2}:\d{2}:\d{2}[=:]', text): return True
    lines = text.strip().split('\n')
    return len(lines) > 10


def _ensure_srt(text):
    text = text.strip()
    if re.match(r'^\d+\s*\r?\n\d{2}:\d{2}:\d{2}', text):
        return text
    if re.match(r'^\{\d+\}\{\d+\}', text):
        fps = _detect_microdvd_fps(text, r'\{(\d+)\}\{(\d+)\}')
        return _microdvd(text, r'\{(\d+)\}\{(\d+)\}(.+)', fps)
    if re.match(r'^\[\d+\]\[\d+\]', text):
        fps = _detect_microdvd_fps(text, r'\[(\d+)\]\[(\d+)\]')
        return _microdvd(text, r'\[(\d+)\]\[(\d+)\](.+)', fps)
    if re.match(r'^\d{1,2}:\d{2}:\d{2}[=:]', text):
        return _tmplayer(text)
    return text


def _detect_microdvd_fps(text: str, bracket_pattern: str) -> float:
    """
    MicroDVD files may have a header line {1}{1}23.976 or [1][1]25
    indicating the FPS. Detect it, otherwise default to 23.976.
    """
    first_line = text.strip().split('\n')[0].strip()
    m = re.match(bracket_pattern + r'([\d.]+)', first_line)
    if m:
        try:
            fps = float(m.group(3))
            if 10 < fps < 120:  # sanity check
                print(f"  🎞️ MicroDVD FPS z nagłówka: {fps}")
                return fps
        except ValueError:
            pass
    return 23.976  # default
    entries, c = [], 1
    for line in text.split('\n'):
        m = re.match(pattern, line.strip())
        if not m: continue
        s, e = int(m.group(1)), int(m.group(2))
        content = m.group(3).replace('|', '\n').replace('/', '\n').strip()
        entries.append(f"{c}\n{_f2t(s,fps)} --> {_f2t(e,fps)}\n{content}\n")
        c += 1
    return '\n'.join(entries)


def _microdvd(text, pattern, fps=23.976):
    # Skip FPS header line {1}{1}fps or [1][1]fps
    entries, c = [], 1
    for line in text.split('\n'):
        line = line.strip()
        m = re.match(pattern, line)
        if not m: continue
        s, e = int(m.group(1)), int(m.group(2))
        if s == 1 and e == 1:  # FPS header line
            continue
        content = m.group(3).replace('|', '\n').replace('/', '\n').strip()
        if not content: continue
        entries.append(f"{c}\n{_f2t(s,fps)} --> {_f2t(e,fps)}\n{content}\n")
        c += 1
    return '\n'.join(entries)


def _tmplayer(text):
    entries, c = [], 1
    for line in text.split('\n'):
        m = re.match(r'(\d{1,2}):(\d{2}):(\d{2})[=:](.+)', line.strip())
        if not m: continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        entries.append(f"{c}\n{h:02d}:{mi:02d}:{s:02d},000 --> {h:02d}:{mi:02d}:{min(s+2,59):02d},000\n{m.group(4).replace('|', chr(10))}\n")
        c += 1
    return '\n'.join(entries)


def _f2t(frame, fps):
    ms = int(frame / fps * 1000)
    return f"{ms//3600000:02d}:{(ms%3600000)//60000:02d}:{(ms%60000)//1000:02d},{ms%1000:03d}"


async def download_by_hash(napi_hash: str, language: str = "PL") -> str | None:
    """Download subtitles from NapiProjekt using MD5 hash."""
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid hash: '{napi_hash}'")
        return None

    print(f"🎯 Napi hash: {napi_hash}")
    subhash = get_subhash(napi_hash)
    params = {
        "v": "dreambox", "kolejka": "false", "nick": "", "pass": "",
        "napios": "Linux", "l": language.upper(), "f": napi_hash, "t": subhash,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(NAPI_DL_URL, params=params)
            print(f"📡 dl.php: status={resp.status_code} size={len(resp.content)}b")

            if resp.status_code != 200:
                print(f"⚠️ dl.php: HTTP {resp.status_code}")
                return None

            srt = _extract_subtitle(resp.content)
            if srt:
                print(f"✅ Napi: napisy pobrane! ({len(srt)} znaków)")
            else:
                print(f"ℹ️ Napi: brak napisów dla tego hasha")
            return srt

    except Exception as e:
        print(f"❌ dl.php error: {e}")
        traceback.print_exc()
        return None

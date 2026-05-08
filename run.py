import uvicorn
import os
import logging
import re
from dotenv import load_dotenv

load_dotenv()

MASK_PARAMS = ["rd_token", "os_api_key"]

def mask_url(url: str) -> str:
    for param in MASK_PARAMS:
        url = re.sub(
            rf'({param}=)([A-Za-z0-9_\-]{{4}})([A-Za-z0-9_\-]+)',
            lambda m: f"{m.group(1)}{m.group(2)}...",
            url
        )
    return url

class TokenMaskFilter(logging.Filter):
    def filter(self, record):
        # uvicorn access log args: (client_addr, method, path, http_version, status_code)
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = mask_url(str(args[2]))
            record.args = tuple(args)
        elif isinstance(record.args, tuple) and len(record.args) > 0:
            record.args = tuple(mask_url(str(a)) if isinstance(a, str) else a for a in record.args)
        return True

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8081))
    base_url = os.getenv("BASE_URL", "").strip().rstrip("/")
    dev_mode = os.getenv("DEV", "false").lower() == "true"

    manifest_url = f"{base_url}/manifest.json" if base_url else f"http://127.0.0.1:{port}/manifest.json"
    home_url = f"{base_url}/" if base_url else f"http://127.0.0.1:{port}/"

    print(f"🚀 Serwer startuje na porcie: {port}")
    print(f"🔗 Link do manifestu: {manifest_url}")
    print(f"🏠 Strona główna: {home_url}")
    print(f"🔧 Tryb: {'development (reload)' if dev_mode else 'production'}")

    _filter = TokenMaskFilter()
    for name in ("uvicorn.access", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addFilter(_filter)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=dev_mode,          # reload tylko w dev
        workers=1 if dev_mode else 2,  # multi-worker w produkcji
        log_level="info",
    )
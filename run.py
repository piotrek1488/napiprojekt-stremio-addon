import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7000))
    # Jeśli nie ma BASE_URL w .env, domyślnie używamy localhost
    base_url = os.getenv("BASE_URL", "127.0.0.1")
    
    print(f"🚀 Serwer startuje na porcie: {port}")
    print(f"🔗 Link do manifestu: http://{base_url}:{port}/manifest.json")
    print(f"🏠 Strona główna: http://{base_url}:{port}/")
    
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
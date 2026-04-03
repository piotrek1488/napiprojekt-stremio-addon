import asyncio
import logging

async def with_retry(func, *args, retries=3, delay=1.0, **kwargs):
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == retries - 1:
                logging.error(f"Wszystkie próby zakończone błędem: {e}")
                raise e
            logging.warning(f"Błąd: {e}. Ponawiam... (pozostało {retries - attempt - 1} prób)")
            await asyncio.sleep(delay * (2 ** attempt)) # Exponential backoff
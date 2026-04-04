from cachetools import TTLCache

# Przechowuje do 1000 wyników przez 3600 sekund (1 godzina)
subtitle_cache = TTLCache(maxsize=1000, ttl=3600)
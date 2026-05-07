from thefuzz import fuzz

def score_subtitles(subtitles: list, target_release: str) -> list:
    if not target_release or not subtitles:
        return subtitles
    
    for sub in subtitles:
        score = 0
        # 1. Podobieństwo nazwy releasu (0-100 pkt)
        if sub.get("releaseName"):
            score += fuzz.ratio(target_release.lower(), sub["releaseName"].lower())
            
        # 2. Preferowane źródło NapiProjekt (dodatkowe 20 pkt)
        if sub.get("source") == "NapiProjekt":
            score += 20
            
        sub["score"] = score
        
    # Sortujemy malejąco
    return sorted(subtitles, key=lambda x: x.get("score", 0), reverse=True)
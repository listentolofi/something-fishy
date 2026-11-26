import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Free public news RSS feeds across your updated Topics
RSS_FEEDS = [
    ("POLITICS", "GLOBAL / ORBITAL", "https://feeds.bbci.co.uk/news/politics/rss.xml"),
    ("POLITICS", "GLOBAL / ORBITAL", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BUSINESS & FINANCE", "GLOBAL / ORBITAL", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("HEALTH & SCIENCE", "GLOBAL / ORBITAL", "https://www.sciencedaily.com/rss/all.xml"),
    ("HISTORY & ARCHAEOLOGY", "GLOBAL / ORBITAL", "https://www.sciencedaily.com/rss/fossils_ruins/archaeology.xml"),
    ("SPORTS", "GLOBAL / ORBITAL", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("TECHNOLOGY", "GLOBAL / ORBITAL", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
]

GEMINI_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash-latest",
    "gemini-flash-latest",
    "gemini-2.5-pro",
]

def extract_media_url(item):
    # Safely extract publisher-provided RSS thumbnail/enclosure if present
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("thumbnail") or tag.endswith("content") or tag.endswith("enclosure"):
            url = elem.attrib.get("url", "").strip()
            media_type = elem.attrib.get("type", "").lower()
            if url and (media_type.startswith("image/") or re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", url, re.I)):
                return url
    return None

def fetch_headlines(limit_per_feed=3):
    collected = []
    headers = {"User-Agent": "Mozilla/5.0 (SomethingFishyBot/1.0)"}
    for category, region, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")[:limit_per_feed]
            for item in items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or url).strip()
                desc = re.sub(r"<[^>]+>", "", (item.findtext("description") or "")).strip()
                media_url = extract_media_url(item)
                if title:
                    collected.append({
                        "category": category,
                        "region": region,
                        "title": title,
                        "link": link,
                        "mediaUrl": media_url,
                        "summary": desc[:300]
                    })
        except Exception as e:
            print(f"Skipped {url}: {e}")
    return collected

def generate_fishy_dossiers(headlines):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    today_str = datetime.now(timezone.utc).strftime("%b %d, %Y").upper()

    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in GitHub Secrets.")

    prompt = f"""
You are the senior investigative editor for 'SOMETHING FISHY'.
Review these real headlines from today ({today_str}) and select the 8 most intriguing, coincidental, or paradigm-challenging stories across Politics, Business & Finance, Sports, Health & Science, History & Archaeology, and Technology.

Return ONLY a valid JSON array (no markdown fences) where each object has:
- "id": unique string like "auto-1"
- "date": "{today_str}"
- "region": one of ["ASIA-PACIFIC", "MIDDLE EAST & AFRICA", "EUROPE", "AMERICAS", "GLOBAL / ORBITAL"]
- "location": uppercase city/sector string
- "subject": one of ["POLITICS", "BUSINESS & FINANCE", "SPORTS", "HEALTH & SCIENCE", "HISTORY & ARCHAEOLOGY", "TECHNOLOGY", "EARTH & ENVIRONMENT", "WORLD & ARCHIVES"]
- "coincidenceLevel": integer between 65 and 96
- "breakdown": {{"deviation": int, "timing": int, "multiSource": int, "opacity": int}}
- "evidenceGrade": one of ["Regulatory / Market Data", "Peer-Reviewed DOI", "Declassified Gov File", "Telemetry / Sensor Log"]
- "citationSource": publisher or institution name + today's date
- "sourceUrl": exact link from the input item
- "mediaType": "image"
- "mediaUrl": exact mediaUrl from input item if non-null, otherwise null
- "mediaCredit": publisher attribution string if mediaUrl is present, otherwise null
- "headline": punchy, non-clickbait investigative headline
- "plainEnglish": 1-2 simple everyday sentences explaining why a regular person should care (zero jargon)
- "publicRecord": 2-3 factual sentences summarizing the verified mainstream report (The Press Release)
- "altHypothesis": 1-2 punchy sentences spelling out the real motive, who profits, or what clashes with the story (Why It's Fishy? — do NOT start with the literal words "So what?")

HEADLINES:
{json.dumps(headlines, indent=2)}
"""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}
    }).encode("utf-8")

    result = None
    last_error = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            print(f"Connected using model: {model}")
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            print(f"Model {model} returned HTTP {e.code}: {err_body}")
            last_error = e
            if e.code == 404:
                continue
            raise

    if result is None:
        raise last_error or RuntimeError("All Gemini models returned 404.")

    raw_text = result["candidates"][0]["content"]["parts"][0]["text"]
    items = json.loads(raw_text)

    output = {
        "updatedAt": datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC"),
        "items": items
    }

    with open("daily_feed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Successfully updated daily_feed.json with {len(items)} dossiers.")

if __name__ == "__main__":
    raw_headlines = fetch_headlines(limit_per_feed=3)
    if raw_headlines:
        generate_fishy_dossiers(raw_headlines)

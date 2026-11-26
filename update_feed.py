import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Free public news RSS feeds across your Topics
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
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("thumbnail") or tag.endswith("content") or tag.endswith("enclosure"):
            url = elem.attrib.get("url", "").strip()
            media_type = elem.attrib.get("type", "").lower()
            if url and (media_type.startswith("image/") or re.search(r"\.(jpg|jpeg|png|webp)(\?.*)?$", url, re.I)):
                return url
    return None

def load_existing_items():
    if not os.path.exists("daily_feed.json"):
        return []
    try:
        with open("daily_feed.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        return []

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

    existing_items = load_existing_items()
    existing_urls = {item.get("sourceUrl", "").strip() for item in existing_items if item.get("sourceUrl")}

    # Filter out headlines already published in earlier runs today
    fresh_headlines = [h for h in headlines if h["link"].strip() not in existing_urls]
    if not fresh_headlines:
        fresh_headlines = headlines

    prompt = f"""
You are the senior investigative editor for 'SOMETHING FISHY'.
Review these real headlines from today ({today_str}) and select the 6 most intriguing, coincidental, or paradigm-challenging stories across Politics, Business & Finance, Sports, Health & Science, History & Archaeology, and Technology.

Return ONLY a valid JSON array (no markdown fences) where each object has:
- "id": unique string
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
{json.dumps(fresh_headlines, indent=2)}
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
    new_items = json.loads(raw_text)

    # Give each item a deterministic unique ID based on its source URL so merging never collides
    for idx, item in enumerate(new_items):
        digest = hashlib.sha1((item.get("sourceUrl", "") + item.get("headline", "")).encode("utf-8")).hexdigest()[:10]
        item["id"] = f"auto-{digest}-{idx}"

    # Merge new stories on top of existing stories (deduplicated by sourceUrl, capped at 24 newest)
    merged = []
    seen_urls = set()
    for item in new_items + existing_items:
        src = (item.get("sourceUrl") or item.get("headline") or "").strip()
        if src and src in seen_urls:
            continue
        if src:
            seen_urls.add(src)
        merged.append(item)

    merged = merged[:24]

    output = {
        "updatedAt": datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC"),
        "items": merged
    }

    with open("daily_feed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Successfully updated daily_feed.json ({len(new_items)} new, {len(merged)} total stored).")

if __name__ == "__main__":
    raw_headlines = fetch_headlines(limit_per_feed=3)
    if raw_headlines:
        generate_fishy_dossiers(raw_headlines)

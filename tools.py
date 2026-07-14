import random
import asyncio
import aiohttp
from io import BytesIO, StringIO

file_sessions = {}
merge_sessions = {}


async def bin_lookup(bin_prefix):
    bin_prefix = bin_prefix.strip()[:6]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://lookup.binlist.net/{bin_prefix}",
                headers={"Accept-Version": "3"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        scheme = data.get("scheme", "N/A").upper()
        brand = data.get("brand", "N/A")
        ctype = data.get("type", "N/A").upper()
        country = data.get("country", {})
        bank = data.get("bank", {})
        country_name = country.get("name", "N/A")
        country_emoji = country.get("emoji", "")
        country_code = country.get("alpha2", "N/A")
        currency = country.get("currency", "N/A")
        bank_name = bank.get("name", "N/A")
        bank_phone = bank.get("phone", "N/A")
        bank_url = bank.get("url", "N/A")

        return {
            "bin": bin_prefix,
            "brand": f"{scheme} - {brand}",
            "type": ctype,
            "country": f"{country_name} {country_emoji}",
            "country_code": country_code,
            "currency": currency,
            "bank": bank_name,
            "bank_phone": bank_phone,
            "bank_url": bank_url,
        }
    except Exception:
        return None


def format_bin_result(info):
    return (
        f"<b>🔍 BIN:</b> <code>{info['bin']}</code>\n"
        f"<b>🏷 Brand:</b> {info['brand']}\n"
        f"<b>💳 Type:</b> {info['type']}\n"
        f"<b>🌍 Country:</b> {info['country']}\n"
        f"<b>💱 Currency:</b> {info['currency']}\n"
        f"<b>🏦 Bank:</b> {info['bank']}"
    )


def generate_cards(template, count):
    cards = []
    for _ in range(count):
        card = ""
        for ch in template:
            if ch.lower() == "x":
                card += str(random.randint(0, 9))
            else:
                card += ch
        cards.append(card)
    return cards


async def get_fake_identity(country_code="us"):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://randomuser.me/api/?nat={country_code}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

        user = data["results"][0]
        name = user["name"]
        location = user["location"]
        street = location["street"]
        fullname = f"{name['title']} {name['first']} {name['last']}"
        address = f"{street['number']} {street['name']}, {location['city']}, {location['state']}, {location['country']} {location['postcode']}"
        dob = user["dob"]["date"][:10]
        return {
            "name": fullname,
            "gender": user["gender"].upper(),
            "dob": dob,
            "age": user["dob"]["age"],
            "email": user["email"],
            "phone": user["phone"],
            "cell": user["cell"],
            "address": address,
            "city": location["city"],
            "state": location["state"],
            "country": location["country"],
            "postcode": location["postcode"],
            "nat": user["nat"],
            "ssn": user.get("id", {}).get("value", "N/A") if user.get("id", {}).get("name") == "SSN" else "N/A",
        }
    except Exception as e:
        return None


def format_fake(info):
    return (
        f"<b>🎭 FAKE IDENTITY</b>\n\n"
        f"<b>👤 Name:</b> {info['name']}\n"
        f"<b>⚤ Gender:</b> {info['gender']}\n"
        f"<b>🎂 DOB:</b> {info['dob']} (Age: {info['age']})\n"
        f"<b>📧 Email:</b> <code>{info['email']}</code>\n"
        f"<b>📞 Phone:</b> {info['phone']}\n"
        f"<b>📱 Cell:</b> {info['cell']}\n"
        f"<b>🆔 SSN:</b> {info['ssn']}\n"
        f"<b>📍 Address:</b> {info['address']}\n"
        f"<b>🌍 Country:</b> {info['country']} ({info['nat']})"
    )


async def check_proxy(proxy_str, timeout=8):
    parts = proxy_str.strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
    elif len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
    else:
        return {"proxy": proxy_str, "status": "INVALID", "ip": "N/A", "country": "N/A", "type": "N/A"}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get("http://ip-api.com/json/?fields=country,query", proxy=proxy_url) as resp:
                data = await resp.json()
                ip1 = data.get("query", "N/A")
                country1 = data.get("country", "N/A")
    except Exception:
        return {"proxy": proxy_str, "status": "DEAD", "ip": "N/A", "country": "N/A", "type": "N/A"}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get("http://ip-api.com/json/?fields=country,query", proxy=proxy_url) as resp:
                data = await resp.json()
                ip2 = data.get("query", "N/A")
    except Exception:
        ip2 = ip1

    proxy_type = "ROTATING" if ip1 != ip2 else "STATIC"

    return {
        "proxy": proxy_str.split(":")[0] + ":" + proxy_str.split(":")[1],
        "status": "LIVE",
        "ip": ip1,
        "country": country1,
        "type": proxy_type,
    }


def format_proxy(p):
    if p["status"] == "DEAD":
        return f"<b>❌ {p['proxy']}</b> - DEAD"
    elif p["status"] == "INVALID":
        return f"<b>⚠️ {p['proxy']}</b> - INVALID FORMAT"
    emoji = "🔄" if p["type"] == "ROTATING" else "📌"
    return (
        f"<b>✅ {p['proxy']}</b>\n"
        f"   ┣ <b>IP:</b> {p['ip']}\n"
        f"   ┣ <b>Country:</b> {p['country']}\n"
        f"   ┗ <b>Type:</b> {p['type']} {emoji}"
    )


def clean_cards(content):
    lines = content.strip().split("\n")
    seen = set()
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 4:
                normalized = f"{parts[0].strip()}|{parts[1].strip()}|{parts[2].strip()}|{parts[3].strip()}"
                if normalized not in seen:
                    seen.add(normalized)
                    cleaned.append(normalized)
            else:
                if line not in seen:
                    seen.add(line)
                    cleaned.append(line)
        else:
            if line not in seen:
                seen.add(line)
                cleaned.append(line)
    return "\n".join(cleaned)


def shuffle_cards(content):
    lines = [l for l in content.strip().split("\n") if l.strip()]
    random.shuffle(lines)
    return "\n".join(lines)


def split_cards(content, parts):
    lines = [l for l in content.strip().split("\n") if l.strip()]
    random.shuffle(lines)
    chunk_size = max(1, len(lines) // parts)
    chunks = []
    for i in range(parts):
        start = i * chunk_size
        end = start + chunk_size if i < parts - 1 else len(lines)
        chunks.append("\n".join(lines[start:end]))
    return chunks


def filter_cards(content, prefix):
    lines = content.strip().split("\n")
    filtered = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            cc = line.split("|")[0].strip()
        else:
            cc = line
        if cc.startswith(prefix):
            filtered.append(line)
    return filtered


def extract_text(text):
    return text.strip()

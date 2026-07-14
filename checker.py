import asyncio
import aiohttp
import re
import json
import time
from Crypto.Cipher import AES
from config import API_URL, MAX_THREADS

user_semaphores = {}
bin_semaphore = asyncio.Semaphore(2)
bin_cache = {}
active_checks = {}


def get_user_semaphore(user_id):
    if user_id not in user_semaphores:
        user_semaphores[user_id] = asyncio.Semaphore(MAX_THREADS)
    return user_semaphores[user_id]


def cleanup_user_semaphore(user_id):
    user_semaphores.pop(user_id, None)


def bold_text(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘷𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    return text.translate(str.maketrans(normal, bold))


def mono_text(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    mono = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"
    return text.translate(str.maketrans(normal, mono))


def format_card(cc):
    parts = cc.split("|")
    if len(parts) >= 4:
        return f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
    return cc.strip()


def solve_js_challenge(html):
    keys = re.findall(r'toNumbers\(\"([a-f0-9]+)\"\)', html)
    if len(keys) < 3:
        return None
    a, b, c = keys[0], keys[1], keys[2]
    key = bytes.fromhex(a)
    iv = bytes.fromhex(b)
    ct = bytes.fromhex(c)
    ecb = AES.new(key, AES.MODE_ECB)
    h = ecb.decrypt(ct)
    pt = bytes(x ^ y for x, y in zip(h, iv))
    pad_byte = pt[-1]
    if 1 <= pad_byte <= 16:
        valid = all(x == pad_byte for x in pt[-pad_byte:])
        if valid:
            pt = pt[:-pad_byte]
    return pt.hex()


async def fetch_bin_info(bin_prefix):
    if bin_prefix in bin_cache:
        return bin_cache[bin_prefix]

    async with bin_semaphore:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"https://data.handyapi.com/bin/{bin_prefix}",
                    timeout=aiohttp.ClientTimeout(total=8),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            bin_cache[bin_prefix] = None
            if data.get("Status") != "SUCCESS":
                return None

            scheme = data.get("Scheme", "").upper()
            ctype = data.get("Type", "").upper()
            country = data.get("Country", {})
            issuer = data.get("Issuer", "-")

            flag_map = {
                "US": "🇺🇸", "GB": "🇬🇧", "CA": "🇨🇦", "AU": "🇦🇺", "DE": "🇩🇪",
                "FR": "🇫🇷", "IN": "🇮🇳", "BR": "🇧🇷", "JP": "🇯🇵", "CN": "🇨🇳",
                "BE": "🇧🇪", "NL": "🇳🇱", "IT": "🇮🇹", "ES": "🇪🇸", "MX": "🇲🇽",
                "RU": "🇷🇺", "KR": "🇰🇷", "SE": "🇸🇪", "CH": "🇨🇭", "NO": "🇳🇴",
            }
            country_name = country.get("Name", "N/A")
            country_code = country.get("A2", "")
            emoji = flag_map.get(country_code, "")

            result = {
                "brand": f"{scheme} - {ctype}",
                "type": ctype or "N/A",
                "country": country_name,
                "country_emoji": emoji,
                "bank": issuer,
            }
            bin_cache[bin_prefix] = result
            return result
        except Exception:
            bin_cache[bin_prefix] = None
            return None


async def check_card(session, cc, user_id=None, cancel_event=None):
    us = get_user_semaphore(user_id) if user_id else asyncio.Semaphore(MAX_THREADS)
    async with us:
        if cancel_event and cancel_event.is_set():
            return {"cc": cc, "status": "CANCELLED", "response": "Cancelled", "gateway": "N/A", "bin": "N/A", "bank": "-", "country": "N/A", "time": 0, "raw": ""}

        url = f"{API_URL}{cc}"
        t_start = time.time()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=45), ssl=False) as resp:
                text = await resp.text()

            if cancel_event and cancel_event.is_set():
                return {"cc": cc, "status": "CANCELLED", "response": "Cancelled", "gateway": "N/A", "bin": "N/A", "bank": "-", "country": "N/A", "time": 0, "raw": ""}

            if "toNumbers" in text and "slowAES" in text:
                cookie_val = solve_js_challenge(text)
                if cookie_val:
                    async with session.get(
                        f"{url}&i=1",
                        headers={"Cookie": f"__test={cookie_val}"},
                        timeout=aiohttp.ClientTimeout(total=45),
                        ssl=False,
                    ) as resp2:
                        text = await resp2.text()

            elapsed = round(time.time() - t_start, 1)

            try:
                data = json.loads(text)
            except Exception:
                data = {}

            outcome = data.get("outcome", "").lower()
            response_text = data.get("response", "N/A")
            gateway = data.get("gateway", "N/A")

            resp_lower = response_text.lower()
            if outcome in ("succeeded", "success", "approved", "live") or resp_lower in ("payment successful", "card added successfully", "approved"):
                status = "APPROVED"
            elif outcome in ("declined", "failed", "decline", "dead", "do not honor") or "declined" in resp_lower:
                status = "DECLINED"
            elif "incorrect" in outcome or "cvc" in outcome or "cvv" in outcome:
                status = "CCN"
            elif "insufficient" in outcome:
                status = "INSUFFICIENT"
            elif "stolen" in outcome or "pickup" in outcome:
                status = "STOLEN"
            else:
                status = "UNKNOWN"

            if status == "UNKNOWN" and response_text == "N/A":
                status = "ERROR"

            bin_info = "N/A"
            bank = "-"
            country = "N/A"

            cc_parts = cc.split("|")
            if cc_parts and len(cc_parts[0]) >= 6:
                bin_data = await fetch_bin_info(cc_parts[0][:6])
                if bin_data:
                    bin_info = bin_data["brand"]
                    bank = bin_data["bank"]
                    country = f"{bin_data['country']} {bin_data['country_emoji']}"

            return {
                "cc": cc,
                "status": status,
                "response": response_text,
                "gateway": gateway,
                "bin": bin_info,
                "bank": bank,
                "country": country,
                "time": elapsed,
                "raw": text,
            }
        except asyncio.CancelledError:
            return {"cc": cc, "status": "CANCELLED", "response": "Cancelled", "gateway": "N/A", "bin": "N/A", "bank": "-", "country": "N/A", "time": 0, "raw": ""}
        except Exception as e:
            return {"cc": cc, "status": "ERROR", "response": str(e)[:100], "gateway": "N/A", "bin": "N/A", "bank": "-", "country": "N/A", "time": 0, "raw": ""}


def format_card_response(r, username="User"):
    cc = r["cc"]
    status = r["status"]
    response = r["response"]
    gateway = r["gateway"]
    bin_info = r["bin"]
    bank = r["bank"]
    country = r["country"]
    elapsed = r.get("time", 0)

    if status == "APPROVED":
        status_str = f"{mono_text('Approved!')} ✅"
    elif status == "LIVE":
        status_str = f"{mono_text('Live!')} 🟢"
    elif status == "DECLINED":
        status_str = f"{mono_text('Dead!')} ❌"
    elif status == "CCN":
        status_str = f"{mono_text('CCN!')} ⚠️"
    else:
        status_str = f"{mono_text(status)}"

    out = f"✿ <b>BILLI</b> ✿\n"
    out += "- - - - - - - - - - - - - - - - - - - - - - - -\n"
    out += f"[⌯] {bold_text('Card')} ⌁ <code>{cc}</code>\n"
    out += f"[⌯] {bold_text('Status')} ⌁ {status_str}\n"
    out += f"[⌯] {bold_text('Result')} ⌁ {mono_text(response)}\n\n"
    out += f"[⌯] {bold_text('Bin')} ⌁ {mono_text(bin_info)}\n"
    out += f"[⌯] {bold_text('Bank')} ⌁ {mono_text(bank)}\n"
    out += f"[⌯] {bold_text('Country')} ⌁ {country}\n\n"
    out += f"[⌯] {bold_text('Gate')} ⌁ {gateway}\n"
    out += f"[⌯] {bold_text('Time')} ⌁ {elapsed}s\n"
    out += f"[⌯] {bold_text('Used By')} ⌁ {username}\n"
    out += "- - - - - - - - - - - - - - - - - - - - - - - -"
    return out


async def single_check(cc, user_id=None):
    async with aiohttp.ClientSession() as session:
        result = await check_card(session, format_card(cc), user_id=user_id)
        return result


async def mass_check_with_progress(cards, user_id, progress_callback=None):
    cancel_event = asyncio.Event()
    stats = {"done": 0, "live": 0, "dead": 0, "ccn": 0, "error": 0, "total": len(cards)}
    active_checks[user_id] = {"cancel": cancel_event, "stats": stats}

    results_list = []
    cards = [format_card(c.strip()) for c in cards if c.strip()]
    idx = 0
    pending = set()
    retried = set()

    async with aiohttp.ClientSession() as session:

        def spawn_task(cc):
            task = asyncio.create_task(check_card(session, cc, user_id=user_id, cancel_event=cancel_event))
            task._cc = cc
            pending.add(task)

        def handle_result(result):
            results_list.append(result)
            stats["done"] += 1
            is_retry = result["cc"] in retried
            if result["status"] in ("APPROVED", "LIVE"):
                stats["live"] += 1
                if is_retry:
                    stats["error"] = max(0, stats["error"] - 1)
            elif result["status"] == "CCN":
                stats["ccn"] += 1
                if is_retry:
                    stats["error"] = max(0, stats["error"] - 1)
            elif result["status"] == "ERROR":
                if not is_retry and not cancel_event.is_set():
                    retried.add(result["cc"])
                    spawn_task(result["cc"])
                stats["error"] += 1
            elif result["status"] not in ("CANCELLED",):
                stats["dead"] += 1
                if is_retry:
                    stats["error"] = max(0, stats["error"] - 1)

        while (idx < len(cards) or pending) and not cancel_event.is_set():
            while len(pending) < MAX_THREADS and idx < len(cards) and not cancel_event.is_set():
                spawn_task(cards[idx])
                idx += 1

            if not pending:
                break

            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED, timeout=1.0)

            for t in done:
                try:
                    result = t.result()
                except (Exception, asyncio.CancelledError):
                    result = {"cc": getattr(t, "_cc", "?"), "status": "ERROR", "response": "Task failed", "gateway": "N/A", "bin": "N/A", "bank": "-", "country": "N/A", "time": 0, "raw": ""}

                handle_result(result)
                if progress_callback:
                    await progress_callback(result, stats)

        if cancel_event.is_set():
            for t in pending:
                t.cancel()

    active_checks.pop(user_id, None)
    cleanup_user_semaphore(user_id)
    return results_list, stats


def stop_check(user_id):
    if user_id in active_checks:
        active_checks[user_id]["cancel"].set()
        return True
    return False

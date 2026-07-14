import asyncio
import sys
import os
import time
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checker import single_check, mass_check_with_progress, stop_check, format_card_response
from tools import bin_lookup


BANNER = r"""
  ╔═══╗╔═══╗╔════╗
  ║╔═╗║║╔══╝║╔╗╔╗║
  ║╚═╝║║╚══╗╚╝║║╚╝
  ║╔╗╔╝║╔══╝  ║║
  ║║║╚╗║╚══╗  ║║
  ╚╝╚═╝╚═══╝  ╚╝
  ================
  XVV GATE v2
"""


def separator(title=""):
    w = 50
    if title:
        side = (w - len(title) - 2) // 2
        return f"\n{'=' * side} {title} {'=' * (w - side - len(title) - 2)}"
    return "=" * w


def heading(text):
    w = 50
    return f"\n{'=' * w}\n  {text}\n{'=' * w}"


def print_result(r, username="CLI"):
    cc = r["cc"]
    status = r["status"]
    response = r["response"]
    gateway = r["gateway"]
    bin_info = r["bin"]
    bank = r["bank"]
    country = r["country"]
    elapsed = r.get("time", 0)

    status_icon = {"APPROVED": "LIVE", "LIVE": "LIVE", "DECLINED": "DEAD", "CCN": "CCN"}.get(status, "?")
    icon = {"APPROVED": "✅", "LIVE": "🟢", "DECLINED": "❌", "CCN": "⚠️"}.get(status, "❓")

    out = f"\n{'=' * 50}\n"
    out += f"  CARD    : {cc}\n"
    out += f"  STATUS  : {status_icon} {icon}\n"
    out += f"  RESPONSE: {response}\n"
    out += f"  BIN     : {bin_info}\n"
    out += f"  BANK    : {bank}\n"
    out += f"  COUNTRY : {country}\n"
    out += f"  GATEWAY : {gateway}\n"
    out += f"  TIME    : {elapsed}s\n"
    out += f"{'=' * 50}"
    print(out)


def format_bin_plain(info):
    return (
        f"  BIN      : {info['bin']}\n"
        f"  BRAND    : {info['brand']}\n"
        f"  TYPE     : {info['type']}\n"
        f"  COUNTRY  : {info['country']}\n"
        f"  CURRENCY : {info['currency']}\n"
        f"  BANK     : {info['bank']}"
    )


# ── /xvv : Single Card Check ────────────────────────────────────────────────

async def cmd_xvv(args):
    if not args:
        print("Usage: /xvv <cc>|<mm>|<yy>|<cvv>")
        return
    cc = " ".join(args)
    print(f"\n[*] Checking: {cc}")
    result = await single_check(cc)
    print_result(result)


# ── /mxvv : Mass Card Check ─────────────────────────────────────────────────

async def cmd_mxvv(args):
    if not args:
        print("Usage: /mxvv <filepath>")
        return
    filepath = args[0]
    if not os.path.isfile(filepath):
        print(f"[-] File not found: {filepath}")
        return

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    cards = [line.strip() for line in content.strip().split("\n") if line.strip() and "|" in line]
    total = len(cards)
    if total == 0:
        print("[-] No valid cards found in file.")
        return

    print(f"\n[*] Loaded {total} cards from {filepath}")
    print("[*] Starting mass check... (Ctrl+C to stop)\n")

    uid = int(time.time())
    last_update = 0
    all_results = []

    async def on_progress(result, stats):
        nonlocal last_update
        done = stats["done"]
        live = stats["live"]
        dead = stats["dead"]
        ccn = stats["ccn"]
        error = stats.get("error", 0)
        all_results.append(result)

        if result["status"] in ("APPROVED", "LIVE"):
            print_result(result)

        if done - last_update >= 3 or done >= total:
            last_update = done
            sys.stdout.write(
                f"\r  Progress: {done}/{total} | Live: {live} | Dead: {dead} | CCN: {ccn} | Err: {error}   "
            )
            sys.stdout.flush()

    try:
        results, final_stats = await mass_check_with_progress(cards, uid, on_progress)
    except KeyboardInterrupt:
        stop_check(uid)
        print("\n\n[!] Stopped by user.")
        return

    print()
    approved = [r for r in all_results if r["status"] in ("APPROVED", "LIVE")]
    ccn_list = [r for r in all_results if r["status"] == "CCN"]
    declined = [r for r in all_results if r["status"] not in ("APPROVED", "LIVE", "CCN", "CANCELLED", "ERROR")]

    print(separator("FINAL RESULTS"))
    print(f"  Total   : {total}")
    print(f"  Checked : {final_stats['done']}")
    print(f"  Live    : {final_stats['live']}")
    print(f"  Dead    : {final_stats['dead']}")
    print(f"  CCN     : {final_stats['ccn']}")
    print(f"  Errors  : {final_stats.get('error', 0)}")
    print(separator())

    stamp = datetime.now().strftime('%H%M%S')
    out_file = f"xvv_result_{stamp}.txt"
    lines = []
    if approved:
        lines.append("=== APPROVED / LIVE ===")
        for r in approved:
            lines.append(f"{r['cc']} | {r['response']} | {r['gateway']} | {r['bin']} | {r['bank']} | {r['country']}")
    if ccn_list:
        lines.append("\n=== CCN ===")
        for r in ccn_list:
            lines.append(f"{r['cc']} | {r['response']} | {r['gateway']}")
    if declined:
        lines.append("\n=== DECLINED ===")
        for r in declined:
            lines.append(f"{r['cc']} | {r['response']} | {r['gateway']}")

    if lines:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n[*] Results saved to: {out_file}")


# ── /bin : BIN Lookup ───────────────────────────────────────────────────────

async def cmd_bin(args):
    if not args:
        print("Usage: /bin <bin_prefix>")
        return
    prefix = args[0][:6]
    print(f"\n[*] Looking up BIN: {prefix}")
    info = await bin_lookup(prefix)
    if info:
        print(separator("BIN RESULT"))
        print(format_bin_plain(info))
        print(separator())
    else:
        print(f"[-] BIN {prefix} not found.")


# ── /clean : Extract & Clean Cards from Messy File ─────────────────────────

async def cmd_clean(args):
    if not args:
        print("Usage: /clean <filepath>")
        return
    filepath = args[0]
    if not os.path.isfile(filepath):
        print(f"[-] File not found: {filepath}")
        return

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"\n[*] Reading: {filepath} ({size_mb:.1f} MB)")

    def extract_pan(text):
        digits = ""
        for ch in text:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        return digits

    seen = set()
    cleaned = []
    total_lines = 0
    cards_found = 0
    duplicates = 0

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            total_lines += 1
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                pan = extract_pan(parts[0])
                if not pan or len(pan) < 6:
                    continue
                month = extract_pan(parts[1])
                year = extract_pan(parts[2])
                cvv = extract_pan(parts[3])
                if not month or not year or not cvv:
                    continue
                normalized = f"{pan}|{month}|{year}|{cvv}"
                if normalized not in seen:
                    seen.add(normalized)
                    cleaned.append(normalized)
                    cards_found += 1
                else:
                    duplicates += 1

    print(f"  Total lines read   : {total_lines}")
    print(f"  Valid cards found  : {cards_found}")
    print(f"  Duplicates removed : {duplicates}")

    if not cleaned:
        print("[-] No valid cards found.")
        return

    stamp = datetime.now().strftime('%H%M%S')
    out_file = f"cleaned_{stamp}.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned))

    print(f"\n[+] Saved {cards_found} cards to: {out_file}")


# ── /split : Split File into N Parts ───────────────────────────────────────

async def cmd_split(args):
    if len(args) < 2:
        print("Usage: /split <N> <filepath>")
        return
    try:
        parts = int(args[0])
    except ValueError:
        print("[-] N must be a number.")
        return
    filepath = args[1]
    if not os.path.isfile(filepath):
        print(f"[-] File not found: {filepath}")
        return

    parts = max(1, min(parts, 100))
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"\n[*] Reading: {filepath} ({size_mb:.1f} MB)")
    print(f"[*] Splitting into {parts} parts...")

    cards = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and "|" in line:
                cards.append(line)

    total = len(cards)
    if total == 0:
        print("[-] No valid cards found.")
        return

    random.shuffle(cards)
    chunk_size = (total + parts - 1) // parts
    stamp = datetime.now().strftime('%H%M%S')

    for i in range(parts):
        start = i * chunk_size
        end = start + chunk_size if i < parts - 1 else total
        chunk = cards[start:end]
        name = f"split_{stamp}_{i+1}of{parts}.txt"
        with open(name, "w", encoding="utf-8") as f:
            f.write("\n".join(chunk))
        print(f"  [{i+1}/{parts}] {name} -> {len(chunk)} cards")

    print(f"\n[+] Split {total} cards into {parts} files.")


# ── /sort : Filter Cards by BIN ────────────────────────────────────────────

async def cmd_sort(args):
    if len(args) < 2:
        print("Usage: /sort <bin_prefix> <filepath>")
        return
    prefix = args[0]
    filepath = args[1]
    if not os.path.isfile(filepath):
        print(f"[-] File not found: {filepath}")
        return

    def extract_pan(text):
        digits = ""
        for ch in text:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        return digits

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"\n[*] Reading: {filepath} ({size_mb:.1f} MB)")
    print(f"[*] Filtering BIN: {prefix}")

    matched = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or "|" not in line:
                continue
            pan = extract_pan(line.split("|")[0])
            if pan and pan.startswith(prefix):
                parts = [p.strip() for p in line.split("|")]
                month = extract_pan(parts[1]) if len(parts) > 1 else ""
                year = extract_pan(parts[2]) if len(parts) > 2 else ""
                cvv = extract_pan(parts[3]) if len(parts) > 3 else ""
                if month and year and cvv:
                    matched.append(f"{pan}|{month}|{year}|{cvv}")
                else:
                    matched.append(pan)

    total_found = len(matched)
    if total_found == 0:
        print("[-] No cards match this BIN.")
        return

    stamp = datetime.now().strftime('%H%M%S')
    out_file = f"sorted_{prefix}_{stamp}.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(matched))

    print(f"\n[+] Found {total_found} cards with BIN {prefix}")
    print(f"[+] Saved to: {out_file}")


# ── Interactive Menu ────────────────────────────────────────────────────────

def print_menu():
    print()
    print(separator("MAIN MENU"))
    print("  [1]  /xvv     Single card check")
    print("  [2]  /mxvv    Mass card check from file")
    print("  [3]  /clean   Extract cards from messy file")
    print("  [6]  /split   Split file into N parts")
    print("  [7]  /sort    Filter cards by BIN from file")
    print("  [8]  /bin     BIN lookup")
    print("  [9]  /help    Show all commands")
    print("  [10] /exit    Exit")
    print(separator())


def print_help():
    print()
    print(separator("COMMANDS"))
    print("  /xvv <cc>|<mm>|<yy>|<cvv>              Single card check")
    print("  /mxvv <filepath>                       Mass card check from file")
    print("  /clean <filepath>                      Extract+deduplicate cards")
    print("  /split <N> <filepath>                  Split file into N parts")
    print("  /sort <bin> <filepath>                 Filter cards by BIN prefix")
    print("  /bin <bin_prefix>                      BIN lookup")
    print("  /menu                                  Show interactive menu")
    print("  /help                                  This help")
    print("  /exit                                  Exit")
    print(separator())


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(BANNER)

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        args = sys.argv[2:]
        if cmd in ("/xvv", "xvv"):
            await cmd_xvv(args)
        elif cmd in ("/mxvv", "mxvv"):
            await cmd_mxvv(args)
        elif cmd in ("/clean", "clean"):
            await cmd_clean(args)
        elif cmd in ("/split", "split"):
            await cmd_split(args)
        elif cmd in ("/sort", "sort"):
            await cmd_sort(args)
        elif cmd in ("/bin", "bin"):
            await cmd_bin(args)
        elif cmd in ("/help", "/h", "help", "h"):
            print_help()
        else:
            print(f"Unknown: {cmd}")
            print_help()
        return

    print_menu()
    print("Enter a command or number. Type /help")

    while True:
        try:
            inp = input("\n>> ").strip()
            if not inp:
                continue

            parts = inp.split()
            cmd = parts[0].lower()
            args = parts[1:]

            menu_map = {
                "1": "/xvv", "2": "/mxvv",
                "3": "/clean", "4": "/split", "5": "/sort", "6": "/bin",
                "7": "/help", "8": "/exit",
            }

            if cmd in menu_map:
                mapped = menu_map[cmd]
                if mapped == "/xvv":
                    more = input("  Card (cc|mm|yy|cvv): ").strip()
                    if more:
                        await cmd_xvv([more])
                    continue
                elif mapped == "/mxvv":
                    more = input("  File path: ").strip()
                    if more:
                        await cmd_mxvv([more])
                    continue
                elif mapped == "/clean":
                    more = input("  File path: ").strip()
                    if more:
                        await cmd_clean([more])
                    continue
                elif mapped == "/split":
                    n = input("  Number of parts: ").strip()
                    fp = input("  File path: ").strip()
                    if n and fp:
                        await cmd_split([n, fp])
                    continue
                elif mapped == "/sort":
                    b = input("  BIN prefix: ").strip()
                    fp = input("  File path: ").strip()
                    if b and fp:
                        await cmd_sort([b, fp])
                    continue
                elif mapped == "/bin":
                    b = input("  BIN: ").strip()
                    if b:
                        await cmd_bin([b])
                    continue
                elif mapped == "/help":
                    print_help()
                    continue
                elif mapped == "/exit":
                    print("Bye.")
                    break
                continue

            if cmd in ("/xvv", "xvv"):
                await cmd_xvv(args if args else [input("  Card: ").strip()])
            elif cmd in ("/mxvv", "mxvv"):
                await cmd_mxvv(args if args else [input("  File path: ").strip()])
            elif cmd in ("/clean", "clean"):
                await cmd_clean(args if args else [input("  File path: ").strip()])
            elif cmd in ("/split", "split"):
                if len(args) >= 2:
                    await cmd_split(args)
                else:
                    n = input("  Number of parts: ").strip()
                    fp = input("  File path: ").strip()
                    if n and fp:
                        await cmd_split([n, fp])
            elif cmd in ("/sort", "sort"):
                if len(args) >= 2:
                    await cmd_sort(args)
                else:
                    b = input("  BIN prefix: ").strip()
                    fp = input("  File path: ").strip()
                    if b and fp:
                        await cmd_sort([b, fp])
            elif cmd in ("/bin", "bin"):
                await cmd_bin(args if args else [input("  BIN: ").strip()])
            elif cmd in ("/menu", "menu"):
                print_menu()
            elif cmd in ("/help", "/h", "help", "h"):
                print_help()
            elif cmd in ("/exit", "/quit", "exit", "quit", "10"):
                print("Bye.")
                break
            else:
                print(f"Unknown: {cmd}. Type /help or /menu")

        except KeyboardInterrupt:
            print("\nBye.")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

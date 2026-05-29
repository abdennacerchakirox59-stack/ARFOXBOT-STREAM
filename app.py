import telebot
import subprocess
import requests
import threading
import os
import json

# ================= CONFIG =================
BOT_TOKEN = "8970620272:AAE91-X9nNoJRS4mA_Qyd6OSF-Pa9a6EqwQ"
bot = telebot.TeleBot(BOT_TOKEN)

DATA_FILE = "data.json"

# ================= JSON STORAGE LOGIC =================
def load_data():
    """طھط­ظ…ظٹظ„ ط§ظ„ط¨ظٹط§ظ†ط§طھ ظ…ظ† ظ…ظ„ظپ JSON"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"pages": {}, "channels": {}}
    return {"pages": {}, "channels": {}}

def save_data():
    """ط­ظپط¸ ط§ظ„ط¨ظٹط§ظ†ط§طھ ظپظٹ ظ…ظ„ظپ JSON"""
    data = {
        "pages": user_pages,
        "channels": user_m3u8
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# طھظ‡ظٹط¦ط© ط§ظ„ط¨ظٹط§ظ†ط§طھ ظ…ظ† ط§ظ„ظ…ظ„ظپ ط¹ظ†ط¯ طھط´ط؛ظٹظ„ ط§ظ„ط³ظƒط±ط¨طھ
db = load_data()
user_pages = db.get("pages", {})
user_m3u8 = db.get("channels", {})
active_page = {}
user_streams = {}

# ================= DASH FIX =================
def fix_dash_url(url):
    if not url: return None
    if "scontent-" in url and ".fbcdn.net" in url:
        end = url.find(".fbcdn.net")
        return "https://video.xx.fbcdn.net" + url[end + len(".fbcdn.net"):]
    return url

# ================= FACEBOOK API =================
def get_new_stream(chat_id):
    chat_id_str = str(chat_id)
    page_name = active_page.get(chat_id)
    
    if not page_name or chat_id_str not in user_pages or page_name not in user_pages[chat_id_str]:
        return None, None, None, None
        
    page = user_pages[chat_id_str][page_name]

    try:
        r = requests.post(
            f"https://graph.facebook.com/v17.0/{page['page_id']}/live_videos",
            params={
                "access_token": page["token"],
                "status": "UNPUBLISHED",
                "title": "Forja TV Stream",
                "description": "Live Stream via Forja Bot"
            }, timeout=15
        ).json()

        live_id = r.get("id")
        if not live_id: return None, None, None, None

        info = requests.get(
            f"https://graph.facebook.com/v17.0/{live_id}",
            params={"access_token": page["token"], "fields": "stream_url,dash_preview_url"}, 
            timeout=15
        ).json()

        return info.get("stream_url"), live_id, fix_dash_url(info.get("dash_preview_url")), page["token"]
    except Exception as e:
        print(f"API Error: {e}")
        return None, None, None, None

def start_ffmpeg(stream_url, source):
    command = [
        "ffmpeg",
        "-re",
        "-i", source,
        "-c", "copy",
        "-f", "flv",
        "-flvflags", "no_duration_filesize",
        stream_url
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ================= FFMPEG ADVANCED TRANSCODING PRO WITH FILTERS =================
def start_ffmpeg_with_filters(stream_url, rtmp_url, watermark_path=None, overlay_text=None):
    # 1. ط¨ظ†ط§ط، ط§ظ„ط£ظ…ط± ط§ظ„ط£ط³ط§ط³ظٹ ظˆطھط­ط¯ظٹط¯ ظ…طµط¯ط± ط§ظ„ط¨ط« ظˆط§ظ„ط±ظˆط§ط¨ط· ط§ظ„ظ…ظ‡طھط²ط©
    command = [
        "ffmpeg",
        "-re",                          # ط§ظ„ظ‚ط±ط§ط،ط© ط¨ظ…ط¹ط¯ظ„ ط§ظ„ط¨طھ ط§ظ„ط·ط¨ظٹط¹ظٹ ظ„ظ„ظپظٹط¯ظٹظˆ (Real-time)
        "-i", stream_url,               # ظ…طµط¯ط± ط§ظ„ط¨ط« ط§ظ„ط£طµظ„ظٹ (ط±ط§ط¨ط· ط§ظ„ظ€ IPTV ط£ظˆ ط§ظ„ظ‚ظ†ط§ط©)
    ]
    
    # --- ط¥ط¹ط¯ط§ط¯ط§طھ ط§ظ„ظپظ„ط§طھط± (ط§ظ„ظ†طµ ظˆط§ظ„ط¹ظ„ط§ظ…ط© ط§ظ„ظ…ط§ط¦ظٹط©) ---
    filters = []
    
    # ط¥ط¶ط§ظپط© ط§ظ„ط¥ط¯ط®ط§ظ„ ط§ظ„ط«ط§ظ†ظٹ ط¥ط°ط§ ظˆظڈط¬ط¯ ط´ط¹ط§ط± (ط§ظ„ط¹ظ„ط§ظ…ط© ط§ظ„ظ…ط§ط¦ظٹط©)
    if watermark_path:
        command.extend(["-i", watermark_path])
        # ط¶ط¨ط· ط­ط¬ظ… ط§ظ„ط´ط¹ط§ط± (100x100) ظˆظˆط¶ط¹ظ‡ ظپظٹ ط£ط¹ظ„ظ‰ ط§ظ„ظٹط³ط§ط±
        filters.append("[1:v]scale=100:100[watermark];[0:v][watermark]overlay=10:10")
    
    # ط¥ط¶ط§ظپط© ط§ظ„ظ†طµ ط£ط³ظپظ„ ط§ظ„ط´ط§ط´ط© ط¥ط°ط§ ظˆظڈط¬ط¯
    if overlay_text and overlay_text.strip():
        safe_text = overlay_text.replace("'", "").replace('"', '').replace(":", "")
        # ظ…ط³ط§ط± ط§ظ„ط®ط· ط§ظ„ط§ظپطھط±ط§ط¶ظٹ ظپظٹ ط£ظ†ط¸ظ…ط© ظ„ظٹظ†ظƒط³ ظˆطھظٹط±ظ…ظˆظƒط³
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        
        if filters:
            filters.append(f"drawtext=text='{safe_text}':fontcolor=white:fontsize=24:x=10:y=H-40:fontfile={font_path}")
        else:
            filters.append(f"drawtext=text='{safe_text}':fontcolor=white:fontsize=24:x=10:y=H-40:fontfile={font_path}")
            
    # ط¯ظ…ط¬ ط§ظ„ظپظ„ط§طھط± ط§ظ„ظ…ط¬ظ‡ط²ط© ط¯ط§ط®ظ„ ط§ظ„ظ…طµظپظˆظپط© ط¥ط°ط§ طھظ… طھظپط¹ظٹظ„ ط£ط­ط¯ظ‡ط§
    if filters:
        command.extend(["-filter_complex", ";".join(filters)])
        
    # --- ط¥ط¹ط¯ط§ط¯ط§طھ ط¥ط¹ط§ط¯ط© ط§ظ„طھط±ظ…ظٹط² ظˆط«ط¨ط§طھ ط§ظ„ط¨ط« (ط§ظ„طھظٹ ظƒط§ظ†طھ ط¨ط§ظ„ط³ظƒط±ط¨طھ ط§ظ„ط£ظˆظ„) ---
    command.extend([
        # ط¥طµظ„ط§ط­ ط§ظ„طھظˆظ‚ظٹطھ ظˆظ…ظ‚ط§ظˆظ…ط© طھظ‚ط·ط¹ط§طھ ط§ظ„ط±ط§ط¨ط· ط§ظ„ط£طµظ„ظٹ (ظ…ظ‡ظ…ط© ط¬ط¯ط§ظ‹ ظ„ط«ط¨ط§طھ ط§ظ„ظ€ IPTV)
        "-fflags", "+genpts+discardcorrupt",
        "-avoid_negative_ts", "make_zero",
        
        # ظ…ط±ظ…ط² ط§ظ„ظپظٹط¯ظٹظˆ ظˆط§ظ„ط³ط±ط¹ط© ظˆظپظˆط±ظٹط© ط§ظ„ط¨ط«
        "-c:v", "libx264",              # ط§ط³طھط®ط¯ط§ظ… ط§ظ„ظ…ط±ظ…ط² ط§ظ„ظ‚ظٹط§ط³ظٹ H.264
        "-preset", "veryfast",          # ظ…ظˆط§ط²ظ†ط© ظ…ظ…طھط§ط²ط© ط¨ظٹظ† ط³ط±ط¹ط© ط§ظ„ظ…ط¹ط§ظ„ط¬ط© ظˆط¬ظˆط¯ط© ط§ظ„ط¨ظƒط³ظ„ط§طھ
        "-tune", "zerolatency",         # ط¥ظ„ط؛ط§ط، ط§ظ„ظ€ Lag ظˆط§ظ„طھط£ط®ظٹط± ظپظˆط±ط§ظ‹ ط¨ظٹظ†ظƒ ظˆط¨ظٹظ† ط§ظ„ط³ظٹط±ظپط±
        
        # ط§ظ„طھط­ظƒظ… ظپظٹ طµط¨ظٹط¨ ط§ظ„ط¨ظٹط§ظ†ط§طھ ظˆط§ظ„ظ€ Bitrate (ط«ط¨ط§طھ ط§ظ„ظ€ CBR ط§ظ„ظ…طھظˆط§ظپظ‚ ظ…ط¹ ط§ظ„ظپظٹط³ط¨ظˆظƒ)
        "-b:v", "2000k",                # طµط¨ظٹط¨ ط¨ظٹط§ظ†ط§طھ ظ…ط³طھظ‚ط± ظˆظ…ظ†ط§ط³ط¨ ط¬ط¯ط§ظ‹ ظ„ظ„ط¥ظ†طھط±ظ†طھ
        "-maxrate", "2000k",            # ظ…ظ†ط¹ ظ‚ظپط²ط§طھ ط§ظ„ظ€ Bitrate ط§ظ„ظ…ظپط§ط¬ط¦ط©
        "-bufsize", "4000k",            # ط­ط¬ظ… ط§ظ„ط¨ط§ظپط± ظ„ط¶ظ…ط§ظ† ط³ظ„ط§ط³ط© ط§ظ„طھط¯ظپظ‚
        "-pix_fmt", "yuv420p",          # طھظ†ط³ظٹظ‚ ط§ظ„ط£ظ„ظˆط§ظ† ط§ظ„ظ‚ظٹط§ط³ظٹ ظ„ظ„ط¨ط« ط§ظ„ظ…ط¨ط§ط´ط±
        "-g", "60",                     # ظ…ظپطھط§ط­ ط¥ط·ط§ط± (Keyframe) ظƒظ„ ط«ط§ظ†ظٹطھظٹظ† ط¶ط¨ط·ط§ظ‹
        
        # --- ط¥ط¹ط¯ط§ط¯ط§طھ ط§ظ„طµظˆطھ ط§ظ„ظ‚ظٹط§ط³ظٹط© ط§ظ„ظ…ط³طھظ‚ط±ط© ---
        "-c:a", "aac",                  # طھط±ظ…ظٹط² ط§ظ„طµظˆطھ ط¨طµظٹط؛ط© AAC ط§ظ„ظ‚ظٹط§ط³ظٹط©
        "-b:a", "128k",                 # ط¬ظˆط¯ط© طµظˆطھ ظ†ظ‚ظٹط© ظˆظ…ط³طھظ‚ط±ط©
        "-ar", "44100",                 # طھط«ط¨ظٹطھ طھط±ط¯ط¯ ط§ظ„طµظˆطھ ط§ظ„ظ…طھظˆط§ظپظ‚ 100% ظ…ط¹ ط§ظ„ط¨ط«
        
        # --- ظ…ط®ط±ط¬ ط§ظ„ط¨ط« ظˆط³ظٹط±ظپط± ط§ظ„ظ€ RTMP ط§ظ„ظ†ظ‡ط§ط¦ظٹ ---
        "-f", "flv",                    # ط¥ط¬ط¨ط§ط± ط­ط§ظˆظٹط© ط§ظ„ظ€ FLV ط§ظ„ط®ط§طµط© ط¨ط§ظ„ط¨ط« ط§ظ„ظ…ط¨ط§ط´ط±
        "-flvflags", "no_duration_filesize",
        rtmp_url                        # ط±ط§ط¨ط· ط§ظ„ظ€ RTMP ط§ظ„ظ…ط¯ظ…ط¬ ظ…ط¹ظ‡ ط§ظ„ظ€ Stream Key
    ])
    
    # طھط´ط؛ظٹظ„ ط§ظ„ط¹ظ…ظ„ظٹط© ظپظٹ ط§ظ„ط®ظ„ظپظٹط© ط¯ظˆظ† ط­ط¸ط± ط§ظ„ط³ظƒط±ظٹط¨طھ ط§ظ„ط£ط³ط§ط³ظٹ
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ================= STREAM THREAD =================
def stream_thread(chat_id, source, name):
    try:
        if name in user_streams.get(chat_id, {}):
            stop_stream(chat_id, name)

        stream_url, live_id, dash, token = get_new_stream(chat_id)
        if not stream_url:
            bot.send_message(chat_id, f"â‌Œ ظپط´ظ„ ط¥ظ†ط´ط§ط، ط¨ط« ظ„ظ€: {name}\nطھط£ظƒط¯ ظ…ظ† ط§ط®طھظٹط§ط± ط§ظ„طµظپط­ط© ط§ظ„طµط­ظٹط­ط© ط¨ظ€ /usepage")
            return

        process = start_ffmpeg(stream_url, source)
        
        user_streams.setdefault(chat_id, {})[name] = {
            "process": process,
            "live_id": live_id,
            "token": token,
            "dash_url": dash # ط­ظپط¸ ط±ط§ط¨ط· ط§ظ„ط¯ط§ط´ ظ„ظ„ظپط­طµ ظ„ط§ط­ظ‚ط§ظ‹
        }

        msg = f"ًںڑ€ **ط¨ط¯ط£ ط§ظ„ط¨ط« ط¨ظ†ط¬ط§ط­:**\nًںژ¥ ط§ظ„ظ‚ظ†ط§ط©: `{name}`"
        if dash:
            msg += f"\n\nًں”— **ط±ط§ط¨ط· DASH ظ„ظ„ظ…ط¹ط§ظٹظ†ط©:**\n`{dash}`"
        
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Thread Error: {e}")

# ================= STOP STREAM =================
def stop_stream(chat_id, name):
    info = user_streams.get(chat_id, {}).get(name)
    if not info: return

    try:
        info["process"].kill() 
        requests.delete(
            f"https://graph.facebook.com/v17.0/{info['live_id']}",
            params={"access_token": info["token"]}, timeout=5
        )
    except: pass

    if name in user_streams[chat_id]:
        del user_streams[chat_id][name]
    bot.send_message(chat_id, f"ًں›‘ طھظ… ط¥ظٹظ‚ط§ظپ: {name}")

# ================= NEW: TEST ALL DASH COMMAND =================
@bot.message_handler(commands=["testall"])
def test_all_dash(msg):
    streams = user_streams.get(msg.chat.id, {})
    if not streams:
        bot.send_message(msg.chat.id, "â‌Œ ظ„ط§ طھظˆط¬ط¯ ظ‚ظ†ظˆط§طھ طھط¨ط« ط­ط§ظ„ظٹط§ظ‹ ظ„ظپط­طµظ‡ط§.")
        return

    status_msg = "ًں§ھ **ظپط­طµ ط±ظˆط§ط¨ط· DASH ظ„ظ„ط¨ط«ظˆط« ط§ظ„ظ†ط´ط·ط©:**\n\n"
    
    for name, info in streams.items():
        dash_url = info.get("dash_url")
        if not dash_url:
            status_msg += f"âڑھï¸ڈ **{name}**: ظ„ط§ ظٹظˆط¬ط¯ ط±ط§ط¨ط· DASH ظ„ظ‡ط°ط§ ط§ظ„ط¨ط«.\n"
            continue
            
        try:
            # ظ…ط­ط§ظˆظ„ط© ط·ظ„ط¨ ط§ظ„ط±ط§ط¨ط· ظ„ظ„طھط£ظƒط¯ ظ…ظ† ط£ظ†ظ‡ ظٹط¹ظ…ظ„ (Status 200)
            check = requests.get(dash_url, timeout=10)
            if check.status_code == 200:
                status_msg += f"âœ… **{name}**: ط±ط§ط¨ط· DASH ظٹط¹ظ…ظ„ ط¨ظ†ط¬ط§ط­.\n"
            else:
                status_msg += f"â‌Œ **{name}**: ط±ط§ط¨ط· DASH ظ„ط§ ظٹط¹ظ…ظ„ (Error {check.status_code}).\n"
        except:
            status_msg += f"â‌Œ **{name}**: ط±ط§ط¨ط· DASH ظ…طھط¹ط·ظ„ (ط®ط·ط£ ط§طھطµط§ظ„).\n"
            
    bot.send_message(msg.chat.id, status_msg, parse_mode="Markdown")

# ================= NEW: TEST SAVED M3U8 COMMAND =================
@bot.message_handler(commands=["testm3u8"])
def test_saved_links(msg):
    chat_id_str = str(msg.chat.id)
    saved_channels = user_m3u8.get(chat_id_str, {})

    if not saved_channels:
        bot.send_message(msg.chat.id, "â‌Œ ظ„ط§ طھظˆط¬ط¯ ظ‚ظ†ظˆط§طھ ظ…ط­ظپظˆط¸ط© ظ„ظپط­طµظ‡ط§. ط§ط³طھط®ط¯ظ… /savem3u8 ط£ظˆظ„ط§ظ‹.")
        return

    wait_msg = bot.send_message(msg.chat.id, "âڈ³ ط¬ط§ط±ظٹ ظپط­طµ ط§ظ„ط±ظˆط§ط¨ط· ط§ظ„ظ…ط­ظپظˆط¸ط©...")
    
    report = "ًں§ھ **طھظ‚ط±ظٹط± ظپط­طµ ط§ظ„ظ‚ظ†ظˆط§طھ ط§ظ„ظ…ط­ظپظˆط¸ط©:**\n\n"
    
    for name, url in saved_channels.items():
        link_type = "ًں”— URL"
        if ".m3u8" in url.lower(): link_type = "ًںژ¥ M3U8"
        elif ".mpd" in url.lower(): link_type = "ًں“¦ MPD"
        
        try:
            # ط§ط³طھط®ط¯ط§ظ… HEAD ظ„ط³ط±ط¹ط© ط§ظ„ظپط­طµطŒ ظˆظپظٹ ط­ط§ظ„ ظپط´ظ„ظ‡ ظ†ط³طھط®ط¯ظ… GET (ظپظ‚ط· ط§ظ„ط±ط¤ظˆط³)
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code >= 400:
                response = requests.get(url, timeout=5, stream=True)
            
            if response.status_code == 200:
                report += f"âœ… **{name}**\nâ”— ط§ظ„ظ†ظˆط¹: `{link_type}` | ط§ظ„ط­ط§ظ„ط©: `ط´ط؛ط§ظ„`\n\n"
            else:
                report += f"â‌Œ **{name}**\nâ”— ط§ظ„ظ†ظˆط¹: `{link_type}` | ط§ظ„ط­ط§ظ„ط©: `ط®ط·ط£ {response.status_code}`\n\n"
        except:
            report += f"âڑ ï¸ڈ **{name}**\nâ”— ط§ظ„ظ†ظˆط¹: `{link_type}` | ط§ظ„ط­ط§ظ„ط©: `ط؛ظٹط± ظ…ط³طھط¬ظٹط¨`\n\n"

    bot.delete_message(msg.chat.id, wait_msg.message_id)
    
    if len(report) > 4000:
        for x in range(0, len(report), 4000):
            bot.send_message(msg.chat.id, report[x:x+4000], parse_mode="Markdown")
    else:
        bot.send_message(msg.chat.id, report, parse_mode="Markdown")

# ================= COMMANDS =================
@bot.message_handler(commands=["check"])
def check_tokens(msg):
    chat_id_str = str(msg.chat.id)
    if chat_id_str not in user_pages or not user_pages[chat_id_str]:
        bot.send_message(msg.chat.id, "â‌Œ ظ„ظٹط³ ظ„ط¯ظٹظƒ طµظپط­ط§طھ ظ…ط³ط¬ظ„ط© ظ„ظ„طھط­ظ‚ظ‚ ظ…ظ†ظ‡ط§.")
        return

    status_msg = "ًں”چ **ظ†طھط§ط¦ط¬ ط§ظ„طھط­ظ‚ظ‚ ظ…ظ† ط§ظ„طھظˆظƒظ†ط§طھ:**\n\n"
    
    for name, data in user_pages[chat_id_str].items():
        token = data.get("token")
        try:
            response = requests.get(
                f"https://graph.facebook.com/me",
                params={"access_token": token},
                timeout=10
            )
            if response.status_code == 200:
                status_msg += f"âœ… **{name}**: ظ‡ط°ط§ ط§ظ„طھظˆظƒظ† ط´ط؛ط§ظ„\n"
            else:
                status_msg += f"â‌Œ **{name}**: ظ‡ط°ط§ ط§ظ„طھظˆظƒظ† ط؛ظٹط± طµط§ظ„ط­\n"
        except:
            status_msg += f"âڑ ï¸ڈ **{name}**: طھط¹ط°ط± ط§ظ„طھط­ظ‚ظ‚ (ط®ط·ط£ ظپظٹ ط§ظ„ط§طھطµط§ظ„)\n"
    
    bot.send_message(msg.chat.id, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=["addpage"])
def add_page(msg):
    try:
        p = msg.text.split(maxsplit=3)
        if len(p) < 4: raise ValueError
        chat_id_str = str(msg.chat.id)
        user_pages.setdefault(chat_id_str, {})[p[1]] = {"page_id": p[2], "token": p[3]}
        save_data() 
        bot.send_message(msg.chat.id, f"âœ… طھظ… ط¥ط¶ط§ظپط© ط§ظ„طµظپط­ط© `{p[1]}` ط¨ظ†ط¬ط§ط­.", parse_mode="Markdown")
    except:
        bot.send_message(msg.chat.id, "âڑ ï¸ڈ ط§ظ„طµظٹط؛ط©: `/addpage ط§ظ„ط§ط³ظ… ID ط§ظ„طھظˆظƒظ†`", parse_mode="Markdown")

@bot.message_handler(commands=["usepage"])
def use_page(msg):
    try:
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(msg.chat.id, "âڑ ï¸ڈ ط£ط±ط³ظ„: `/usepage ط§ط³ظ…_ط§ظ„طµظپط­ط©`", parse_mode="Markdown")
            return
            
        name = parts[1].strip()
        chat_id_str = str(msg.chat.id)
        
        if chat_id_str in user_pages and name in user_pages[chat_id_str]:
            active_page[msg.chat.id] = name
            bot.send_message(msg.chat.id, f"ًںژ¯ ط§ظ„طµظپط­ط© ط§ظ„ظ†ط´ط·ط© ط§ظ„ط¢ظ†: `{name}`", parse_mode="Markdown")
        else:
            bot.send_message(msg.chat.id, f"â‌Œ ط§ظ„طµظپط­ط© `{name}` ط؛ظٹط± ظ…ظˆط¬ظˆط¯ط©.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"â‌Œ ط­ط¯ط« ط®ط·ط£: {e}")

@bot.message_handler(commands=["savem3u8"])
def save_m3u8(msg):
    try:
        _, name, url = msg.text.split(maxsplit=2)
        chat_id_str = str(msg.chat.id)
        user_m3u8.setdefault(chat_id_str, {})[name] = url
        save_data() 
        bot.send_message(msg.chat.id, f"ًں’¾ طھظ… ط­ظپط¸ ط§ظ„ظ‚ظ†ط§ط©: `{name}`", parse_mode="Markdown")
    except:
        bot.send_message(msg.chat.id, "âڑ ï¸ڈ ط§ظ„طµظٹط؛ط©: `/savem3u8 ط§ظ„ط§ط³ظ… ط§ظ„ط±ط§ط¨ط·`", parse_mode="Markdown")

@bot.message_handler(commands=["m3u8list"])
def m3u8_list(msg):
    chat_id_str = str(msg.chat.id)
    data = user_m3u8.get(chat_id_str)
    if not data:
        bot.send_message(msg.chat.id, "â‌Œ ظ‚ط§ط¦ظ…ط© ط§ظ„ظ‚ظ†ظˆط§طھ ظپط§ط±ط؛ط©.")
        return
    txt = "ًں“؛ **ط§ظ„ظ‚ظ†ظˆط§طھ ط§ظ„ظ…ط­ظپظˆط¸ط©:**\n"
    for n in data: txt += f"- `{n}`\n"
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown")

@bot.message_handler(commands=["stopall"])
def stop_all(msg):
    streams = user_streams.get(msg.chat.id, {})
    if not streams:
        bot.send_message(msg.chat.id, "â‌Œ ظ„ط§ طھظˆط¬ط¯ ط¨ط«ظˆط« ظ†ط´ط·ط©.")
        return
    for name in list(streams.keys()):
        stop_stream(msg.chat.id, name)
    bot.send_message(msg.chat.id, "ًں›‘ طھظ… طھظ†ط¸ظٹظپ ط§ظ„ط±ط§ظ… ظˆط¥ظٹظ‚ط§ظپ ط¬ظ…ظٹط¹ ط§ظ„ط¹ظ…ظ„ظٹط§طھ.")

@bot.message_handler(content_types=["document"])
def handle_txt(msg):
    if not msg.document.file_name.lower().endswith(".txt"): return
    try:
        file_info = bot.get_file(msg.document.file_id)
        content = bot.download_file(file_info.file_path).decode('utf-8')
        chat_id_str = str(msg.chat.id)
        user_m3u8.setdefault(chat_id_str, {})
        count = 0
        for line in content.splitlines():
            line = line.strip()
            if line and " " in line:
                name, url = line.split(maxsplit=1)
                if url.startswith("http"):
                    user_m3u8[chat_id_str][name] = url
                    count += 1
        save_data() 
        bot.send_message(msg.chat.id, f"ًں’¾ طھظ… ط§ط³طھظٹط±ط§ط¯ {count} ظ‚ظ†ط§ط© ط¨ظ†ط¬ط§ط­.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"â‌Œ ط®ط·ط£ ظپظٹ ط§ظ„ظ…ظ„ظپ: {e}")

@bot.message_handler(func=lambda m: True)
def start_by_name(msg):
    if msg.chat.id not in active_page:
        bot.send_message(msg.chat.id, "âڑ ï¸ڈ ط§ط®طھط± طµظپط­ط© ط£ظˆظ„ط§ظ‹ ط¨ط§ط³طھط®ط¯ط§ظ… `/usepage`")
        return
    
    chat_id_str = str(msg.chat.id)
    saved = user_m3u8.get(chat_id_str, {})
    names = msg.text.splitlines()
    started_count = 0

    for n in names:
        n = n.strip()
        if n in saved:
            threading.Thread(
                target=stream_thread, 
                args=(msg.chat.id, saved[n], n), 
                daemon=True
            ).start()
            started_count += 1

    if started_count == 0:
        bot.send_message(msg.chat.id, "â‌Œ ظ„ظ… ظٹطھظ… ط§ظ„ط¹ط«ظˆط± ط¹ظ„ظ‰ ط§ط³ظ… ظ‚ظ†ط§ط© ظ…ط·ط§ط¨ظ‚.")

if __name__ == "__main__":
    print("ًںژ¬ Bot ZenGo is Running ...")
    bot.infinity_polling()

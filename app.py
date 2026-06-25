import telebot
import subprocess
import time
import requests
import threading
import json
import os
import re

# ================= CONFIG =================
BOT_TOKEN = "8935584921:AAGMjeS6CsBw0hXIf0Rbu9nbQbY3n1hfw4k"
bot = telebot.TeleBot(BOT_TOKEN)

DATA_FILE = "data.json"

# ================= STORAGE & JSON MECHANISM =================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"pages": {}, "channels": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"pages": {}, "channels": {}}

def save_data():
    data = {
        "pages": user_pages,
        "channels": user_m3u8
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data_store = load_data()
user_pages = data_store.get("pages", {})
user_m3u8 = data_store.get("channels", {})

active_page = {}
user_streams = {}

# ================= DIRECT FACEBOOK ZERO REWRITER =================
def rewrite_to_facebook_zero(url):
    """
    تحوير رابط الـ DASH الرسمي القادم من فيسبوك مباشرة
    ليتم تمريره عبر نطاقات الـ Zero المفتوحة مجاناً بدون رصيد
    """
    if not url:
        return None
    
    # البحث عن نطاقات الميديا الرسمية لفيسبوك وتشويهها بنطاق الـ Zero المفتوح بالمغرب
    # يتم دمج الـ Host المجاني لخدعة الفلترة مع الحفاظ على مسار وجلسة البث الحقيقية لفيسبوك
    match = re.search(r"https://([^/]*?(?:video|scontent)[^/]*?\.fbcdn\.net)/", url)
    if match:
        # استبدال النطاق بنطاق فيسبوك زيرو الأساسي مع الحفاظ على التوجيه المستهدف للـ CDN
        replacement = "https://free.facebook.com.video.xx.fbcdn.net/"
        return re.sub(r"https://[^/]*?(?:video|scontent)[^/]*?\.fbcdn\.net/", replacement, url)
    return url

# ================= FACEBOOK GRAPH API =================
def get_new_stream(chat_id):
    page_name = active_page.get(chat_id)
    if not page_name:
        return None, None, None, None

    page = user_pages[chat_id][page_name]

    try:
        r = requests.post(
            f"https://graph.facebook.com/v17.0/{page['page_id']}/live_videos",
            params={
                "access_token": page["token"],
                "status": "UNPUBLISHED",
                "title": "Zero Direct Live",
                "description": "Pure FB Zero Pass"
            },
            timeout=10
        ).json()

        if "id" not in r:
            return None, None, None, None

        live_id = r["id"]
        info = requests.get(
            f"https://graph.facebook.com/v17.0/{live_id}",
            params={
                "access_token": page["token"],
                "fields": "stream_url,dash_preview_url"
            },
            timeout=10
        ).json()

        # جلب الرابط الرسمي وتحويره فوراً للـ Zero
        zero_dash = rewrite_to_facebook_zero(info.get("dash_preview_url"))
        return info.get("stream_url"), live_id, zero_dash, page["token"]
    except:
        return None, None, None, None

# ================= FFMPEG ENGINE =================
def launch_ffmpeg(source, stream_url):
    return subprocess.Popen([
        "ffmpeg", "-re",
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "1",
        "-i", source,
        "-c", "copy",
        "-f", "flv",
        stream_url
    ], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

# ================= STREAM THREAD =================
def stream_thread(chat_id, source, name):
    stream_url, live_id, dash, token = get_new_stream(chat_id)
    if not stream_url:
        bot.send_message(chat_id, "❌ فشل إنشاء البث المباشر.")
        return

    user_streams.setdefault(chat_id, {})[name] = {
        "proc": None,
        "live_id": live_id,
        "token": token,
        "active": True,
        "source": source,
        "dash_url": dash  
    }

    # وظيفة لتحديث الرابط بعد ثوانٍ من استقرار البث على سيرفرات فيسبوك
    def send_dash_later():
        time.sleep(15)
        try:
            info = requests.get(
                f"https://graph.facebook.com/v17.0/{live_id}",
                params={"access_token": token, "fields": "dash_preview_url"},
                timeout=10
            ).json()
            fresh_zero_dash = rewrite_to_facebook_zero(info.get("dash_preview_url"))
            if fresh_zero_dash:
                if chat_id in user_streams and name in user_streams[chat_id]:
                    user_streams[chat_id][name]["dash_url"] = fresh_zero_dash  
                bot.send_message(chat_id, f"🎥 القناة: {name}\n🚀 رابط DASH المباشر للـ Zero:\n`{fresh_zero_dash}`", parse_mode="Markdown")
        except:
            pass

    threading.Thread(target=send_dash_later, daemon=True).start()

    while user_streams.get(chat_id, {}).get(name, {}).get("active", False):
        proc = user_streams[chat_id][name].get("proc")

        if proc is None or proc.poll() is not None:
            proc = launch_ffmpeg(source, stream_url)
            user_streams[chat_id][name]["proc"] = proc
            
        time.sleep(1)

    proc = user_streams.get(chat_id, {}).get(name, {}).get("proc")
    if proc:
        proc.kill()

# ================= STOP STREAM FUNCTION =================
def stop_stream(chat_id, name):
    info = user_streams.get(chat_id, {}).get(name)
    if not info:
        return

    info["active"] = False

    try:
        if info.get("proc"):
            info["proc"].kill()
        requests.delete(
            f"https://graph.facebook.com/v17.0/{info['live_id']}",
            params={"access_token": info["token"]},
            timeout=10
        )
    except:
        pass

    if name in user_streams.get(chat_id, {}):
        del user_streams[chat_id][name]

# ================= COMMANDS HANDLERS =================

@bot.message_handler(commands=["addpage"])
def add_page(msg):
    try:
        _, name, page_id, token = msg.text.split(maxsplit=3)
    except:
        bot.send_message(msg.chat.id, "⚠️ الصيغة: /addpage الاسم ID التوكن")
        return
    
    str_chat_id = str(msg.chat.id)
    user_pages.setdefault(str_chat_id, {})[name] = {"page_id": page_id, "token": token}
    save_data()
    bot.send_message(msg.chat.id, f"✅ تم إضافة الصفحة {name} بنجاح.")

@bot.message_handler(commands=["usepage"])
def use_page(msg):
    try:
        _, name = msg.text.split(maxsplit=1)
    except:
        return
    
    str_chat_id = str(msg.chat.id)
    if name not in user_pages.get(str_chat_id, {}):
        bot.send_message(msg.chat.id, "❌ الصفحة غير موجودة")
        return
    
    active_page[str_chat_id] = name
    bot.send_message(msg.chat.id, f"🎯 الصفحة النشطة الآن: {name}")

@bot.message_handler(commands=["savem3u8"])
def save_m3u8(msg):
    try:
        _, name, url = msg.text.split(maxsplit=2)
    except:
        bot.send_message(msg.chat.id, "⚠️ الصيغة: /savem3u8 الاسم الرابط")
        return
    
    str_chat_id = str(msg.chat.id)
    user_m3u8.setdefault(str_chat_id, {})[name] = url
    save_data()
    bot.send_message(msg.chat.id, f"💾 تم حفظ القناة: {name}")

@bot.message_handler(commands=["m3u8list"])
def m3u8_list(msg):
    str_chat_id = str(msg.chat.id)
    data = user_m3u8.get(str_chat_id)
    if not data or len(data) == 0:
        bot.send_message(msg.chat.id, "❌ قائمة القنوات فارغة..")
        return
    
    txt = "📺 القنوات المحفوظة:\n"
    for n in data:
        txt += f"- {n}\n"
    bot.send_message(msg.chat.id, txt)

@bot.message_handler(commands=["stopall"])
def stop_all(msg):
    str_chat_id = str(msg.chat.id)
    streams = user_streams.get(str_chat_id)
    if not streams:
        bot.send_message(msg.chat.id, "❌ لا توجد بثوث نشطة")
        return
    
    for name in list(streams.keys()):
        stop_stream(str_chat_id, name)
        bot.send_message(msg.chat.id, f"🛑 تم إيقاف: {name}")
    
    bot.send_message(msg.chat.id, "🛑 تم تنظيف الرام وإيقاف جميع العمليات..")

# ================= TEXT MESSAGE GENERAL RECEIVER =================
@bot.message_handler(func=lambda m: True)
def start_by_name(msg):
    str_chat_id = str(msg.chat.id)
    if str_chat_id not in active_page:
        bot.send_message(msg.chat.id, "⚠️ اختر صفحة أولاً باستخدام /usepage.")
        return

    saved = user_m3u8.get(str_chat_id, {})
    started = 0
    not_found = False

    for name in msg.text.splitlines():
        name = name.strip()
        if not name:
            continue
        if name in saved:
            if name in user_streams.get(str_chat_id, {}):
                bot.send_message(msg.chat.id, f"⚠️ البث '{name}' قيد التشغيل بالفعل.")
                continue
            threading.Thread(
                target=stream_thread,
                args=(str_chat_id, saved[name], name),
                daemon=True
            ).start()
            started += 1
        else:
            not_found = True

    if started == 0 and not_found:
        bot.send_message(msg.chat.id, "❌ لم يتم العثور على اسم قناة مطابق.")

# ================= RUN =================
if __name__ == "__main__":
    print("🎬 Bot BeOut Pure Zero (No Proxy) is running ...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Error occurred: {e}")

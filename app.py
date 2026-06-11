import telebot
import subprocess
import time
import requests
import threading
import json
import os
import re

# ================= CONFIG =================
BOT_TOKEN = "8970620272:AAE91-X9nNoJRS4mA_Qyd6OSF-Pa9a6EqwQ"
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

# تحميل البيانات عند الإقلاع
data_store = load_data()
user_pages = data_store.get("pages", {})
user_m3u8 = data_store.get("channels", {})

# متغيرات الجلسة المؤقتة
active_page = {}
user_streams = {}

# ================= REGEX DASH FIX =================
def fix_dash_url(url):
    if not url:
        return None
    
    match = re.search(r"https://([^/]*?(?:video|scontent)[^/]*?\.fbcdn\.net)/", url)
    if match:
        domain = match.group(1)
        if "video" in domain:
            replacement = "https://BeOut+Lfraja@video.xx.fbcdn.net/"
        else:
            replacement = "https://BeOut+Lfraja@scontent.xx.fbcdn.net/"
        
        return re.sub(r"https://[^/]*?(?:video|scontent)[^/]*?\.fbcdn\.net/", replacement, url)
    return url

# ================= FACEBOOK GRAPH API =================
def get_new_stream(chat_id):
    page_name = active_page.get(chat_id)
    if not page_name:
        return None, None, None, None

    page = user_pages[chat_id][page_name]

    # نظام المحاولات المتكررة (Retries) لتفادي فشل استخراج المفتاح
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://graph.facebook.com/v17.0/{page['page_id']}/live_videos",
                params={
                    "access_token": page["token"],
                    "status": "UNPUBLISHED",
                    "title": "Live Preview",
                    "description": "Preview stream"
                },
                timeout=10
            ).json()

            if "id" not in r:
                time.sleep(2)
                continue

            live_id = r["id"]
            
            # الانتظار قليلاً لضمان قيام فيسبوك بتوليد الرابط
            time.sleep(1)
            
            info = requests.get(
                f"https://graph.facebook.com/v17.0/{live_id}",
                params={
                    "access_token": page["token"],
                    "fields": "stream_url,dash_preview_url"
                },
                timeout=10
            ).json()

            if info.get("stream_url"):
                return info.get("stream_url"), live_id, fix_dash_url(info.get("dash_preview_url")), page["token"]
        except:
            time.sleep(2)
            
    return None, None, None, None

# ================= FFMPEG ENGINE =================
def launch_ffmpeg(source, stream_url):
    # إزالة -re لمنع استهلاك المعالج مع روابط m3u8
    # إضافة أوامر reconnect لضمان استقرار البث وعدم توقفه
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", 
        "-reconnect_at_eof", "1", 
        "-reconnect_streamed", "1", 
        "-reconnect_delay_max", "5",
        "-i", source,
        "-c:v", "copy",
        "-c:a", "copy",
        "-f", "flv",
        "-flvflags", "no_duration_filesize",
        stream_url
    ], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

# ================= STREAM THREAD =================
def stream_thread(chat_id, source, name):
    stream_url, live_id, dash, token = get_new_stream(chat_id)
    if not stream_url:
        bot.send_message(chat_id, "❌ فشل إنشاء البث.")
        return

    user_streams.setdefault(chat_id, {})[name] = {
        "proc": None,
        "live_id": live_id,
        "token": token,
        "active": True,
        "source": source,
        "dash_url": dash  
    }

    def send_dash_later():
        time.sleep(20)
        try:
            info = requests.get(
                f"https://graph.facebook.com/v17.0/{live_id}",
                params={"access_token": token, "fields": "dash_preview_url"},
                timeout=10
            ).json()
            fresh = fix_dash_url(info.get("dash_preview_url"))
            if fresh:
                if chat_id in user_streams and name in user_streams[chat_id]:
                    user_streams[chat_id][name]["dash_url"] = fresh  
                bot.send_message(chat_id, f"🎥 {name}\n👁️ DASH:\n{fresh}")
        except:
            pass

    threading.Thread(target=send_dash_later, daemon=True).start()

    # استخدام proc.wait لمنع استهلاك الـ CPU بالكامل مع الحفاظ على التكرار الآمن
    while user_streams.get(chat_id, {}).get(name, {}).get("active", False):
        proc = launch_ffmpeg(source, stream_url)
        user_streams[chat_id][name]["proc"] = proc
        
        proc.wait() # تجميد الثريد هنا حتى تنتهي العملية دون استهلاك المعالج
        
        # إذا تم إيقاف العملية يدوياً، نخرج من الحلقة
        if not user_streams.get(chat_id, {}).get(name, {}).get("active", False):
            break
            
        time.sleep(3)

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

@bot.message_handler(commands=["check"])
def check_tokens(msg):
    str_chat_id = str(msg.chat.id)
    pages = user_pages.get(str_chat_id, {})
    if not pages:
        bot.send_message(msg.chat.id, "❌ لا توجد صفحات مسجلة لفحصها.")
        return
    
    report = "📋 تقرير فحص التوكنات:\n"
    for name, info in pages.items():
        try:
            r = requests.get(
                f"https://graph.facebook.com/v17.0/{info['page_id']}",
                params={"access_token": info["token"], "fields": "name"},
                timeout=10
            )
            if r.status_code == 200:
                report += f"✅ {name}: هذا التوكن شغال\n"
            else:
                report += f"❌ {name}: هذا التوكن غير صالح\n"
        except:
            report += f"❌ {name}: هذا التوكن غير صالح\n"
            
    bot.send_message(msg.chat.id, report)

@bot.message_handler(commands=["testall"])
def test_all_dash(msg):
    str_chat_id = str(msg.chat.id)
    streams = user_streams.get(str_chat_id, {})
    
    if not streams or len(streams) == 0:
        bot.send_message(msg.chat.id, "❌ لا توجد قنوات تبث حالياً لفحصها.")
        return
    
    report = "🧪 **فحص روابط DASH للبثوث النشطة:**\n\n"
    
    for name, info in streams.items():
        dash_url = info.get("dash_url")
        
        if not dash_url:
            report += f"⚪️ **{name}**: لا يوجد رابط DASH لهذا البث.\n"
            continue
            
        try:
            res = requests.get(dash_url, timeout=10)
            if res.status_code == 200:
                report += f"✅ **{name}**: رابط DASH يعمل بنجاح.\n"
            else:
                report += f"❌ **{name}**: رابط DASH لا يعمل (Error {res.status_code}).\n"
        except:
            report += f"❌ **{name}**: رابط DASH متعطل (خطأ اتصال).\n"
            
    bot.send_message(msg.chat.id, report, parse_mode="Markdown")

@bot.message_handler(commands=["testm3u8"])
def test_m3u8_channels(msg):
    str_chat_id = str(msg.chat.id)
    channels = user_m3u8.get(str_chat_id, {})
    if not channels:
        bot.send_message(msg.chat.id, "❌ قائمة القنوات فارغة..")
        return
    
    status_msg = bot.send_message(msg.chat.id, "⏳ جاري فحص الروابط المحفوظة...")
    report = "🧪 تقرير فحص القنوات المحفوظة:\n"
    
    for name, url in channels.items():
        if ".m3u8" in url.lower():
            link_type = "M3U8"
        elif ".mpd" in url.lower():
            link_type = "MPD"
        else:
            link_type = "URL"
            
        try:
            res = requests.head(url, timeout=5, allow_redirects=True)
            if res.status_code >= 200 and res.status_code < 400:
                status = "شغال ✅"
            else:
                status = f"خطأ ({res.status_code}) ❌"
        except:
            status = "غير مستجيب ❌"
            
        report += f"- {name} ({link_type}) -> {status}\n"
        
    bot.edit_message_text(report, chat_id=msg.chat.id, message_id=status_msg.message_id)

@bot.message_handler(content_types=["document"])
def handle_txt(msg):
    if not msg.document.file_name.lower().endswith(".txt"):
        return
    
    file_info = bot.get_file(msg.document.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    content = requests.get(file_url).text
    
    str_chat_id = str(msg.chat.id)
    user_m3u8.setdefault(str_chat_id, {})
    count = 0
    
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            name, url = line.split(maxsplit=1)
            if url.startswith("http"):
                user_m3u8[str_chat_id][name] = url
                count += 1
        except:
            pass
            
    save_data()
    bot.send_message(msg.chat.id, f"💾 تم استيراد {count} قناة بنجاح..")

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

print("🎬 Bot BeOut is running ...")
bot.polling(non_stop=True)

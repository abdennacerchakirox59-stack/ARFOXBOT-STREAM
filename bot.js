// ================= IMPORTS =================
const TeleBot = require("node-telegram-bot-api");
const { spawn } = require("child_process");
const axios = require("axios");
const fs = require("fs");

// ================= CONFIG =================
const BOT_TOKEN = "8970620272:AAE91-X9nNoJRS4mA_Qyd6OSF-Pa9a6EqwQ";
const bot = new TeleBot(BOT_TOKEN, { polling: true });

const DATA_FILE = "data.json";

// ================= JSON STORAGE LOGIC =================
function loadData() {
  if (fs.existsSync(DATA_FILE)) {
    try {
      const raw = fs.readFileSync(DATA_FILE, "utf-8");
      return JSON.parse(raw);
    } catch {
      return { pages: {}, channels: {} };
    }
  }
  return { pages: {}, channels: {} };
}

function saveData() {
  const data = {
    pages: userPages,
    channels: userM3u8,
  };
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 4), "utf-8");
}

// تهيئة البيانات من الملف عند تشغيل السكربت
const db = loadData();
let userPages = db.pages || {};
let userM3u8 = db.channels || {};
const activePage = {};
const userStreams = {};

// ================= DASH FIX =================
function fixDashUrl(url) {
  if (!url) return null;
  return url.replace(
    /https:\/\/[^@]*?(video|scontent)[\w\-\.]*\.fbcdn\.net/g,
    "https://BeOut@$1.xx.fbcdn.net"
  );
}

// ================= FACEBOOK API =================
async function getNewStream(chatId) {
  const chatIdStr = String(chatId);
  const pageName = activePage[chatId];

  if (!pageName || !userPages[chatIdStr] || !userPages[chatIdStr][pageName]) {
    return [null, null, null, null];
  }

  const page = userPages[chatIdStr][pageName];

  try {
    const createRes = await axios.post(
      `https://graph.facebook.com/v17.0/${page.page_id}/live_videos`,
      null,
      {
        params: {
          access_token: page.token,
          status: "UNPUBLISHED",
          title: "Forja TV Stream",
          description: "Live Stream via Forja Bot",
        },
        timeout: 15000,
      }
    );

    const liveId = createRes.data?.id;
    if (!liveId) return [null, null, null, null];

    const infoRes = await axios.get(
      `https://graph.facebook.com/v17.0/${liveId}`,
      {
        params: {
          access_token: page.token,
          fields: "stream_url,dash_preview_url",
        },
        timeout: 15000,
      }
    );

    const info = infoRes.data;
    return [
      info.stream_url || null,
      liveId,
      fixDashUrl(info.dash_preview_url || null),
      page.token,
    ];
  } catch (e) {
    console.error(`API Error: ${e.message}`);
    return [null, null, null, null];
  }
}

// ================= FFMPEG BASIC =================
function startFfmpeg(streamUrl, source) {
  const command = [
    "-re",
    "-i", source,
    "-c", "copy",
    "-f", "flv",
    "-flvflags", "no_duration_filesize",
    streamUrl,
  ];
  return spawn("ffmpeg", command, {
    stdio: ["ignore", "ignore", "ignore"],
  });
}

// ================= FFMPEG ADVANCED TRANSCODING PRO WITH FILTERS =================
function startFfmpegWithFilters(streamUrl, rtmpUrl, watermarkPath = null, overlayText = null) {
  const command = [
    "-re",
    "-i", streamUrl,
  ];

  const filters = [];

  if (watermarkPath) {
    command.push("-i", watermarkPath);
    filters.push("[1:v]scale=100:100[watermark];[0:v][watermark]overlay=10:10");
  }

  if (overlayText && overlayText.trim()) {
    const safeText = overlayText.replace(/['"]/g, "").replace(/:/g, "");
    const fontPath = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";
    filters.push(
      `drawtext=text='${safeText}':fontcolor=white:fontsize=24:x=10:y=H-40:fontfile=${fontPath}`
    );
  }

  if (filters.length > 0) {
    command.push("-filter_complex", filters.join(";"));
  }

  command.push(
    "-fflags", "+genpts+discardcorrupt",
    "-avoid_negative_ts", "make_zero",
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-tune", "zerolatency",
    "-b:v", "2000k",
    "-maxrate", "2000k",
    "-bufsize", "4000k",
    "-pix_fmt", "yuv420p",
    "-g", "60",
    "-c:a", "aac",
    "-b:a", "128k",
    "-ar", "44100",
    "-f", "flv",
    "-flvflags", "no_duration_filesize",
    rtmpUrl
  );

  return spawn("ffmpeg", command, {
    stdio: ["ignore", "ignore", "ignore"],
  });
}

// ================= STREAM THREAD =================
async function streamThread(chatId, source, name) {
  try {
    if (userStreams[chatId]?.[name]) {
      await stopStream(chatId, name);
    }

    const [streamUrl, liveId, dash, token] = await getNewStream(chatId);
    if (!streamUrl) {
      bot.sendMessage(
        chatId,
        `❌ فشل إنشاء بث لـ: ${name}\nتأكد من اختيار الصفحة الصحيحة بـ /usepage`
      );
      return;
    }

    const process = startFfmpeg(streamUrl, source);

    if (!userStreams[chatId]) userStreams[chatId] = {};
    userStreams[chatId][name] = {
      process,
      live_id: liveId,
      token,
      dash_url: dash,
    };

    let msg = `🚀 **بدأ البث بنجاح:**\n🎥 القناة: \`${name}\``;
    if (dash) {
      msg += `\n\n🔗 **رابط DASH للمعاينة:**\n\`${dash}\``;
    }

    bot.sendMessage(chatId, msg, { parse_mode: "Markdown" });
  } catch (e) {
    console.error(`Thread Error: ${e.message}`);
  }
}

// ================= STOP STREAM =================
async function stopStream(chatId, name) {
  const info = userStreams[chatId]?.[name];
  if (!info) return;

  try {
    info.process.kill("SIGKILL");
    await axios.delete(
      `https://graph.facebook.com/v17.0/${info.live_id}`,
      {
        params: { access_token: info.token },
        timeout: 5000,
      }
    );
  } catch {}

  delete userStreams[chatId][name];
  bot.sendMessage(chatId, `🛑 تم إيقاف: ${name}`);
}

// ================= /testall =================
bot.onText(/\/testall/, async (msg) => {
  const chatId = msg.chat.id;
  const streams = userStreams[chatId] || {};

  if (Object.keys(streams).length === 0) {
    bot.sendMessage(chatId, "❌ لا توجد قنوات تبث حالياً لفحصها.");
    return;
  }

  let statusMsg = "🧪 **فحص روابط DASH للبثوث النشطة:**\n\n";

  for (const [name, info] of Object.entries(streams)) {
    const dashUrl = info.dash_url;
    if (!dashUrl) {
      statusMsg += `⚪️ **${name}**: لا يوجد رابط DASH لهذا البث.\n`;
      continue;
    }

    try {
      const check = await axios.get(dashUrl, { timeout: 10000 });
      if (check.status === 200) {
        statusMsg += `✅ **${name}**: رابط DASH يعمل بنجاح.\n`;
      } else {
        statusMsg += `❌ **${name}**: رابط DASH لا يعمل (Error ${check.status}).\n`;
      }
    } catch {
      statusMsg += `❌ **${name}**: رابط DASH متعطل (خطأ اتصال).\n`;
    }
  }

  bot.sendMessage(chatId, statusMsg, { parse_mode: "Markdown" });
});

// ================= /testm3u8 =================
bot.onText(/\/testm3u8/, async (msg) => {
  const chatId = msg.chat.id;
  const chatIdStr = String(chatId);
  const savedChannels = userM3u8[chatIdStr] || {};

  if (Object.keys(savedChannels).length === 0) {
    bot.sendMessage(chatId, "❌ لا توجد قنوات محفوظة لفحصها. استخدم /savem3u8 أولاً.");
    return;
  }

  const waitMsg = await bot.sendMessage(chatId, "⏳ جاري فحص الروابط المحفوظة...");
  let report = "🧪 **تقرير فحص القنوات المحفوظة:**\n\n";

  for (const [name, url] of Object.entries(savedChannels)) {
    let linkType = "🔗 URL";
    if (url.toLowerCase().includes(".m3u8")) linkType = "🎥 M3U8";
    else if (url.toLowerCase().includes(".mpd")) linkType = "📦 MPD";

    try {
      let response;
      try {
        response = await axios.head(url, { timeout: 5000, maxRedirects: 5 });
      } catch {
        response = await axios.get(url, { timeout: 5000, responseType: "stream" });
        response.data.destroy();
      }

      if (response.status === 200) {
        report += `✅ **${name}**\n┗ النوع: \`${linkType}\` | الحالة: \`شغال\`\n\n`;
      } else {
        report += `❌ **${name}**\n┗ النوع: \`${linkType}\` | الحالة: \`خطأ ${response.status}\`\n\n`;
      }
    } catch {
      report += `⚠️ **${name}**\n┗ النوع: \`${linkType}\` | الحالة: \`غير مستجيب\`\n\n`;
    }
  }

  bot.deleteMessage(chatId, waitMsg.message_id);

  if (report.length > 4000) {
    for (let i = 0; i < report.length; i += 4000) {
      bot.sendMessage(chatId, report.slice(i, i + 4000), { parse_mode: "Markdown" });
    }
  } else {
    bot.sendMessage(chatId, report, { parse_mode: "Markdown" });
  }
});

// ================= /check =================
bot.onText(/\/check/, async (msg) => {
  const chatId = msg.chat.id;
  const chatIdStr = String(chatId);

  if (!userPages[chatIdStr] || Object.keys(userPages[chatIdStr]).length === 0) {
    bot.sendMessage(chatId, "❌ ليس لديك صفحات مسجلة للتحقق منها.");
    return;
  }

  let statusMsg = "🔍 **نتائج التحقق من التوكنات:**\n\n";

  for (const [name, data] of Object.entries(userPages[chatIdStr])) {
    try {
      const response = await axios.get("https://graph.facebook.com/me", {
        params: { access_token: data.token },
        timeout: 10000,
      });
      if (response.status === 200) {
        statusMsg += `✅ **${name}**: هذا التوكن شغال\n`;
      } else {
        statusMsg += `❌ **${name}**: هذا التوكن غير صالح\n`;
      }
    } catch {
      statusMsg += `⚠️ **${name}**: تعذر التحقق (خطأ في الاتصال)\n`;
    }
  }

  bot.sendMessage(chatId, statusMsg, { parse_mode: "Markdown" });
});

// ================= /addpage =================
bot.onText(/\/addpage (.+)/, (msg, match) => {
  try {
    const chatId = msg.chat.id;
    const chatIdStr = String(chatId);
    const parts = match[1].trim().split(/\s+/);

    if (parts.length < 3) throw new Error("Wrong format");

    const [name, pageId, token] = parts;
    if (!userPages[chatIdStr]) userPages[chatIdStr] = {};
    userPages[chatIdStr][name] = { page_id: pageId, token };
    saveData();
    bot.sendMessage(chatId, `✅ تم إضافة الصفحة \`${name}\` بنجاح.`, {
      parse_mode: "Markdown",
    });
  } catch {
    bot.sendMessage(msg.chat.id, "⚠️ الصيغة: `/addpage الاسم ID التوكن`", {
      parse_mode: "Markdown",
    });
  }
});

// ================= /usepage =================
bot.onText(/\/usepage(.*)/, (msg, match) => {
  try {
    const chatId = msg.chat.id;
    const chatIdStr = String(chatId);
    const name = match[1].trim();

    if (!name) {
      bot.sendMessage(chatId, "⚠️ أرسل: `/usepage اسم_الصفحة`", {
        parse_mode: "Markdown",
      });
      return;
    }

    if (userPages[chatIdStr]?.[name]) {
      activePage[chatId] = name;
      bot.sendMessage(chatId, `🎯 الصفحة النشطة الآن: \`${name}\``, {
        parse_mode: "Markdown",
      });
    } else {
      bot.sendMessage(chatId, `❌ الصفحة \`${name}\` غير موجودة.`);
    }
  } catch (e) {
    bot.sendMessage(msg.chat.id, `❌ حدث خطأ: ${e.message}`);
  }
});

// ================= /savem3u8 =================
bot.onText(/\/savem3u8 (.+)/, (msg, match) => {
  try {
    const chatId = msg.chat.id;
    const chatIdStr = String(chatId);
    const parts = match[1].trim().split(/\s+/);

    if (parts.length < 2) throw new Error("Wrong format");

    const name = parts[0];
    const url = parts.slice(1).join(" ");
    if (!userM3u8[chatIdStr]) userM3u8[chatIdStr] = {};
    userM3u8[chatIdStr][name] = url;
    saveData();
    bot.sendMessage(chatId, `💾 تم حفظ القناة: \`${name}\``, {
      parse_mode: "Markdown",
    });
  } catch {
    bot.sendMessage(msg.chat.id, "⚠️ الصيغة: `/savem3u8 الاسم الرابط`", {
      parse_mode: "Markdown",
    });
  }
});

// ================= /m3u8list =================
bot.onText(/\/m3u8list/, (msg) => {
  const chatId = msg.chat.id;
  const chatIdStr = String(chatId);
  const data = userM3u8[chatIdStr];

  if (!data || Object.keys(data).length === 0) {
    bot.sendMessage(chatId, "❌ قائمة القنوات فارغة.");
    return;
  }

  let txt = "📺 **القنوات المحفوظة:**\n";
  for (const name of Object.keys(data)) {
    txt += `- \`${name}\`\n`;
  }
  bot.sendMessage(chatId, txt, { parse_mode: "Markdown" });
});

// ================= /stopall =================
bot.onText(/\/stopall/, async (msg) => {
  const chatId = msg.chat.id;
  const streams = userStreams[chatId] || {};

  if (Object.keys(streams).length === 0) {
    bot.sendMessage(chatId, "❌ لا توجد بثوث نشطة.");
    return;
  }

  for (const name of Object.keys({ ...streams })) {
    await stopStream(chatId, name);
  }

  bot.sendMessage(chatId, "🛑 تم تنظيف الرام وإيقاف جميع العمليات.");
});

// ================= HANDLE TXT FILE UPLOAD =================
bot.on("document", async (msg) => {
  const doc = msg.document;
  if (!doc.file_name?.toLowerCase().endsWith(".txt")) return;

  try {
    const chatId = msg.chat.id;
    const chatIdStr = String(chatId);
    const fileLink = await bot.getFileLink(doc.file_id);
    const res = await axios.get(fileLink, { responseType: "text" });
    const content = res.data;

    if (!userM3u8[chatIdStr]) userM3u8[chatIdStr] = {};
    let count = 0;

    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (line && line.includes(" ")) {
        const spaceIdx = line.indexOf(" ");
        const name = line.slice(0, spaceIdx);
        const url = line.slice(spaceIdx + 1).trim();
        if (url.startsWith("http")) {
          userM3u8[chatIdStr][name] = url;
          count++;
        }
      }
    }

    saveData();
    bot.sendMessage(chatId, `💾 تم استيراد ${count} قناة بنجاح.`);
  } catch (e) {
    bot.sendMessage(msg.chat.id, `❌ خطأ في الملف: ${e.message}`);
  }
});

// ================= CATCH-ALL: START STREAM BY CHANNEL NAME =================
bot.on("message", async (msg) => {
  if (msg.text?.startsWith("/")) return;
  if (msg.document) return;

  const chatId = msg.chat.id;

  if (!activePage[chatId]) {
    bot.sendMessage(chatId, "⚠️ اختر صفحة أولاً باستخدام `/usepage`", {
      parse_mode: "Markdown",
    });
    return;
  }

  const chatIdStr = String(chatId);
  const saved = userM3u8[chatIdStr] || {};
  const names = (msg.text || "").split("\n");
  let startedCount = 0;

  for (const rawName of names) {
    const n = rawName.trim();
    if (n && saved[n]) {
      streamThread(chatId, saved[n], n);
      startedCount++;
    }
  }

  if (startedCount === 0) {
    bot.sendMessage(chatId, "❌ لم يتم العثور على اسم قناة مطابق.");
  }
});

// ================= STARTUP =================
console.log("🎬 Bot ZenGo is Running ...");

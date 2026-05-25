const BOT_NAME = "kartinkomet";
const IMAGE_DISLIKE_LIMIT = 2;
const JOKE_DISLIKE_LIMIT = 2;
const HISTORY_LIMIT = 35;

const MENU_TEXT = `<b>🎛 Пульт ${BOT_NAME}</b>
один экран, все рычаги

<b>🎲 Рандом</b>
пикчи и анекдоты из общего пула

<b>📥 Загрузка</b>
пикчи и анекдоты принимаю в личке`;

const START_TEXT = `<b>Я @kartinkomet_bot</b>
таскаю случайные пикчи и анекдоты из общего склада

Жми кнопки ниже или используй команды`;

const PRIVATE_UPLOAD_TEXT = `<b>📥 Загрузка пикч включена</b>

Кидайте одну пикчу, пачку, альбом или пересланные изображения

Когда всё закинули — /done
Если передумали — /cancel`;

const PRIVATE_JOKE_UPLOAD_TEXT = `<b>📝 Загрузка анекдотов включена</b>

Кидайте анекдоты текстом, по одному сообщению

Когда всё закинули — /done
Если передумали — /cancel`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET") {
      return json({ ok: true, bot: BOT_NAME, status: "alive" });
    }

    if (request.method !== "POST" || url.pathname !== "/webhook") {
      return json({ ok: false, error: "not_found" }, 404);
    }

    const headerSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (env.WEBHOOK_SECRET && headerSecret !== env.WEBHOOK_SECRET) {
      return json({ ok: false, error: "bad_secret" }, 401);
    }

    try {
      const update = await request.json();
      await ensureSchema(env.DB);
      await handleUpdate(update, env);
      return json({ ok: true });
    } catch (error) {
      console.error("webhook_error", error);
      return json({ ok: true });
    }
  },
};

async function handleUpdate(update, env) {
  if (update.callback_query) {
    await handleCallback(update.callback_query, env);
    return;
  }

  if (update.message) {
    await handleMessage(update.message, env);
  }
}

async function handleMessage(message, env) {
  const chat = message.chat;
  const from = message.from || {};
  const text = (message.text || message.caption || "").trim();
  const command = parseCommand(text);

  if (command === "/start") {
    await sendMessage(env, chat.id, START_TEXT, mainMenuKeyboard(chat.type));
    return;
  }

  if (command === "/menu") {
    await sendMessage(env, chat.id, MENU_TEXT, mainMenuKeyboard(chat.type));
    return;
  }

  if (command === "/pic") {
    await sendRandomImage(env, chat.id);
    return;
  }

  if (command === "/joke") {
    await sendRandomJoke(env, chat.id);
    return;
  }

  if (command === "/count") {
    await sendCount(env, chat.id);
    return;
  }

  if (command === "/stats") {
    await sendStats(env, chat.id);
    return;
  }

  if (command === "/upload_pidor") {
    await startUpload(env, message, "image");
    return;
  }

  if (command === "/upload_joke") {
    await startUpload(env, message, "joke");
    return;
  }

  if (command === "/done") {
    await finishUpload(env, message);
    return;
  }

  if (command === "/cancel") {
    await cancelUpload(env, message);
    return;
  }

  if (chat.type === "private") {
    if (message.photo) {
      await maybeStoreImage(env, message);
      return;
    }

    if (message.text && !message.text.startsWith("/")) {
      await maybeStoreJoke(env, message);
    }
  }
}

async function handleCallback(callback, env) {
  const data = callback.data || "";
  const message = callback.message;
  const chatId = message?.chat?.id;
  const userId = callback.from?.id;

  await answerCallback(env, callback.id);

  if (!chatId) return;

  if (data === "menu") {
    await editOrSendMessage(env, chatId, message.message_id, MENU_TEXT, mainMenuKeyboard(message.chat.type));
    return;
  }

  if (data === "pic") {
    await sendRandomImage(env, chatId);
    return;
  }

  if (data === "joke") {
    await sendRandomJoke(env, chatId);
    return;
  }

  if (data === "count") {
    await sendCount(env, chatId);
    return;
  }

  if (data === "stats") {
    await sendStats(env, chatId);
    return;
  }

  if (data === "upload_info") {
    await sendMessage(
      env,
      chatId,
      `<b>📬 Загрузка в личке</b>

Открой @kartinkomet_bot и отправь /upload_pidor для пикч или /upload_joke для анекдотов`,
      undefined,
    );
    return;
  }

  if (data === "upload_hint_private") {
    await sendMessage(
      env,
      chatId,
      `<b>📥 Что грузим?</b>

Пикчи: /upload_pidor
Анекдоты: /upload_joke`,
    );
    return;
  }

  if (data.startsWith("react:")) {
    await handleReaction(env, callback, data, userId);
  }
}

async function startUpload(env, message, mode) {
  if (message.chat.type !== "private") {
    await sendMessage(
      env,
      message.chat.id,
      `<b>📬 Загрузка только в личке</b>

Открой @kartinkomet_bot и там отправь ${mode === "image" ? "/upload_pidor" : "/upload_joke"}`,
    );
    return;
  }

  const now = unix();
  await env.DB.prepare(
    `INSERT OR REPLACE INTO upload_sessions
      (user_id, chat_id, mode, added_count, failed_count, created_at, updated_at)
     VALUES (?, ?, ?, 0, 0, ?, ?)`,
  )
    .bind(message.from.id, message.chat.id, mode, now, now)
    .run();

  await sendMessage(env, message.chat.id, mode === "image" ? PRIVATE_UPLOAD_TEXT : PRIVATE_JOKE_UPLOAD_TEXT);
}

async function finishUpload(env, message) {
  const session = await findAnySession(env.DB, message.from.id);
  if (!session) {
    await sendMessage(env, message.chat.id, "⚠️ Загрузка сейчас не открыта");
    return;
  }

  await env.DB.prepare("DELETE FROM upload_sessions WHERE user_id = ? AND mode = ?")
    .bind(message.from.id, session.mode)
    .run();

  const noun = session.mode === "image" ? "пикч" : "анекдотов";
  await sendMessage(
    env,
    message.chat.id,
    `<b>✅ Загрузка завершена</b>

Добавлено ${noun}: <b>${session.added_count}</b>
Не принято: <b>${session.failed_count}</b>`,
  );
}

async function cancelUpload(env, message) {
  const session = await findAnySession(env.DB, message.from.id);
  if (!session) {
    await sendMessage(env, message.chat.id, "⚠️ Отменять нечего, загрузка сейчас не открыта");
    return;
  }

  await env.DB.prepare("DELETE FROM upload_sessions WHERE user_id = ? AND mode = ?")
    .bind(message.from.id, session.mode)
    .run();

  await sendMessage(env, message.chat.id, "❌ Загрузка отменена");
}

async function maybeStoreImage(env, message) {
  const session = await getSession(env.DB, message.from.id, "image");
  if (!session) return;

  const photo = message.photo.at(-1);
  const name = displayName(message.from);
  const now = unix();

  try {
    await env.DB.prepare(
      `INSERT OR IGNORE INTO images
        (file_id, unique_file_id, added_by, added_by_name, active, shown_count, created_at)
       VALUES (?, ?, ?, ?, 1, 0, ?)`,
    )
      .bind(photo.file_id, photo.file_unique_id || null, message.from.id, name, now)
      .run();

    await incrementSession(env.DB, message.from.id, "image", "added_count");
  } catch (error) {
    console.error("store_image_error", error);
    await incrementSession(env.DB, message.from.id, "image", "failed_count");
  }
}

async function maybeStoreJoke(env, message) {
  const session = await getSession(env.DB, message.from.id, "joke");
  if (!session) return;

  const text = message.text.trim();
  if (text.length < 3) {
    await incrementSession(env.DB, message.from.id, "joke", "failed_count");
    return;
  }

  const now = unix();
  try {
    await env.DB.prepare(
      `INSERT OR IGNORE INTO jokes
        (text, added_by, added_by_name, active, shown_count, created_at)
       VALUES (?, ?, ?, 1, 0, ?)`,
    )
      .bind(text, message.from.id, displayName(message.from), now)
      .run();
    await incrementSession(env.DB, message.from.id, "joke", "added_count");
  } catch (error) {
    console.error("store_joke_error", error);
    await incrementSession(env.DB, message.from.id, "joke", "failed_count");
  }
}

async function sendRandomImage(env, chatId) {
  const image = await pickRandom(env.DB, chatId, "image", "images");
  if (!image) {
    await sendMessage(env, chatId, "📭 Пул пикч пуст\n\nЗакинь первую через /upload_pidor в личке");
    return;
  }

  await env.DB.prepare("UPDATE images SET shown_count = shown_count + 1 WHERE id = ?").bind(image.id).run();
  await rememberRandom(env.DB, chatId, "image", image.id);

  await sendPhoto(env, chatId, image.file_id, randomCaption(), imageKeyboard(image.id, 0, 0));
}

async function sendRandomJoke(env, chatId) {
  const joke = await pickRandom(env.DB, chatId, "joke", "jokes");
  if (!joke) {
    await sendMessage(env, chatId, "📭 Пул анекдотов пуст\n\nЗакинь первый через /upload_joke в личке");
    return;
  }

  await env.DB.prepare("UPDATE jokes SET shown_count = shown_count + 1 WHERE id = ?").bind(joke.id).run();
  await rememberRandom(env.DB, chatId, "joke", joke.id);

  await sendMessage(env, chatId, formatJoke(joke.text), jokeKeyboard(joke.id, 0, 0));
}

async function handleReaction(env, callback, data, userId) {
  const [, contentType, rawId, reaction] = data.split(":");
  const contentId = Number(rawId);
  const table = contentType === "image" ? "images" : "jokes";
  const limit = contentType === "image" ? IMAGE_DISLIKE_LIMIT : JOKE_DISLIKE_LIMIT;

  if (!Number.isFinite(contentId) || !["like", "dislike"].includes(reaction)) return;

  await env.DB.prepare(
    `INSERT INTO reactions (content_type, content_id, user_id, reaction, updated_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(content_type, content_id, user_id)
     DO UPDATE SET reaction = excluded.reaction, updated_at = excluded.updated_at`,
  )
    .bind(contentType, contentId, userId, reaction, unix())
    .run();

  const counts = await reactionCounts(env.DB, contentType, contentId);

  if (counts.dislikes >= limit) {
    await env.DB.prepare(`UPDATE ${table} SET active = 0 WHERE id = ?`).bind(contentId).run();
    await editReplyMarkup(env, callback.message.chat.id, callback.message.message_id, null);
    await sendMessage(
      env,
      callback.message.chat.id,
      contentType === "image"
        ? "🖕🏻 Народный суд вынес приговор. Пикча удалена из пула"
        : "🖕🏻 Народный суд вынес приговор. Анекдот удалён из пула",
    );
    return;
  }

  const keyboard = contentType === "image"
    ? imageKeyboard(contentId, counts.likes, counts.dislikes)
    : jokeKeyboard(contentId, counts.likes, counts.dislikes);
  await editReplyMarkup(env, callback.message.chat.id, callback.message.message_id, keyboard);
}

async function sendCount(env, chatId) {
  const images = await scalar(env.DB, "SELECT COUNT(*) FROM images WHERE active = 1");
  const jokes = await scalar(env.DB, "SELECT COUNT(*) FROM jokes WHERE active = 1");
  await sendMessage(
    env,
    chatId,
    `<b>📦 Склад ${BOT_NAME}</b>

🖼 Пикч внутри: <b>${images}</b>
😂 Анекдотов внутри: <b>${jokes}</b>`,
  );
}

async function sendStats(env, chatId) {
  const images = await scalar(env.DB, "SELECT COUNT(*) FROM images WHERE active = 1");
  const jokes = await scalar(env.DB, "SELECT COUNT(*) FROM jokes WHERE active = 1");
  const imageShots = await scalar(env.DB, "SELECT COALESCE(SUM(shown_count), 0) FROM images");
  const jokeShots = await scalar(env.DB, "SELECT COALESCE(SUM(shown_count), 0) FROM jokes");
  const likes = await scalar(env.DB, "SELECT COUNT(*) FROM reactions WHERE reaction = 'like'");
  const dislikes = await scalar(env.DB, "SELECT COUNT(*) FROM reactions WHERE reaction = 'dislike'");

  await sendMessage(
    env,
    chatId,
    `<b>📊 Сводка ${BOT_NAME}</b>

<b>📦 Пул</b>
🖼 Пикч: <b>${images}</b>
😂 Анекдотов: <b>${jokes}</b>

<b>🎲 Рандом</b>
🖼 Выстрелов пикч: <b>${imageShots}</b>
😂 Выстрелов шуток: <b>${jokeShots}</b>

<b>🧪 Реакции</b>
🤙🏻 Одобрений: <b>${likes}</b>
🖕🏻 Приговоров: <b>${dislikes}</b>`,
  );
}

async function pickRandom(db, chatId, contentType, table) {
  const recent = await db.prepare(
    `SELECT content_id FROM random_history
     WHERE chat_id = ? AND content_type = ?
     ORDER BY created_at DESC
     LIMIT ?`,
  )
    .bind(chatId, contentType, HISTORY_LIMIT)
    .all();

  const ids = recent.results.map((row) => row.content_id);
  let query = `SELECT * FROM ${table} WHERE active = 1`;
  const params = [];

  if (ids.length) {
    query += ` AND id NOT IN (${ids.map(() => "?").join(",")})`;
    params.push(...ids);
  }

  query += " ORDER BY shown_count ASC, RANDOM() LIMIT 1";
  let result = await db.prepare(query).bind(...params).first();

  if (!result) {
    result = await db.prepare(`SELECT * FROM ${table} WHERE active = 1 ORDER BY shown_count ASC, RANDOM() LIMIT 1`).first();
  }

  return result;
}

async function rememberRandom(db, chatId, contentType, contentId) {
  const now = unix();
  await db.prepare("INSERT INTO random_history (chat_id, content_type, content_id, created_at) VALUES (?, ?, ?, ?)")
    .bind(chatId, contentType, contentId, now)
    .run();
  await db.prepare(
    `DELETE FROM random_history
     WHERE rowid NOT IN (
       SELECT rowid FROM random_history
       WHERE chat_id = ? AND content_type = ?
       ORDER BY created_at DESC
       LIMIT 80
     ) AND chat_id = ? AND content_type = ?`,
  )
    .bind(chatId, contentType, chatId, contentType)
    .run();
}

function mainMenuKeyboard(chatType) {
  const uploadButton = chatType === "private"
    ? { text: "📥 Залить пикчи", callback_data: "upload_hint_private" }
    : { text: "📬 Загрузка в личке", callback_data: "upload_info" };

  return {
    inline_keyboard: [
      [
        { text: "🎲 Пикча", callback_data: "pic" },
        { text: "😂 Анекдот", callback_data: "joke" },
      ],
      [
        { text: "📦 Склад", callback_data: "count" },
        { text: "📊 Статы", callback_data: "stats" },
      ],
      [uploadButton],
    ],
  };
}

function imageKeyboard(id, likes, dislikes) {
  return {
    inline_keyboard: [
      [
        { text: `🤙🏻 ${likes}`, callback_data: `react:image:${id}:like` },
        { text: `🖕🏻 ${dislikes}`, callback_data: `react:image:${id}:dislike` },
      ],
      [
        { text: "🎲 Ещё", callback_data: "pic" },
        { text: "🎛 Пульт", callback_data: "menu" },
      ],
    ],
  };
}

function jokeKeyboard(id, likes, dislikes) {
  return {
    inline_keyboard: [
      [
        { text: `🤙🏻 ${likes}`, callback_data: `react:joke:${id}:like` },
        { text: `🖕🏻 ${dislikes}`, callback_data: `react:joke:${id}:dislike` },
      ],
      [
        { text: "😂 Ещё", callback_data: "joke" },
        { text: "🎛 Пульт", callback_data: "menu" },
      ],
    ],
  };
}

async function getSession(db, userId, mode) {
  return db.prepare("SELECT * FROM upload_sessions WHERE user_id = ? AND mode = ?").bind(userId, mode).first();
}

async function findAnySession(db, userId) {
  return db.prepare("SELECT * FROM upload_sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1").bind(userId).first();
}

async function incrementSession(db, userId, mode, column) {
  await db.prepare(`UPDATE upload_sessions SET ${column} = ${column} + 1, updated_at = ? WHERE user_id = ? AND mode = ?`)
    .bind(unix(), userId, mode)
    .run();
}

async function reactionCounts(db, contentType, contentId) {
  const rows = await db.prepare(
    `SELECT reaction, COUNT(*) AS count
     FROM reactions
     WHERE content_type = ? AND content_id = ?
     GROUP BY reaction`,
  )
    .bind(contentType, contentId)
    .all();
  const counts = { likes: 0, dislikes: 0 };
  for (const row of rows.results) {
    if (row.reaction === "like") counts.likes = row.count;
    if (row.reaction === "dislike") counts.dislikes = row.count;
  }
  return counts;
}

async function scalar(db, sql) {
  const row = await db.prepare(sql).first();
  return Object.values(row || { count: 0 })[0] || 0;
}

async function ensureSchema(db) {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS images (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_id TEXT NOT NULL UNIQUE,
      unique_file_id TEXT,
      added_by INTEGER,
      added_by_name TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      shown_count INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS jokes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL UNIQUE,
      added_by INTEGER,
      added_by_name TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      shown_count INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS reactions (
      content_type TEXT NOT NULL,
      content_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      reaction TEXT NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (content_type, content_id, user_id)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS upload_sessions (
      user_id INTEGER NOT NULL,
      chat_id INTEGER NOT NULL,
      mode TEXT NOT NULL,
      added_count INTEGER NOT NULL DEFAULT 0,
      failed_count INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, mode)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS random_history (
      chat_id INTEGER NOT NULL,
      content_type TEXT NOT NULL,
      content_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL
    )`),
  ]);
}

async function telegram(env, method, payload) {
  const response = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    console.error("telegram_error", method, response.status, await response.text());
  }
  return response;
}

async function sendMessage(env, chatId, text, replyMarkup) {
  return telegram(env, "sendMessage", {
    chat_id: chatId,
    text,
    parse_mode: "HTML",
    disable_web_page_preview: true,
    reply_markup: replyMarkup,
  });
}

async function editOrSendMessage(env, chatId, messageId, text, replyMarkup) {
  const response = await telegram(env, "editMessageText", {
    chat_id: chatId,
    message_id: messageId,
    text,
    parse_mode: "HTML",
    disable_web_page_preview: true,
    reply_markup: replyMarkup,
  });

  if (!response.ok) {
    await sendMessage(env, chatId, text, replyMarkup);
  }
}

async function sendPhoto(env, chatId, photo, caption, replyMarkup) {
  return telegram(env, "sendPhoto", {
    chat_id: chatId,
    photo,
    caption,
    parse_mode: "HTML",
    reply_markup: replyMarkup,
  });
}

async function editReplyMarkup(env, chatId, messageId, replyMarkup) {
  return telegram(env, "editMessageReplyMarkup", {
    chat_id: chatId,
    message_id: messageId,
    reply_markup: replyMarkup,
  });
}

async function answerCallback(env, callbackQueryId) {
  return telegram(env, "answerCallbackQuery", { callback_query_id: callbackQueryId });
}

function parseCommand(text) {
  if (!text.startsWith("/")) return "";
  return text.split(/\s+/)[0].split("@")[0].toLowerCase();
}

function formatJoke(text) {
  return `<b>😂 Анекдот</b>

<blockquote>${escapeHtml(text)}</blockquote>`;
}

function randomCaption() {
  const captions = [
    "Картинка нашла своего зрителя",
    "Пул выдал визуальный аргумент",
    "Рандом достал это со склада",
    "Экспонат прибыл без объяснений",
    "Сомнительный файл вышел к людям",
    "Визуальный шум доставлен",
  ];
  return captions[Math.floor(Math.random() * captions.length)];
}

function displayName(user) {
  if (user.username) return user.username;
  return [user.first_name, user.last_name].filter(Boolean).join(" ") || String(user.id);
}

function unix() {
  return Math.floor(Date.now() / 1000);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

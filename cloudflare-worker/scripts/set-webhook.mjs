const workerUrl = process.env.WORKER_URL;
const botToken = process.env.BOT_TOKEN;
const webhookSecret = process.env.WEBHOOK_SECRET;

if (!workerUrl || !botToken || !webhookSecret) {
  console.error("Need WORKER_URL, BOT_TOKEN and WEBHOOK_SECRET");
  process.exit(1);
}

const url = new URL(`https://api.telegram.org/bot${botToken}/setWebhook`);
url.searchParams.set("url", `${workerUrl.replace(/\/$/, "")}/webhook`);
url.searchParams.set("secret_token", webhookSecret);
url.searchParams.set("drop_pending_updates", "true");

const response = await fetch(url);
const body = await response.text();
console.log(body);

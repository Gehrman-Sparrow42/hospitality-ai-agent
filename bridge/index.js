import pkg from "whatsapp-web.js";
const { Client, LocalAuth } = pkg;
import qrcodeTerminal from "qrcode-terminal";
import QRCode from "qrcode";
import axios from "axios";
import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import path from "path";
import fs from "fs";
import crypto from "crypto";
import { fileURLToPath } from "url";

// Load environment variables
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
dotenv.config({ path: path.resolve(__dirname, "../.env") });
dotenv.config(); // fallback to local .env

const BACKEND_WEBHOOK_URL =
  process.env.BACKEND_WEBHOOK_URL || "http://127.0.0.1:8000/webhook";
const WEBHOOK_TIMEOUT_MS =
  parseInt(process.env.WEBHOOK_TIMEOUT_MS, 10) || 60000;
const AUTH_DATA_PATH =
  process.env.AUTH_DATA_PATH || path.resolve(__dirname, "./.wwebjs_auth");
const BRIDGE_API_PORT =
  parseInt(process.env.BRIDGE_API_PORT, 10) || 3001;

const AUDIT_LOG_PATH =
  process.env.AUDIT_LOG_PATH || path.resolve(__dirname, "bot_audit.log");

/**
 * Automatically ensures session folders, bot_audit.log, and .env files are in .gitignore
 */
function ensureGitignorePatterns() {
  try {
    const candidatePaths = [
      path.resolve(__dirname, "..", ".gitignore"),
      path.resolve(__dirname, ".gitignore"),
      path.resolve(process.cwd(), ".gitignore"),
    ];
    const requiredPatterns = [
      ".env",
      "*.env",
      "bot_audit.log",
      "*/bot_audit.log",
      ".wwebjs_auth/",
      "auth_info/",
      "session/",
      "*/.wwebjs_auth/",
      "*/auth_info/",
      "*/session/",
    ];
    for (const gPath of candidatePaths) {
      if (fs.existsSync(gPath)) {
        let content = fs.readFileSync(gPath, "utf-8");
        let modified = false;
        for (const pattern of requiredPatterns) {
          if (!content.includes(pattern)) {
            content += `\n${pattern}`;
            modified = true;
          }
        }
        if (modified) {
          fs.writeFileSync(gPath, content, "utf-8");
        }
      }
    }
  } catch (err) {}
}
ensureGitignorePatterns();

/**
 * Ensures POSIX directory permissions are strictly 0700 (owner only)
 * for session and authentication materials.
 */
function secureAuthDirectoryPermissions(dirPath) {
  try {
    if (!fs.existsSync(dirPath)) {
      fs.mkdirSync(dirPath, { recursive: true, mode: 0o700 });
    }
    if (process.platform !== "win32") {
      fs.chmodSync(dirPath, 0o700);
      try {
        const items = fs.readdirSync(dirPath, { withFileTypes: true });
        for (const item of items) {
          const itemPath = path.join(dirPath, item.name);
          if (item.isDirectory()) {
            secureAuthDirectoryPermissions(itemPath);
          } else {
            fs.chmodSync(itemPath, 0o600);
          }
        }
      } catch (childErr) {}
    }
  } catch (err) {
    console.warn("[SEC_AUTH_WARN] Could not set 0700 permissions on auth dir:", err.message);
  }
}

// Initial security sweep on session auth storage
[
  AUTH_DATA_PATH,
  path.resolve(__dirname, "auth_info"),
  path.resolve(__dirname, "session"),
].forEach((p) => {
  if (fs.existsSync(p)) {
    secureAuthDirectoryPermissions(p);
  }
});

/**
 * Reads the last non-empty line of the audit log file to extract its entry_hash.
 */
async function getLastAuditEntryHash(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return "0".repeat(64);
    }
    const stat = await fs.promises.stat(filePath);
    if (stat.size === 0) {
      return "0".repeat(64);
    }
    const content = await fs.promises.readFile(filePath, "utf-8");
    const lines = content.trim().split("\n").filter((l) => l.trim().length > 0);
    if (lines.length === 0) {
      return "0".repeat(64);
    }
    const lastLine = lines[lines.length - 1];
    try {
      const data = JSON.parse(lastLine);
      if (data.entry_hash) return String(data.entry_hash).trim();
      if (data.hash) return String(data.hash).trim();
    } catch (e) {}
    return crypto.createHash("sha256").update(lastLine).digest("hex");
  } catch (err) {
    return "0".repeat(64);
  }
}

/**
 * Asynchronously writes an outgoing bot message entry to bot_audit.log in JSON Lines (jsonl) format
 * using a cryptographic SHA-256 hash chain (blockchain-like Merkle continuity).
 * Strict append-only: opens with append mode for kernel chattr +a compatibility.
 */
async function appendAuditLog(recipientJid, messageContent, status = "SENT") {
  try {
    const prevHash = await getLastAuditEntryHash(AUDIT_LOG_PATH);
    const nowIso = new Date().toISOString();
    const recClean = String(recipientJid || "").trim();
    const msgClean = String(messageContent || "").trim();
    const stClean = String(status || "SENT").trim().toUpperCase();

    const payload = `${prevHash}:${nowIso}:${recClean}:${msgClean}:${stClean}`;
    const entryHash = crypto.createHash("sha256").update(payload, "utf-8").digest("hex");

    const entry = {
      timestamp: nowIso,
      recipient_jid: recClean,
      message_preview: msgClean,
      status: stClean,
      prev_hash: prevHash,
      entry_hash: entryHash,
    };
    const line = JSON.stringify(entry) + "\n";
    await fs.promises.appendFile(AUDIT_LOG_PATH, line, { encoding: "utf-8" });
  } catch (err) {
    console.warn("[AUDIT_LOG_WARN] Failed to write bot_audit.log:", err.message);
  }
}

let TRIGGER_PREFIX =
  process.env.TRIGGER_PREFIX !== undefined ? process.env.TRIGGER_PREFIX : "-test";

// State management
let client = null;
let bridgeState = "DISCONNECTED"; // DISCONNECTED | INITIALIZING | QR_READY | PAIRING_CODE_READY | AUTHENTICATED | CONNECTED
let currentQR = null;
let currentQRDataURL = null;
let currentPairingCode = null;
let currentPairingPhone = null;
let connectedUser = null;
let recentLogs = [];

// Global Filter & Behavior Configuration
let FILTER_CONFIG = {
  only_unknown_contacts: false,
  blacklist: [],
  debounce_seconds: 30,
  admin_notify_phone: "",
  trigger_prefix: TRIGGER_PREFIX || "-test",
};

// Smart Debounce Map: chatId -> { messages: string[], msgObj: any, timer: Timeout, firstTime: number }
const debounceBuffers = new Map();

function addLog(type, title, detail = "") {
  const logItem = {
    id: Date.now() + Math.random().toString(36).substring(2, 6),
    timestamp: new Date().toLocaleTimeString(),
    type, // 'info' | 'success' | 'warn' | 'error' | 'message'
    title,
    detail,
  };
  recentLogs.push(logItem);
  if (recentLogs.length > 50) {
    recentLogs.shift();
  }
}

function cleanChromiumLocks() {
  try {
    const sessionDir = path.join(AUTH_DATA_PATH, "session");
    if (fs.existsSync(sessionDir)) {
      const lockFiles = ["SingletonLock", "SingletonSocket", "SingletonCookie"];
      for (const lock of lockFiles) {
        const p = path.join(sessionDir, lock);
        if (fs.existsSync(p)) {
          try { fs.unlinkSync(p); } catch (e) {}
        }
      }
    }
  } catch (err) {}
}

// WhatsApp Client Initializer
async function initializeWhatsAppClient(force = false, pairPhoneNumber = null) {
  if (!force && bridgeState === "INITIALIZING" && client) {
    console.log("[INFO] WhatsApp client is already initializing...");
    return;
  }

  if (client) {
    try {
      if (client.pupBrowser) {
        try { await client.pupBrowser.close(); } catch (e) {}
      }
      await client.destroy();
    } catch (e) {
      console.warn("[WARN] Error destroying previous client:", e.message);
    }
    client = null;
  }
  cleanChromiumLocks();

  bridgeState = "INITIALIZING";
  currentQR = null;
  currentQRDataURL = null;
  currentPairingCode = null;
  if (pairPhoneNumber) {
    currentPairingPhone = String(pairPhoneNumber).replace(/\D/g, "");
  }
  connectedUser = null;
  
  if (currentPairingPhone) {
    addLog("info", "Telefon Eşleştirmesi Başlatılıyor", `${currentPairingPhone} için 8 haneli kod isteniyor...`);
  } else {
    addLog("info", "WhatsApp İstemcisi Başlatılıyor", "Puppeteer ve LocalAuth yükleniyor...");
  }

  const clientOptions = {
    authStrategy: new LocalAuth({
      dataPath: AUTH_DATA_PATH,
    }),
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    webVersionCache: {
      type: "none",
    },
    puppeteer: {
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-zygote",
        "--disable-extensions",
        "--disable-accelerated-2d-canvas",
      ],
    },
  };


  client = new Client(clientOptions);

  // Event: QR Code received
  client.on("qr", async (qr) => {
    bridgeState = "QR_READY";
    currentQR = qr;
    try {
      currentQRDataURL = await QRCode.toDataURL(qr, { margin: 2, scale: 7 });
    } catch (err) {
      console.error("[ERROR] Failed to generate QR DataURL:", err);
    }

    console.log("\n[QR CODE] Scan the QR code below with your WhatsApp app:\n");
    qrcodeTerminal.generate(qr, { small: true });
    addLog("warn", "QR Kod Hazır", "WhatsApp ile QR kodunu taratmanız bekleniyor.");
  });

  // Event: Code Received (Pairing Code event)
  client.on("code", (code) => {
    bridgeState = "PAIRING_CODE_READY";
    currentPairingCode = code;
    console.log(`[PAIRING CODE EVENT] Received pairing code: ${code}`);
    addLog("warn", "Eşleştirme Kodu Hazır", `WhatsApp 8 haneli kod: ${code}`);
  });

  // Event: Loading screen during post-login sync
  client.on("loading_screen", (percent, message) => {
    console.log(`[SYNC LOADING] ${percent}%: ${message}`);
    addLog("info", "Oturum Eşitleniyor", `%${percent}: ${message}`);
  });

  // Event: State change
  client.on("change_state", (state) => {
    console.log(`[STATE CHANGE] WhatsApp state: ${state}`);
    addLog("info", "Durum Değişti", `Yeni durum: ${state}`);
  });

  // Event: Authentication successful
  client.on("authenticated", () => {
    bridgeState = "AUTHENTICATED";
    currentQR = null;
    currentQRDataURL = null;
    currentPairingCode = null;
    currentPairingPhone = null;
    console.log("[AUTH] WhatsApp authentication successful!");
    addLog("success", "Oturum Doğrulandı", "WhatsApp hesabı başarıyla bağlandı!");
    secureAuthDirectoryPermissions(AUTH_DATA_PATH);
  });

  // Event: Auth failure
  client.on("auth_failure", (msg) => {
    bridgeState = "DISCONNECTED";
    console.error("[ERROR] WhatsApp authentication failure:", typeof msg === "string" ? msg : "Auth rejected");
    addLog("error", "Doğrulama Hatası", typeof msg === "string" ? msg : "Doğrulama başarısız oldu.");
  });

  // Event: Client Ready
  client.on("ready", () => {
    bridgeState = "CONNECTED";
    currentQR = null;
    currentQRDataURL = null;

    try {
      const info = client.info;
      connectedUser = {
        name: info?.pushname || "WhatsApp Kullanıcısı",
        phone: info?.wid?.user || "Bilinmiyor",
        platform: info?.platform || "web",
      };
    } catch (e) {
      connectedUser = { name: "WhatsApp Kullanıcısı", phone: "Bilinmiyor" };
    }

    console.log("\n[READY] WhatsApp Web client is online and listening for messages!\n");
    addLog("success", "Bağlantı Aktif", `WhatsApp bağlı: ${connectedUser?.phone || 'Aktif'}`);
    secureAuthDirectoryPermissions(AUTH_DATA_PATH);
  });

  async function flushDebounceBuffer(chatId) {
    if (!debounceBuffers.has(chatId)) return;
    const bufferData = debounceBuffers.get(chatId);
    debounceBuffers.delete(chatId);

    const combinedMessage = bufferData.messages.join("\n").trim();
    const msg = bufferData.msgObj;

    if (!combinedMessage) return;

    console.log(`[DEBOUNCE_FLUSH] Dispatching ${bufferData.messages.length} lines for ${chatId}:\n"${combinedMessage}"`);
    addLog("message", `Gelen Mesaj (${chatId})`, `"${combinedMessage.substring(0, 90)}..." (${bufferData.messages.length} satır birleştirildi)`);

    try {
      const payload = {
        phone: chatId,
        message: combinedMessage,
      };

      const response = await axios.post(BACKEND_WEBHOOK_URL, payload, {
        timeout: WEBHOOK_TIMEOUT_MS,
        headers: { "Content-Type": "application/json" },
      });

      let replyText = response.data && response.data.reply;
      const isMuted = response.data && response.data.is_muted;
      const action = response.data && response.data.action;
      const alertDetails = response.data && response.data.alert_details;

      // Ensure no internal system tags or reasoning ever leak to the customer
      if (replyText) {
        replyText = replyText.replace(/<(?:think|reasoning|thought)[\s\S]*?<\/(?:think|reasoning|thought)>/gi, '');
        replyText = replyText.replace(/(?:\*{1,2}|_{1,2})?\[\s*(?:YETKILI|REZERVASYON|INSAN|LEAD|DEVRET)[\s\S]*?\](?:\*{1,2}|_{1,2})?/gi, '');
        replyText = replyText.replace(/\n{3,}/g, '\n\n').trim();
      }

      // 1. If AI generated a reply, send it
      if (replyText) {
        console.log(`[REPLY] To: ${chatId} | Text: "${replyText.substring(0, 80)}..."`);
        let sendSuccess = false;
        try {
          const chat = await msg.getChat();
          await chat.sendMessage(replyText);
          sendSuccess = true;
        } catch (errChat) {
          console.warn("[WARN] chat.sendMessage fallback to client.sendMessage:", errChat.message);
          try {
            await client.sendMessage(chatId, replyText);
            sendSuccess = true;
          } catch (errDirect) {
            console.error("[ERROR] Failed to send AI reply:", errDirect.message);
          }
        }

        // Asynchronously record outgoing message to bot_audit.log (non-blocking)
        appendAuditLog(chatId, replyText, sendSuccess ? "SENT" : "FAILED").catch(() => {});

        if (sendSuccess) {
          addLog("success", `AI Yanıtı Gönderildi (${chatId})`, `"${replyText.substring(0, 100)}..."`);
        } else {
          addLog("error", `AI Yanıtı Gönderilemedi (${chatId})`, `Mesaj iletimi başarısız.`);
        }
      }

      // 2. Admin Alert Dispatcher (for human intervention or reservation leads)
      if (action === "intervention_alert" || action === "reservation_alert") {
        const isRes = action === "reservation_alert";
        const alertTitle = isRes ? "📋 Yeni Rezervasyon Talebi" : "🔔 Yetkili Müdahalesi Gerekli";
        
        let displayPhone = chatId;
        try {
          const rawDigits = chatId.split("@")[0].replace(/[^\d]/g, "");
          if (rawDigits.length === 12 && rawDigits.startsWith("90")) {
            displayPhone = `+90 ${rawDigits.slice(2, 5)} ${rawDigits.slice(5, 8)} ${rawDigits.slice(8, 10)} ${rawDigits.slice(10, 12)}`;
          } else if (rawDigits.length >= 10) {
            displayPhone = `+${rawDigits}`;
          }
        } catch (_) {}

        const alertMsg = `${alertTitle}\n` +
          `Müşteri: ${displayPhone}\n` +
          `Detay: ${alertDetails || 'Talep alındı'}\n` +
          `Not: Bot 2 saat durduruldu, sohbeti devralabilirsiniz.`;

        // Determine destination: configured admin phone or self-chat
        let adminChat = FILTER_CONFIG.admin_notify_phone.trim();
        if (adminChat) {
          adminChat = adminChat.includes("@") ? adminChat : `${adminChat.replace(/[^0-9]/g, "")}@c.us`;
        } else if (connectedUser?.phone && connectedUser.phone !== "Bilinmiyor") {
          adminChat = `${connectedUser.phone.replace(/[^0-9]/g, "")}@c.us`;
        } else {
          adminChat = chatId;
        }

        console.log(`[ADMIN_ALERT] Sending alert to ${adminChat}: ${alertTitle}`);
        try {
          await client.sendMessage(adminChat, alertMsg);
          addLog("warn", "Admin Bildirimi İletildi", `WhatsApp uyarısı gönderildi -> ${adminChat}`);
        } catch (errAlert) {
          console.warn("[WARN] Could not send admin WhatsApp alert:", errAlert.message);
        }
      }
    } catch (error) {
      console.error("[ERROR] Debounce flush error:", error.message);
      if (error.code === "ECONNREFUSED") {
        addLog("error", "Backend Bağlantı Hatası", `FastAPI servisine (${BACKEND_WEBHOOK_URL}) erişilemiyor.`);
        const fallbackText = "Şu anda mesajınızı işlerken geçici bir aksaklık oluştu. Kamp koordinatörümüz en kısa sürede sizinle bu sohbet üzerinden iletişime geçecektir. 🏕️";
        let ok = false;
        try {
          await client.sendMessage(chatId, fallbackText);
          ok = true;
        } catch (e) {}
        appendAuditLog(chatId, fallbackText, ok ? "SENT" : "FAILED").catch(() => {});
      } else if (error.code === "ECONNABORTED" || error.message.includes("timeout")) {
        addLog("warn", "Zaman Aşımı", "FastAPI / Ollama istek zaman aşımına uğradı.");
        const timeoutText = "Yoğunluk nedeniyle kısa bir gecikme yaşandı. Talebinizi aldım, kamp yetkilimiz en kısa sürede bilgi verecektir. 🏕️";
        let ok = false;
        try {
          await client.sendMessage(chatId, timeoutText);
          ok = true;
        } catch (e) {}
        appendAuditLog(chatId, timeoutText, ok ? "SENT" : "FAILED").catch(() => {});
      } else {
        addLog("error", "İşleme Hatası", error.message);
      }
    }
  }

  // Core Message Handler
  async function handleIncomingMessage(msg) {
    try {
      // 1. Resolve chat identifier (supports both @c.us and @lid multi-device IDs)
      const chatId = msg.id?.remote || (msg.fromMe ? msg.to : msg.from) || msg.from;

      // 2. Filter out broadcasts and status updates
      if (!chatId || chatId === "status@broadcast" || chatId.includes("@broadcast")) {
        return;
      }

      // 3. Filter out group chats (only accept direct chats, reject @g.us)
      if (chatId.includes("@g.us") || msg.isGroupMsg) {
        return;
      }

      // 4. Filter out non-text media types (images, voice notes, stickers, documents)
      if (msg.hasMedia || msg.type !== "chat") {
        return;
      }

      // 5. Blacklist Check
      const cleanNum = chatId.replace(/[^0-9]/g, "");
      if (FILTER_CONFIG.blacklist && FILTER_CONFIG.blacklist.length > 0) {
        const isBlocked = FILTER_CONFIG.blacklist.some((b) => b && cleanNum.includes(b.replace(/[^0-9]/g, "")));
        if (isBlocked) {
          console.log(`[BLACKLIST] Ignored blacklisted contact: ${chatId}`);
          return;
        }
      }

      // 6. Only Unknown Contacts Check (Ignore friends / family in phonebook)
      if (FILTER_CONFIG.only_unknown_contacts && !msg.fromMe) {
        try {
          const contact = await msg.getContact();
          if (contact && contact.isMyContact) {
            console.log(`[CONTACT_FILTER] Ignored saved personal contact: ${contact.name || contact.pushname || chatId}`);
            return;
          }
        } catch (e) {
          console.warn("[WARN] Could not inspect contact book:", e.message);
        }
      }

      const rawBody = (msg.body || "").trim();
      if (!rawBody) {
        return;
      }

      let processedMessage = rawBody;

      // 7. Check Trigger Prefix
      if (TRIGGER_PREFIX) {
        const lowerRaw = rawBody.toLowerCase();
        const lowerPrefix = TRIGGER_PREFIX.toLowerCase();

        if (lowerRaw.startsWith(lowerPrefix)) {
          processedMessage = rawBody.slice(TRIGGER_PREFIX.length).trim();
          if (!processedMessage) {
            return;
          }
        } else if (lowerRaw === "/reset") {
          processedMessage = "/reset";
        } else {
          // Message does NOT start with trigger prefix -> Ignore completely
          return;
        }
      }

      // 8. Push to Smart 30-Second Debounce Buffer
      const debounceMs = Math.max(1000, (FILTER_CONFIG.debounce_seconds || 30) * 1000);

      if (debounceBuffers.has(chatId)) {
        const existing = debounceBuffers.get(chatId);
        clearTimeout(existing.timer);
        existing.messages.push(processedMessage);
        existing.msgObj = msg; // update latest message reference
        console.log(`[BUFFER] Appended message for ${chatId} (${existing.messages.length} in queue). Resetting ${FILTER_CONFIG.debounce_seconds}s timer.`);
        addLog("info", `Mesaj Tampona Eklendi (${chatId})`, `"${processedMessage}" (Toplam ${existing.messages.length} satır, ${FILTER_CONFIG.debounce_seconds}s bekleniyor)`);

        existing.timer = setTimeout(() => {
          flushDebounceBuffer(chatId);
        }, debounceMs);
      } else {
        console.log(`[BUFFER] Starting new ${FILTER_CONFIG.debounce_seconds}s debounce buffer for ${chatId}...`);
        addLog("info", `Mesaj Tampona Alındı (${chatId})`, `"${processedMessage}" (${FILTER_CONFIG.debounce_seconds}s birleştirme tamponu başladı)`);

        const bufferData = {
          messages: [processedMessage],
          msgObj: msg,
          firstTime: Date.now(),
          timer: setTimeout(() => {
            flushDebounceBuffer(chatId);
          }, debounceMs),
        };
        debounceBuffers.set(chatId, bufferData);
      }
    } catch (error) {
      console.error("[ERROR] Message handler error:", error.message);
    }
  }

  // Handle incoming messages from other contacts
  client.on("message", handleIncomingMessage);

  // Handle self-messages ("Message yourself" on the host phone) or outgoing trigger tests
  client.on("message_create", async (msg) => {
    const rawBody = (msg.body || "").trim();
    const chatId = msg.id?.remote || msg.to || msg.from || "";

    // Ignore broadcasts or status updates
    if (!chatId || chatId.includes("@broadcast") || chatId.includes("@g.us")) {
      return;
    }

    if (msg.fromMe) {
      // Check prefix for self-messages or outgoing test messages
      if (TRIGGER_PREFIX) {
        if (rawBody.toLowerCase().startsWith(TRIGGER_PREFIX.toLowerCase()) || rawBody.toLowerCase() === "/reset") {
          await handleIncomingMessage(msg);
        }
      }
    }
  });

  client.on("disconnected", (reason) => {
    bridgeState = "DISCONNECTED";
    connectedUser = null;
    currentQR = null;
    currentQRDataURL = null;
    console.log("[DISCONNECT] WhatsApp client was disconnected:", reason);
    addLog("warn", "Bağlantı Kesildi", String(reason));

    // Auto-reconnect if it was an unexpected network or session blip (not intentional logout)
    if (reason !== "LOGOUT") {
      addLog("info", "Yeniden Bağlanma", "Beklenmedik kopma sonrası 10 saniye içinde yeniden başlatılacak...");
      setTimeout(() => {
        if (bridgeState === "DISCONNECTED") {
          console.log("[AUTO_RECONNECT] Attempting to reconnect WhatsApp client...");
          initializeWhatsAppClient(true);
        }
      }, 10000);
    }
  });

  client.initialize().catch(async (err) => {
    console.error("[ERROR] WhatsApp client initialization error:", err.message);
    // WhatsApp Web navigation during pairing/login routinely destroys execution context.
    // NEVER destroy or restart client here, as that aborts the mobile key exchange!
    if (err.message && err.message.includes("Execution context was destroyed")) {
      console.log("[INFO] Navigation detected during login/sync, preserving browser session.");
      return;
    }
    if (err.message && err.message.includes("already running")) {
      cleanChromiumLocks();
      return initializeWhatsAppClient(true, currentPairingPhone);
    }
    bridgeState = "ERROR";
    addLog("error", "Başlatma Hatası", err.message || String(err));
  });

  ensureDOMSupervisorStarted();
}

// Initialize Management Express API
const app = express();
app.use(cors());
app.use(express.json());

let domSupervisorInterval = null;

function startDOMSupervisor() {
  if (domSupervisorInterval) clearInterval(domSupervisorInterval);
  domSupervisorInterval = setInterval(async () => {
    try {
      if (!client || !client.pupPage) return;

      const domStatus = await client.pupPage.evaluate(async () => {
        // 1. Check if logged in
        const pane = document.querySelector("#pane-side") || document.querySelector("[data-testid=chat-list]");
        if (pane) return { state: "CONNECTED" };

        // 2. Check 8-digit pairing code cells
        const cells = Array.from(document.querySelectorAll("[data-testid=link-device-code-cell], div, span")).filter((el) => {
          return (
            el.children.length === 0 &&
            el.innerText &&
            el.innerText.trim().length === 1 &&
            /^[A-Z0-9]$/.test(el.innerText.trim())
          );
        });
        const charList = cells.map((c) => c.innerText.trim());
        if (charList.length >= 8) {
          return {
            state: "PAIRING_CODE_READY",
            code: `${charList.slice(0, 4).join("")}-${charList.slice(4, 8).join("")}`,
          };
        }

        // 3. Check for expired QR reload button ("Select to reload QR code")
        const reloadBtn = Array.from(document.querySelectorAll("button, div[role=button], span")).find((b) => {
          const t = b.innerText ? b.innerText.trim().toLowerCase() : "";
          return t.includes("reload") || t.includes("yenile") || t.includes("yeniden") || t.includes("select to reload");
        });
        if (reloadBtn) {
          reloadBtn.click();
          await new Promise((r) => setTimeout(r, 600));
        }

        // 4. Check for live QR data-ref on the container
        const qrContainer = document.querySelector("[data-ref]") || document.querySelector("[data-testid=link-device-qr-code]");
        const rawRef = qrContainer ? qrContainer.getAttribute("data-ref") : null;
        if (rawRef) {
          return {
            state: "QR_READY",
            rawRef: rawRef,
          };
        }

        // 5. Canvas fallback
        const canvas = document.querySelector("canvas");
        if (canvas && canvas.width > 50 && canvas.height > 50) {
          return {
            state: "QR_READY",
            canvasDataURL: canvas.toDataURL("image/png"),
          };
        }

        // 6. Phone input screen
        const phoneInput = document.querySelector("[data-testid=phone-number-input]") || document.querySelector("input[type=text]");
        if (phoneInput) return { state: "PHONE_INPUT" };

        return { state: "WAITING" };
      });

      if (!domStatus) return;

      if (domStatus.state === "CONNECTED") {
        if (bridgeState !== "CONNECTED") {
          bridgeState = "CONNECTED";
          currentQR = null;
          currentQRDataURL = null;
          currentPairingCode = null;
          currentPairingPhone = null;
          try {
            const info = client.info;
            connectedUser = {
              name: info?.pushname || "WhatsApp Kullanıcısı",
              phone: info?.wid?.user || "Aktif",
              platform: info?.platform || "web",
            };
          } catch (e) {
            connectedUser = { name: "WhatsApp Kullanıcısı", phone: "Aktif" };
          }
          console.log("\n[READY] WhatsApp connected and synced via DOM supervisor!\n");
          addLog("success", "WhatsApp Bağlantısı Aktif", `WhatsApp oturumu bağlandı: ${connectedUser?.phone || 'Aktif'}`);
        }
      } else if (domStatus.state === "PAIRING_CODE_READY") {
        if (domStatus.code && domStatus.code !== currentPairingCode) {
          currentPairingCode = domStatus.code;
          bridgeState = "PAIRING_CODE_READY";
          console.log(`[PAIR_CODE_SYNC] Active code updated: ${currentPairingCode}`);
        }
      } else if (domStatus.state === "QR_READY") {
        if (domStatus.rawRef && domStatus.rawRef !== currentQR) {
          currentQR = domStatus.rawRef;
          try {
            // Generate clean, high-DPI, ultra-sharp QR code with M level error correction
            currentQRDataURL = await QRCode.toDataURL(domStatus.rawRef, {
              margin: 2,
              scale: 8,
              errorCorrectionLevel: "M",
            });
            bridgeState = "QR_READY";
            console.log("[QR_SUPERVISOR] Generated ultra-sharp QR code from live data-ref!");
          } catch (e) {
            console.error("[QR_SUPERVISOR ERROR]:", e.message);
          }
        } else if (!currentQRDataURL && domStatus.canvasDataURL) {
          currentQRDataURL = domStatus.canvasDataURL;
          bridgeState = "QR_READY";
        }
      }
    } catch (err) {
      // Suppress navigation context destroyed
    }
  }, 1500);
}

function ensureDOMSupervisorStarted() {
  if (!domSupervisorInterval) {
    startDOMSupervisor();
  }
}

async function switchToQRMode(page) {
  if (!page) return null;
  const rawQr = await page.evaluate(async () => {
    // 1. If on phone number or pairing code screen, click "Log in with QR code"
    const qrBtn = Array.from(document.querySelectorAll('div[role="button"], button, span, div')).find((b) => {
      const t = b.innerText ? b.innerText.trim() : "";
      return t === "Log in with QR code" || t === "QR kodu ile bağla" || t.includes("Log in with QR");
    });
    if (qrBtn) {
      qrBtn.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // 2. If QR expired, click reload button
    const reloadBtn = Array.from(document.querySelectorAll("button, span, div[role=button]")).find((b) => {
      const t = b.innerText ? b.innerText.trim().toLowerCase() : "";
      return t.includes("reload") || t.includes("yenile") || t.includes("yeniden") || t.includes("select to reload");
    });
    if (reloadBtn) {
      reloadBtn.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // 3. Extract data-ref
    const qrContainer = document.querySelector("[data-ref]") || document.querySelector("[data-testid=link-device-qr-code]");
    if (qrContainer && qrContainer.getAttribute("data-ref")) {
      return qrContainer.getAttribute("data-ref");
    }

    // Fallback: canvas
    const canvas = document.querySelector("canvas");
    if (canvas && canvas.width > 50) {
      return canvas.toDataURL("image/png");
    }
    return null;
  });

  if (rawQr) {
    if (rawQr.startsWith("data:image")) {
      return rawQr;
    }
    try {
      currentQR = rawQr;
      const dataUrl = await QRCode.toDataURL(rawQr, { margin: 2, scale: 8, errorCorrectionLevel: "M" });
      return dataUrl;
    } catch (e) {
      return null;
    }
  }
  return null;
}

async function switchToCodeMode(page) {
  if (!page) return false;
  return await page.evaluate(async () => {
    // If on QR code screen, click "Link with phone number instead."
    const phoneBtn = Array.from(document.querySelectorAll('div[role="button"], button, span, div')).find((b) => {
      const t = b.innerText ? b.innerText.trim() : "";
      return (
        t === "Log in with phone number" ||
        t === "Link with phone number instead." ||
        t === "Telefon numarasıyla bağla" ||
        t.includes("phone number instead")
      );
    });
    if (phoneBtn) {
      phoneBtn.click();
      await new Promise((r) => setTimeout(r, 600));
      return true;
    }
    return false;
  });
}

// API: Get bridge status & QR code & Pairing code
app.get("/api/status", async (req, res) => {
  ensureDOMSupervisorStarted();

  // Instant data-ref fallback if state is not CONNECTED and currentQRDataURL is empty
  if (client && client.pupPage && bridgeState !== "CONNECTED" && !currentQRDataURL && !currentPairingCode) {
    try {
      const rawRef = await client.pupPage.evaluate(() => {
        const qrContainer = document.querySelector("[data-ref]") || document.querySelector("[data-testid=link-device-qr-code]");
        if (qrContainer && qrContainer.getAttribute("data-ref")) {
          return qrContainer.getAttribute("data-ref");
        }
        const c = document.querySelector("canvas");
        return c && c.width > 50 ? c.toDataURL("image/png") : null;
      });
      if (rawRef) {
        if (rawRef.startsWith("data:image")) {
          currentQRDataURL = rawRef;
        } else {
          currentQR = rawRef;
          currentQRDataURL = await QRCode.toDataURL(rawRef, { margin: 2, scale: 8, errorCorrectionLevel: "M" });
        }
        bridgeState = "QR_READY";
      }
    } catch (e) {}
  }

  res.json({
    status: bridgeState,
    qr: currentQRDataURL,
    pairingCode: currentPairingCode,
    pairingPhone: currentPairingPhone,
    connectedUser,
    triggerPrefix: TRIGGER_PREFIX,
    backendWebhookUrl: BACKEND_WEBHOOK_URL,
    logs: recentLogs.slice(-25),
  });
});

// API: Get QR directly
app.get("/api/qr", (req, res) => {
  res.json({
    status: bridgeState,
    qr: currentQRDataURL,
    rawQR: currentQR,
    pairingCode: currentPairingCode,
  });
});

// API: Seamless Bi-Directional Mode Switcher (Zero Browser Restart)
app.post("/api/switch-mode", async (req, res) => {
  const { mode } = req.body || {};
  if (mode !== "qr" && mode !== "code") {
    return res.status(400).json({ success: false, error: "Geçersiz mod ('qr' veya 'code' olmalı)." });
  }

  if (bridgeState === "CONNECTED") {
    return res.json({
      success: true,
      message: "WhatsApp oturumu zaten bağlı.",
      status: "CONNECTED",
      mode,
    });
  }

  try {
    ensureDOMSupervisorStarted();

    if (!client || !client.pupPage) {
      initializeWhatsAppClient(true);
      return res.json({
        success: true,
        message: "İstemci başlatılıyor...",
        status: bridgeState,
        mode,
      });
    }

    if (mode === "qr") {
      const qrData = await switchToQRMode(client.pupPage);
      if (qrData) {
        currentQRDataURL = qrData;
        bridgeState = "QR_READY";
      }
      currentPairingCode = null;
      addLog("info", "QR Moduna Geçildi", "WhatsApp Web QR kod ekranına yönlendirildi.");
      return res.json({
        success: true,
        status: bridgeState,
        qr: currentQRDataURL,
        mode: "qr",
      });
    } else {
      await switchToCodeMode(client.pupPage);
      addLog("info", "Eşleştirme Moduna Geçildi", "WhatsApp Web telefonla eşleştirme ekranına yönlendirildi.");
      return res.json({
        success: true,
        status: bridgeState,
        pairingCode: currentPairingCode,
        mode: "code",
      });
    }
  } catch (err) {
    console.error("[SWITCH_MODE ERROR]:", err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

// API: Safe & Non-Destructive Start / Reconnect (Never kills live session)
app.post("/api/connect", async (req, res) => {
  try {
    ensureDOMSupervisorStarted();

    if (client && client.pupPage) {
      if (bridgeState === "CONNECTED") {
        return res.json({
          success: true,
          message: "WhatsApp oturumu zaten bağlı ve aktif!",
          status: "CONNECTED",
          connectedUser,
        });
      }
      // If browser is running, switch to QR screen & reload QR safely
      const qrData = await switchToQRMode(client.pupPage);
      if (qrData) {
        currentQRDataURL = qrData;
        bridgeState = "QR_READY";
      }
      return res.json({
        success: true,
        message: "QR kodu yenilendi.",
        status: bridgeState,
        qr: currentQRDataURL,
      });
    }

    // Client is dead or null -> initialize
    initializeWhatsAppClient(true);
    res.json({
      success: true,
      message: "WhatsApp istemcisi başlatılıyor...",
      status: bridgeState,
    });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

let isPairingInProgress = false;


async function requestPairingCodeViaDOM(page, phoneNumber) {
  let clean = String(phoneNumber).replace(/\D/g, "");
  if (clean.startsWith("0")) {
    clean = "90" + clean.substring(1);
  } else if (!clean.startsWith("90") && clean.length === 10) {
    clean = "90" + clean;
  }
  const formattedPhone = "+" + clean;

  console.log(`[PAIR_DOM] Requesting code for ${formattedPhone} via WhatsApp Web UI...`);

  const code = await page.evaluate(async (targetPhone) => {
    // 1. Dismiss any existing modal/alert (e.g. OK button)
    const okBtn = Array.from(document.querySelectorAll("button, div[role=button]")).find(
      (b) => b.innerText && b.innerText.trim() === "OK"
    );
    if (okBtn) {
      okBtn.click();
      await new Promise((r) => setTimeout(r, 400));
    }

    // 2. If already on the code screen for targetPhone, return the active code without regenerating
    const pageText = document.body ? document.body.innerText : "";
    const cleanTarget = targetPhone.replace(/\D/g, "");
    const cleanPage = pageText.replace(/\D/g, "");
    if ((pageText.includes("Enter code") || pageText.includes("Kodu girin")) && cleanPage.includes(cleanTarget)) {
      const cells = Array.from(document.querySelectorAll("[data-testid=link-device-code-cell], div, span")).filter((el) => {
        return (
          el.children.length === 0 &&
          el.innerText &&
          el.innerText.trim().length === 1 &&
          /^[A-Z0-9]$/.test(el.innerText.trim())
        );
      });
      const charList = cells.map((c) => c.innerText.trim());
      if (charList.length >= 8) {
        return `${charList.slice(0, 4).join("")}-${charList.slice(4, 8).join("")}`;
      }
    }

    // Otherwise if on code screen for a DIFFERENT number, click (edit) to change it
    const editBtn = Array.from(document.querySelectorAll("button, span, div[role=button]")).find(
      (b) => b.innerText && b.innerText.includes("(edit)")
    );
    if (editBtn) {
      editBtn.click();
      await new Promise((r) => setTimeout(r, 600));
    }


    // 3. Find "Log in with phone number" or "Link with phone number instead."
    const linkPhoneBtn = Array.from(document.querySelectorAll("div[role=button], button, span, div")).find((b) => {
      const t = b.innerText ? b.innerText.trim() : "";
      return t === "Log in with phone number" || t === "Link with phone number instead." || t === "Telefon numarasıyla bağla";
    });
    if (linkPhoneBtn) {
      linkPhoneBtn.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // 4. Wait for phone number input
    let input = null;
    for (let i = 0; i < 35; i++) {
      input = document.querySelector("[data-testid=phone-number-input]") || document.querySelector("input[type=text]");
      if (input) break;
      await new Promise((r) => setTimeout(r, 200));
    }
    if (!input) {
      throw new Error("WhatsApp Web telefon numarası giriş alanı bulunamadı.");
    }

    // 5. Fill input with target phone number using React value setter
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    nativeSetter.call(input, targetPhone);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 500));

    // 6. Click Next
    const nextBtn = Array.from(document.querySelectorAll("button, div[role=button]")).find((b) => {
      const t = b.innerText ? b.innerText.trim() : "";
      return t === "Next" || t === "İleri";
    });
    if (!nextBtn) {
      throw new Error("İleri (Next) butonu bulunamadı.");
    }
    nextBtn.click();

    // 7. Wait for response: either error modal or pairing code
    for (let i = 0; i < 35; i++) {
      await new Promise((r) => setTimeout(r, 400));

      // Check for error alert/dialog
      const alert = Array.from(document.querySelectorAll("[role=alert], div[role=dialog]"))
        .map((e) => e.innerText)
        .find((t) => t && t.length > 5);
      if (alert) {
        if (alert.includes("Too many attempts") || alert.includes("çok fazla deneme")) {
          const ok = Array.from(document.querySelectorAll("button, div[role=button]")).find(
            (b) => b.innerText && b.innerText.trim() === "OK"
          );
          if (ok) ok.click();
          throw new Error("WhatsApp güvenlik kısıtlaması: Bu numara için çok fazla deneme yapıldı. WhatsApp geçici olarak bekleme süresi koymuştur. Lütfen 15-30 dakika sonra tekrar deneyiniz.");
        }
        if (alert.includes("invalid") || alert.includes("geçersiz") || alert.includes("Check the phone number")) {
          throw new Error("WhatsApp bu telefon numarasını geçersiz olarak bildirdi. Lütfen girdiğiniz numarayı kontrol ediniz.");
        }
      }

      // Check for code cells
      const cells = Array.from(document.querySelectorAll("[data-testid=link-device-code-cell], div, span")).filter((el) => {
        return (
          el.children.length === 0 &&
          el.innerText &&
          el.innerText.trim().length === 1 &&
          /^[A-Z0-9]$/.test(el.innerText.trim())
        );
      });
      const charList = cells.map((c) => c.innerText.trim());
      if (charList.length >= 8) {
        const p1 = charList.slice(0, 4).join("");
        const p2 = charList.slice(4, 8).join("");
        return `${p1}-${p2}`;
      }

      // Fallback regex match for XXXX-XXXX
      const allText = Array.from(document.querySelectorAll("span, div"))
        .map((s) => s.innerText && s.innerText.trim())
        .filter(Boolean);
      for (const t of allText) {
        const m = t.match(/\b([A-Z0-9]{4})-([A-Z0-9]{4})\b/);
        if (m) {
          return `${m[1]}-${m[2]}`;
        }
      }
    }

    throw new Error("WhatsApp eşleştirme kodu zaman aşımına uğradı. Lütfen tekrar deneyiniz.");
  }, formattedPhone);

  return code;
}

// API: Request Pairing Code (No QR mode for remote clients)
app.post("/api/pair", async (req, res) => {
  const { phoneNumber } = req.body || {};
  if (!phoneNumber || typeof phoneNumber !== "string") {
    return res.status(400).json({ success: false, error: "Lütfen geçerli bir telefon numarası girin." });
  }

  let clean = phoneNumber.replace(/\D/g, "");
  if (clean.startsWith("0")) {
    clean = "90" + clean.substring(1);
  } else if (!clean.startsWith("90") && clean.length === 10) {
    clean = "90" + clean;
  }

  if (isPairingInProgress) {
    return res.status(429).json({ success: false, error: "Eşleştirme kodu zaten alınıyor, lütfen bekleyin..." });
  }
  isPairingInProgress = true;
  currentPairingPhone = clean;

  try {
    // 1. Ensure client is active and pupPage is available
    if (!client || !client.pupPage) {
      console.log(`[PAIR] Initializing WhatsApp client before requesting code for: ${clean}`);
      addLog("info", "WhatsApp Başlatılıyor", `${clean} için tarayıcı hazırlanıyor...`);
      initializeWhatsAppClient(true, clean);
      
      // Wait up to 25s for pupPage to be ready
      for (let i = 0; i < 50; i++) {
        await new Promise((r) => setTimeout(r, 500));
        if (client && client.pupPage) break;
      }
      if (!client || !client.pupPage) {
        throw new Error("WhatsApp Web tarayıcısı henüz hazır değil. Lütfen birkaç saniye sonra tekrar deneyiniz.");
      }
    }

    console.log(`[PAIR] Requesting pairing code via DOM for: ${clean}`);
    addLog("info", "Eşleştirme Kodu İsteniyor", `${clean} için 8 haneli kod alınıyor...`);
    
    const code = await requestPairingCodeViaDOM(client.pupPage, clean);
    if (code) {
      bridgeState = "PAIRING_CODE_READY";
      currentPairingCode = code;
      ensureDOMSupervisorStarted();

      console.log(`\n==============================================`);
      console.log(`[PAIRING CODE] WhatsApp Eşleştirme Kodu: ${code}`);
      console.log(`==============================================\n`);

      addLog("warn", "Eşleştirme Kodu Hazır", `Numara (${clean}) için 8 haneli kod: ${code}`);

      return res.json({
        success: true,
        code: code,
        pairingCode: code,
        message: `${clean} için 8 haneli kod üretildi: ${code}`,
        phoneNumber: clean,
      });
    } else {
      throw new Error("Eşleştirme kodu oluşturulamadı.");
    }
  } catch (err) {
    console.error("[PAIR ERROR]:", err.message || err);
    addLog("error", "Eşleştirme Hatası", err.message || String(err));
    res.status(500).json({ success: false, error: err.message || String(err) });
  } finally {
    isPairingInProgress = false;
  }
});


// Debug: Live WhatsApp Web Screenshot
app.get("/api/debug/screenshot", async (req, res) => {
  if (!client || !client.pupPage) {
    return res.status(404).json({ error: "Puppeteer sayfası henüz hazır değil" });
  }
  try {
    const buffer = await client.pupPage.screenshot({ type: "png", fullPage: true });
    res.setHeader("Content-Type", "image/png");
    res.send(buffer);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});


// API: Disconnect / Unlink WhatsApp Client
app.post("/api/disconnect", async (req, res) => {
  try {
    if (client) {
      addLog("info", "Bağlantı Kapatılıyor", "Kullanıcı isteği ile WhatsApp istemcisi durduruldu.");
      try {
        await client.logout();
      } catch (logoutErr) {
        console.warn("[WARN] client.logout() warning:", logoutErr.message);
      }
      try {
        await client.destroy();
      } catch (destErr) {
        console.warn("[WARN] client.destroy() warning:", destErr.message);
      }
      client = null;
    }
    bridgeState = "DISCONNECTED";
    connectedUser = null;
    currentQR = null;
    currentQRDataURL = null;

    // Optional session cache purge if requested
    if (req.body?.clearSession) {
      try {
        if (fs.existsSync(AUTH_DATA_PATH)) {
          fs.rmSync(AUTH_DATA_PATH, { recursive: true, force: true });
          addLog("info", "Oturum Temizlendi", "LocalAuth verileri silindi.");
        }
      } catch (e) {
        console.warn("[WARN] Could not remove auth folder:", e.message);
      }
    }

    res.json({ success: true, message: "WhatsApp bağlantısı kesildi.", status: bridgeState });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// API: Update Trigger Prefix
app.post("/api/prefix", (req, res) => {
  const { prefix } = req.body;
  TRIGGER_PREFIX = typeof prefix === "string" ? prefix.trim() : "";
  FILTER_CONFIG.trigger_prefix = TRIGGER_PREFIX;
  addLog("info", "Önek Güncellendi", TRIGGER_PREFIX ? `Yeni önek: "${TRIGGER_PREFIX}"` : "Önek kaldırıldı (Tüm mesajlar)");
  res.json({ success: true, triggerPrefix: TRIGGER_PREFIX });
});

// API: Update Full Filter & Debounce Configuration
app.post("/api/config", (req, res) => {
  const body = req.body || {};
  if (typeof body.only_unknown_contacts === "boolean") FILTER_CONFIG.only_unknown_contacts = body.only_unknown_contacts;
  if (Array.isArray(body.blacklist)) FILTER_CONFIG.blacklist = body.blacklist;
  if (typeof body.debounce_seconds === "number") FILTER_CONFIG.debounce_seconds = Math.max(1, body.debounce_seconds);
  if (typeof body.admin_notify_phone === "string") FILTER_CONFIG.admin_notify_phone = body.admin_notify_phone;
  if (typeof body.trigger_prefix === "string") {
    FILTER_CONFIG.trigger_prefix = body.trigger_prefix;
    TRIGGER_PREFIX = body.trigger_prefix;
  }
  console.log("[CONFIG] Updated bridge filter settings:", FILTER_CONFIG);
  addLog("info", "Filtre Ayarları Güncellendi", `Rehber Filtresi: ${FILTER_CONFIG.only_unknown_contacts ? 'Açık' : 'Kapalı'}, Tampon: ${FILTER_CONFIG.debounce_seconds}s`);
  res.json({ success: true, config: FILTER_CONFIG });
});

app.get("/api/config", (req, res) => {
  res.json({ success: true, config: FILTER_CONFIG });
});

// API: Get Event Logs
app.get("/api/logs", (req, res) => {
  res.json({ logs: recentLogs });
});

// Start Express Server
app.listen(BRIDGE_API_PORT, "0.0.0.0", () => {
  console.log("=================================================");
  console.log(`  Bridge Management API active on port ${BRIDGE_API_PORT}`);
  console.log(`  Endpoints: http://localhost:${BRIDGE_API_PORT}/api/status`);
  console.log("=================================================");
});

// Sync persistent filter settings from FastAPI on boot
async function syncFilterSettingsFromBackend() {
  try {
    const backendBase = BACKEND_WEBHOOK_URL.replace(/\/webhook\/?$/, "");
    const res = await axios.get(`${backendBase}/api/settings/filters`, { timeout: 4000 });
    if (res.data) {
      if (typeof res.data.only_unknown_contacts === "boolean") FILTER_CONFIG.only_unknown_contacts = res.data.only_unknown_contacts;
      if (Array.isArray(res.data.blacklist)) FILTER_CONFIG.blacklist = res.data.blacklist;
      if (typeof res.data.debounce_seconds === "number") FILTER_CONFIG.debounce_seconds = res.data.debounce_seconds;
      if (typeof res.data.admin_notify_phone === "string") FILTER_CONFIG.admin_notify_phone = res.data.admin_notify_phone;
      if (typeof res.data.trigger_prefix === "string") {
        FILTER_CONFIG.trigger_prefix = res.data.trigger_prefix;
        TRIGGER_PREFIX = res.data.trigger_prefix;
      }
      console.log("[CONFIG] Synced persistent filter settings from backend:", FILTER_CONFIG);
    }
  } catch (err) {
    console.log("[CONFIG] Note: Initial filter sync from backend skipped (backend starting up).");
  }
}

// Auto-start WhatsApp client on boot
initializeWhatsAppClient();
syncFilterSettingsFromBackend();

// Graceful shutdown
const shutdown = async () => {
  console.log("\n[SHUTDOWN] Destroying WhatsApp client...");
  if (client) {
    try {
      await client.destroy();
    } catch (e) {}
  }
  process.exit(0);
};

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

/**
 * WhatsApp AI Camp Assistant — Control Center & Multi-Chat Interface
 */

// =========================================================================
// 0. Global Authentication & Fetch Interceptor
// =========================================================================
const originalFetch = window.fetch;
window.fetch = async function (url, options = {}) {
  options = options || {};
  options.headers = options.headers || {};
  const token = localStorage.getItem("panel_auth_token");
  if (token) {
    if (options.headers instanceof Headers) {
      options.headers.set("X-Panel-Token", token);
      options.headers.set("Authorization", `Bearer ${token}`);
    } else if (Array.isArray(options.headers)) {
      options.headers.push(["X-Panel-Token", token]);
      options.headers.push(["Authorization", `Bearer ${token}`]);
    } else {
      options.headers["X-Panel-Token"] = token;
      options.headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await originalFetch(url, options);
  if (response.status === 401 && typeof url === "string" && !url.includes("/api/auth/login")) {
    const currentToken = localStorage.getItem("panel_auth_token");
    let sentToken = null;
    if (options && options.headers) {
      if (typeof options.headers.get === "function") {
        sentToken = options.headers.get("X-Panel-Token");
      } else if (Array.isArray(options.headers)) {
        const found = options.headers.find(h => h[0] === "X-Panel-Token");
        sentToken = found ? found[1] : null;
      } else {
        sentToken = options.headers["X-Panel-Token"];
      }
    }

    if (!currentToken || (sentToken && sentToken === currentToken)) {
      localStorage.removeItem("panel_auth_token");
      if (typeof stopPolling === "function") stopPolling();
      showAuthModal();
    }
  }
  return response;
};

function checkAuthStatus() {
  const token = localStorage.getItem("panel_auth_token");
  if (!token) {
    showAuthModal();
    return false;
  }
  return true;
}

function showAuthModal() {
  const overlay = document.getElementById("auth-overlay");
  if (overlay) {
    overlay.classList.add("show-modal");
    overlay.style.display = "flex";
    setTimeout(() => {
      const input = document.getElementById("auth-password-input");
      if (input) input.focus();
    }, 120);
  }
}

function hideAuthModal() {
  const overlay = document.getElementById("auth-overlay");
  if (overlay) {
    overlay.classList.remove("show-modal");
    overlay.style.display = "none";
  }
}

let statusInterval = null;
let convInterval = null;
let msgInterval = null;

function startPolling() {
  stopPolling();
  statusInterval = setInterval(fetchStatus, 2500);
  convInterval = setInterval(fetchConversations, 3000);
  msgInterval = setInterval(fetchMessages, 4000);
}

function stopPolling() {
  if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
  if (convInterval) { clearInterval(convInterval); convInterval = null; }
  if (msgInterval) { clearInterval(msgInterval); msgInterval = null; }
}

async function handleLoginSubmit(event) {
  if (event) event.preventDefault();
  const input = document.getElementById("auth-password-input");
  const errorMsg = document.getElementById("auth-error-msg");
  const btn = document.getElementById("auth-submit-btn");
  if (!input) return;

  const password = input.value.trim();
  if (!password) return;

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Giriş Yapılıyor...</span>`;
  }
  if (errorMsg) {
    errorMsg.style.display = "none";
    errorMsg.textContent = "";
  }

  try {
    const res = await originalFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: password }),
    });
    const data = await res.json();
    if (res.ok && data.success && data.token) {
      localStorage.setItem("panel_auth_token", data.token);
      hideAuthModal();
      input.value = "";
      if (errorMsg) errorMsg.style.display = "none";
      showToast("success", "Başarılı", "Yönetici paneline giriş yapıldı.");

      // Start polling and fetch initial data immediately
      startPolling();
      fetchStatus();
      fetchFilterSettings();
      fetchConversations();
      fetchActiveConversationMessages();
      fetchMessages();
    } else {
      if (errorMsg) {
        errorMsg.textContent = data.detail || "Hatalı panel şifresi! Lütfen tekrar deneyin.";
        errorMsg.style.display = "block";
      }
      input.select();
    }
  } catch (err) {
    if (errorMsg) {
      errorMsg.textContent = "Bağlantı hatası: " + err.message;
      errorMsg.style.display = "block";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-right-to-bracket"></i> <span>Giriş Yap</span>`;
    }
  }
}

function handleLogout() {
  if (confirm("Panel oturumunu kilitlemek istediğinizden emin misiniz?")) {
    stopPolling();
    localStorage.removeItem("panel_auth_token");
    originalFetch("/api/auth/logout", { method: "POST" }).catch(() => { });
    showAuthModal();
    showToast("info", "Kilitlendi", "Panel oturumu kapatıldı.");
  }
}

const API_BASE = "";
const DEFAULT_SIMULATOR_PHONE = "905559876543@c.us";

let activeChatPhone = DEFAULT_SIMULATOR_PHONE;
let allConversations = [];
let activeTab = "logs";
let currentBridgeState = "DISCONNECTED";
let lastKnownLogsCount = 0;
let searchQuery = "";

// On DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  const isAuthed = checkAuthStatus();
  if (isAuthed) {
    fetchStatus();
    fetchFilterSettings();
    fetchKnowledgeSettings();
    fetchConversations();
    fetchActiveConversationMessages();
    fetchMessages();
    startPolling();
  }

  // Sync prefix toggle label
  const prefixInput = document.getElementById("input-prefix");
  const previewPrefix = document.getElementById("preview-prefix");
  if (prefixInput && previewPrefix) {
    prefixInput.addEventListener("input", (e) => {
      previewPrefix.textContent = e.target.value.trim() || "(önek yok)";
    });
  }

  // Live counter for knowledge textarea
  const kbTextarea = document.getElementById("knowledge-textarea");
  if (kbTextarea) {
    kbTextarea.addEventListener("input", updateKnowledgeCounters);
  }
});

// =========================================================================
// 1. Status & Bridge State Management
// =========================================================================

async function fetchStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/status`);
    if (!res.ok) throw new Error("Dashboard status fetch failed");
    const data = await res.json();

    // Isolated safe calls
    try { updateServiceIndicators(data); } catch (e) { console.error("Error in updateServiceIndicators:", e); }
    try { updateSystemResources(data.resources); } catch (e) { console.error("Error in updateSystemResources:", e); }
    try { updateBridgePanel(data.bridge); } catch (e) { console.error("Error in updateBridgePanel:", e); }
    try { updateModelSelector(data.ollama); } catch (e) { console.error("Error in updateModelSelector:", e); }
    try { updateMemoryStats(data.database); } catch (e) { console.error("Error in updateMemoryStats:", e); }
    try { updateSecurityPanel(data.security); } catch (e) { console.error("Error in updateSecurityPanel:", e); }
    if (data.bridge && data.bridge.logs) {
      try { renderLogs(data.bridge.logs); } catch (e) { console.error("Error in renderLogs:", e); }
    }
  } catch (err) {
    console.warn("Status poll error:", err.message);
    setOfflineIndicators();
  }
}

function updateSystemResources(resources) {
  if (!resources) return;

  // CPU
  const elCpu = document.getElementById("res-cpu");
  const elCpuBar = document.getElementById("res-cpu-bar");
  if (elCpu) {
    const pct = typeof resources.cpu_percent === "number" ? resources.cpu_percent : 0;
    elCpu.textContent = `${pct.toFixed(1)}%`;
    if (elCpuBar) {
      elCpuBar.style.width = `${Math.min(100, Math.max(2, pct))}%`;
      elCpuBar.className = "metric-progress-bar" + (pct > 80 ? " danger" : (pct > 50 ? " warn" : ""));
    }
  }

  // RAM
  const elRam = document.getElementById("res-ram");
  const elRamBar = document.getElementById("res-ram-bar");
  if (elRam && resources.ram) {
    const ram = resources.ram;
    elRam.textContent = `${ram.used_mb} / ${ram.total_mb} MB (${ram.percent}%)`;
    if (elRamBar) {
      elRamBar.style.width = `${Math.min(100, Math.max(2, ram.percent))}%`;
      elRamBar.className = "metric-progress-bar" + (ram.percent > 85 ? " danger" : (ram.percent > 65 ? " warn" : ""));
    }
  }

  // Swap
  const elSwap = document.getElementById("res-swap");
  const elSwapBar = document.getElementById("res-swap-bar");
  if (elSwap && resources.swap) {
    const swap = resources.swap;
    elSwap.textContent = `${swap.used_mb} / ${swap.total_mb} MB (${swap.percent}%)`;
    if (elSwapBar) {
      elSwapBar.style.width = `${Math.min(100, Math.max(2, swap.percent))}%`;
      elSwapBar.className = "metric-progress-bar" + (swap.percent > 80 ? " danger" : (swap.percent > 30 ? " warn" : ""));
    }
  }

  // Disk
  const elDisk = document.getElementById("res-disk");
  const elDiskBar = document.getElementById("res-disk-bar");
  if (elDisk && resources.disk) {
    const disk = resources.disk;
    elDisk.textContent = `${disk.used_gb} / ${disk.total_gb} GB (${disk.percent}%)`;
    if (elDiskBar) {
      elDiskBar.style.width = `${Math.min(100, Math.max(2, disk.percent))}%`;
      elDiskBar.className = "metric-progress-bar" + (disk.percent > 90 ? " danger" : (disk.percent > 75 ? " warn" : ""));
    }
  }

  // Uptime
  const elUptime = document.getElementById("res-uptime");
  if (elUptime && resources.uptime) {
    elUptime.textContent = resources.uptime;
  }
}

function updateServiceIndicators(data) {
  // Backend Pill
  const pillBackend = document.getElementById("pill-backend");
  const valBackend = document.getElementById("val-backend");
  if (pillBackend && valBackend) {
    if (data.backend?.status === "online") {
      pillBackend.className = "status-pill status-pill-btn online";
      valBackend.textContent = "API Aktif";
    } else {
      pillBackend.className = "status-pill status-pill-btn offline";
      valBackend.textContent = "Kapalı";
    }
  }

  // Ollama / Cloud Model Pill
  const pillOllama = document.getElementById("pill-ollama");
  const valOllama = document.getElementById("val-ollama");
  if (pillOllama && valOllama) {
    if (data.ollama?.connected) {
      pillOllama.className = "status-pill status-pill-btn online";
      let modelClean = (data.ollama.active_model || "AI")
        .replace(/^OPENAI:\s*/i, "")
        .replace(/^GROQ:\s*/i, "")
        .replace(/^OPENROUTER:\s*/i, "")
        .replace(/^GEMINI:\s*/i, "")
        .replace(/\s*\(Bağlı\)/i, "");
      valOllama.textContent = modelClean;
    } else {
      pillOllama.className = "status-pill status-pill-btn offline";
      valOllama.textContent = data.ollama?.error ? "Erişilemiyor" : "Kapalı";
    }
  }

  // Bridge Pill
  const pillBridge = document.getElementById("pill-bridge");
  const valBridge = document.getElementById("val-bridge");
  currentBridgeState = data.bridge?.status || "OFFLINE";

  if (pillBridge && valBridge) {
    if (currentBridgeState === "CONNECTED") {
      pillBridge.className = "status-pill status-pill-btn online";
      valBridge.textContent = "WhatsApp";
    } else if (currentBridgeState === "AUTHENTICATED") {
      pillBridge.className = "status-pill status-pill-btn online";
      valBridge.textContent = "Eşitleniyor...";
    } else if (currentBridgeState === "QR_READY") {
      pillBridge.className = "status-pill status-pill-btn warning";
      valBridge.textContent = "QR Bekliyor";
    } else if (currentBridgeState === "INITIALIZING") {
      pillBridge.className = "status-pill status-pill-btn warning";
      valBridge.textContent = "Başlatılıyor...";
    } else {
      pillBridge.className = "status-pill status-pill-btn offline";
      valBridge.textContent = "Bağlantı Yok";
    }
  }
}

function setOfflineIndicators() {
  const pillBackend = document.getElementById("pill-backend");
  if (pillBackend) pillBackend.className = "status-pill status-pill-btn offline";
  const pillOllama = document.getElementById("pill-ollama");
  if (pillOllama) pillOllama.className = "status-pill status-pill-btn offline";
  const pillBridge = document.getElementById("pill-bridge");
  if (pillBridge) pillBridge.className = "status-pill status-pill-btn offline";
}

function forceRefreshStatus() {
  fetchStatus();
  fetchConversations();
}

function focusModelSelector() {
  const select = document.getElementById("select-model");
  if (select) {
    select.focus();
    select.scrollIntoView({ behavior: "smooth", block: "center" });
    select.style.boxShadow = "0 0 15px var(--wa-green-light)";
    setTimeout(() => { select.style.boxShadow = ""; }, 1500);
  }
}

function switchMainView(viewId) {
  // Update view navigation tabs
  const tabs = document.querySelectorAll(".view-tab");
  tabs.forEach(tab => tab.classList.remove("active"));
  const activeTab = document.getElementById(`view-tab-${viewId}`);
  if (activeTab) activeTab.classList.add("active");

  const views = {
    chat: document.getElementById("view-chat"),
    knowledge: document.getElementById("view-knowledge"),
    settings: document.getElementById("view-settings"),
    logs: document.getElementById("view-logs")
  };

  Object.keys(views).forEach(key => {
    if (views[key]) {
      if (key === viewId) {
        views[key].classList.remove("hidden");
        views[key].classList.add("active-view");
      } else {
        views[key].classList.add("hidden");
        views[key].classList.remove("active-view");
      }
    }
  });

  if (viewId === "knowledge") {
    fetchKnowledgeSettings();
  }

  // Re-scroll chat if switching to chat
  if (viewId === "chat") {
    const container = document.getElementById("chat-messages");
    if (container) container.scrollTop = container.scrollHeight;
  }
}

function toggleQuickSettings() {
  const drawer = document.getElementById("quick-settings-drawer");
  const backdrop = document.getElementById("quick-drawer-backdrop");
  if (!drawer) return;
  const isOpen = drawer.classList.contains("open");
  if (isOpen) {
    drawer.classList.remove("open");
    if (backdrop) backdrop.classList.add("hidden");
  } else {
    drawer.classList.add("open");
    if (backdrop) backdrop.classList.remove("hidden");

    // Sync current values into quick drawer
    const prefixInput = document.getElementById("input-prefix");
    const quickPrefix = document.getElementById("quick-input-prefix");
    if (prefixInput && quickPrefix) quickPrefix.value = prefixInput.value;

    const topicInput = document.getElementById("input-ntfy-topic");
    const quickTopic = document.getElementById("quick-ntfy-topic");
    if (topicInput && quickTopic) quickTopic.textContent = topicInput.value;
  }
}

async function handleQuickPrefixSave() {
  const quickInput = document.getElementById("quick-input-prefix");
  const mainInput = document.getElementById("input-prefix");
  if (quickInput && mainInput) {
    mainInput.value = quickInput.value.trim();
    await handlePrefixSave();
  }
}

function toggleRightDrawer() {
  switchMainView("logs");
}

function updateBridgePanel(bridge) {
  if (!bridge) return;

  const quickStatus = document.getElementById("quick-bridge-status");
  if (quickStatus) {
    if (bridge.status === "CONNECTED") {
      quickStatus.innerHTML = `<span style="color: var(--wa-green-light); font-weight: 600;"><i class="fa-solid fa-circle-check"></i> WhatsApp Bağlı (${bridge.user?.name || bridge.user?.id || 'Aktif'})</span>`;
    } else if (bridge.status === "QR_READY") {
      quickStatus.innerHTML = `<span style="color: var(--warning); font-weight: 600;"><i class="fa-solid fa-qrcode"></i> QR Kod Hazır</span>`;
    } else {
      quickStatus.innerHTML = `<span style="color: var(--text-secondary);"><i class="fa-solid fa-circle-xmark"></i> Bağlantı Yok / Çevrimdışı</span>`;
    }
  }

  const qrBox = document.getElementById("qr-box");
  const qrPlaceholder = document.getElementById("qr-placeholder");
  const qrSpinner = document.getElementById("qr-spinner");
  const qrImage = document.getElementById("qr-image");
  const connectedProfile = document.getElementById("connected-profile");
  const connectedName = document.getElementById("connected-name");
  const connectedPhone = document.getElementById("connected-phone");
  const bridgeBadge = document.getElementById("bridge-badge");

  // Sync Trigger Prefix Input if not focused
  const prefixInput = document.getElementById("input-prefix");
  const previewPrefix = document.getElementById("preview-prefix");
  if (prefixInput && document.activeElement !== prefixInput && bridge.triggerPrefix !== undefined) {
    prefixInput.value = bridge.triggerPrefix;
    if (previewPrefix) {
      previewPrefix.textContent = bridge.triggerPrefix || "(önek yok)";
    }
  }

  // Update badge
  if (bridgeBadge) {
    if (bridge.status === "CONNECTED") {
      bridgeBadge.className = "connection-badge status-connected";
      bridgeBadge.textContent = "Bağlı";
    } else if (bridge.status === "AUTHENTICATED") {
      bridgeBadge.className = "connection-badge status-connected";
      bridgeBadge.textContent = "Eşitleniyor...";
    } else if (bridge.status === "PAIRING_CODE_READY" || bridge.pairingCode) {
      bridgeBadge.className = "connection-badge status-qr";
      bridgeBadge.textContent = "Kod Hazır";
    } else if (bridge.status === "QR_READY") {
      bridgeBadge.className = "connection-badge status-qr";
      bridgeBadge.textContent = "QR Kod Hazır";
    } else if (bridge.status === "INITIALIZING") {
      bridgeBadge.className = "connection-badge status-warning";
      bridgeBadge.textContent = "Başlatılıyor";
    } else {
      bridgeBadge.className = "connection-badge status-disconnected";
      bridgeBadge.textContent = "Çevrimdışı";
    }
  }

  // Handle Pairing Code Display Banner
  const bannerPairing = document.getElementById("banner-pairing-code");
  const valPairingCode = document.getElementById("val-pairing-code");
  if (bridge.status === "CONNECTED" || bridge.status === "AUTHENTICATED") {
    if (bannerPairing) bannerPairing.classList.add("hidden");
  } else if (bridge.pairingCode) {
    if (bannerPairing) bannerPairing.classList.remove("hidden");
    if (valPairingCode) valPairingCode.textContent = formatPairingCode(bridge.pairingCode);
  }

  if (bridge.status === "CONNECTED") {
    if (qrBox) qrBox.classList.add("hidden");
    if (connectedProfile) {
      connectedProfile.classList.remove("hidden");
      if (connectedName) connectedName.textContent = bridge.connectedUser?.name || "WhatsApp Kullanıcısı";
      if (connectedPhone) connectedPhone.textContent = bridge.connectedUser?.phone || "Bağlı";
    }
  } else if (bridge.status === "AUTHENTICATED") {
    if (qrBox) qrBox.classList.add("hidden");
    if (connectedProfile) {
      connectedProfile.classList.remove("hidden");
      if (connectedName) connectedName.textContent = "WhatsApp Hesabı (Bağlandı)";
      if (connectedPhone) connectedPhone.textContent = "Sohbetler eşitleniyor, lütfen bekleyin...";
    }
  } else if (bridge.status === "QR_READY" && bridge.qr) {
    if (connectedProfile) connectedProfile.classList.add("hidden");
    if (qrBox) qrBox.classList.remove("hidden");
    if (qrPlaceholder) qrPlaceholder.classList.add("hidden");
    if (qrSpinner) qrSpinner.classList.add("hidden");
    if (qrImage) {
      qrImage.classList.remove("hidden");
      qrImage.src = bridge.qr;
    }
  } else if (bridge.status === "INITIALIZING") {
    if (connectedProfile) connectedProfile.classList.add("hidden");
    if (qrBox) qrBox.classList.remove("hidden");
    if (qrPlaceholder) qrPlaceholder.classList.add("hidden");
    if (qrImage) qrImage.classList.add("hidden");
    if (qrSpinner) qrSpinner.classList.remove("hidden");
  } else {
    // DISCONNECTED / OFFLINE
    if (connectedProfile) connectedProfile.classList.add("hidden");
    if (qrBox) qrBox.classList.remove("hidden");
    if (qrImage) qrImage.classList.add("hidden");
    if (qrSpinner) qrSpinner.classList.add("hidden");
    if (qrPlaceholder) qrPlaceholder.classList.remove("hidden");
  }
}

function getFriendlyStatus(status) {
  switch (status) {
    case "CONNECTED":
      return "WhatsApp oturumu aktif ve mesajları dinliyor.";
    case "QR_READY":
      return "Lütfen WhatsApp > Bağlı Cihazlar ile QR kodu taratın.";
    case "INITIALIZING":
      return "WhatsApp istemcisi başlatılıyor...";
    case "AUTHENTICATED":
      return "Oturum doğrulandı, yükleniyor...";
    case "DISCONNECTED":
      return "WhatsApp bağlantısı kapalı.";
    default:
      return "Köprü servisine bağlanılamıyor.";
  }
}

function updateModelSelector(ollama) {
  const select = document.getElementById("select-model");
  if (!select) return;

  // Always provide Cloud API options + any detected local Ollama models
  const cloudModels = [
    { value: "gpt-4o-mini", label: "OpenAI: gpt-4o-mini (Önerilen - Bulut API)" },
    { value: "llama-3.3-70b-versatile", label: "Groq: llama-3.3-70b-versatile (Bulut Hızlı)" },
  ];

  const localModels = (ollama?.models || [])
    .filter(m => !m.startsWith("OPENAI:") && !m.startsWith("GROQ:") && m !== "gpt-4o-mini" && m !== "llama-3.3-70b-versatile")
    .map(m => ({ value: m, label: `Ollama: ${m} (Lokal)` }));

  const allAvailable = [...cloudModels, ...localModels];
  const allValues = allAvailable.map(x => x.value);

  const existingOptions = Array.from(select.options).map(o => o.value);
  const isSame = existingOptions.length === allValues.length &&
    existingOptions.every((v, i) => v === allValues[i]);

  if (!isSame) {
    const currentVal = select.value;
    select.innerHTML = "";
    allAvailable.forEach(item => {
      const opt = document.createElement("option");
      opt.value = item.value;
      opt.textContent = item.label;
      select.appendChild(opt);
    });

    if (currentVal && allValues.includes(currentVal)) {
      select.value = currentVal;
    } else if (ollama?.active_model && allValues.includes(ollama.active_model)) {
      select.value = ollama.active_model;
    } else {
      select.value = "gpt-4o-mini";
    }
  }
}

function updateMemoryStats(dbStats) {
  if (!dbStats) return;
  const statCount = document.getElementById("stats-msg-count");
  if (statCount) {
    statCount.textContent = `${dbStats.total_messages || 0} mesaj (${dbStats.total_users || 0} kullanıcı)`;
  }
}

function updateSecurityPanel(sec) {
  if (!sec) return;
  const inputRateMin = document.getElementById("input-rate-min");
  const inputRateDaily = document.getElementById("input-rate-daily");
  const valRateMin = document.getElementById("val-rate-min");
  const valRateDaily = document.getElementById("val-rate-daily");
  const valBlockedCount = document.getElementById("val-blocked-count");
  const blockedBox = document.getElementById("blocked-phones-box");

  if (document.activeElement !== inputRateMin) {
    inputRateMin.value = sec.rate_limit_per_minute || 5;
    valRateMin.textContent = sec.rate_limit_per_minute || 5;
  }
  if (document.activeElement !== inputRateDaily) {
    inputRateDaily.value = sec.rate_limit_daily || 30;
    valRateDaily.textContent = sec.rate_limit_daily || 30;
  }

  valBlockedCount.textContent = sec.blocked_phones_count || 0;

  if (sec.blocked_phones && sec.blocked_phones.length > 0) {
    blockedBox.classList.remove("hidden");
    blockedBox.innerHTML = "";
    sec.blocked_phones.forEach(b => {
      const item = document.createElement("div");
      item.className = "blocked-item";
      item.innerHTML = `
        <span><code>${escapeHtml(b.phone)}</code> (${b.remaining_seconds}s)</span>
        <button class="btn btn-sm btn-outline" onclick="handleUnblockPhone('${escapeHtml(b.phone)}')">Engeli Kaldır</button>
      `;
      blockedBox.appendChild(item);
    });
  } else {
    blockedBox.classList.add("hidden");
  }
}

async function handleSecuritySave() {
  const rate_limit_per_minute = parseInt(document.getElementById("input-rate-min").value, 10);
  const rate_limit_daily = parseInt(document.getElementById("input-rate-daily").value, 10);

  document.getElementById("val-rate-min").textContent = rate_limit_per_minute;
  document.getElementById("val-rate-daily").textContent = rate_limit_daily;

  try {
    await fetch(`${API_BASE}/api/dashboard/security`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rate_limit_per_minute, rate_limit_daily }),
    });
  } catch (err) {
    console.error("Failed to update security settings:", err);
  }
}

async function handleUnblockPhone(phone) {
  try {
    await fetch(`${API_BASE}/api/dashboard/security/unblock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    fetchStatus();
  } catch (err) {
    alert("Engeli kaldırırken hata oluştu: " + err.message);
  }
}

// =========================================================================
// Remote Pairing Code (QR-less Linking)
// =========================================================================

async function switchPairingMode(mode) {
  const tabCode = document.getElementById("tab-pair-code");
  const tabQr = document.getElementById("tab-pair-qr");
  const sectionCode = document.getElementById("section-pair-code");
  const sectionQr = document.getElementById("section-pair-qr");

  if (mode === "code") {
    if (tabCode) tabCode.classList.add("active");
    if (tabQr) tabQr.classList.remove("active");
    if (sectionCode) sectionCode.classList.remove("hidden");
    if (sectionQr) sectionQr.classList.add("hidden");
  } else {
    if (tabQr) tabQr.classList.add("active");
    if (tabCode) tabCode.classList.remove("active");
    if (sectionQr) sectionQr.classList.remove("hidden");
    if (sectionCode) sectionCode.classList.add("hidden");
  }

  // If already connected, no need to toggle WhatsApp Web screens
  if (currentBridgeState === "CONNECTED") return;

  try {
    const qrPlaceholder = document.getElementById("qr-placeholder");
    const qrSpinner = document.getElementById("qr-spinner");
    const qrImage = document.getElementById("qr-image");

    if (mode === "qr") {
      if (qrPlaceholder) qrPlaceholder.classList.add("hidden");
      if (qrImage && !qrImage.src) qrImage.classList.add("hidden");
      if (qrSpinner) qrSpinner.classList.remove("hidden");
    }

    const res = await fetch(`${API_BASE}/api/bridge/switch-mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      if (mode === "qr" && data.qr) {
        if (qrSpinner) qrSpinner.classList.add("hidden");
        if (qrImage) {
          qrImage.classList.remove("hidden");
          qrImage.src = data.qr;
        }
      }
    }
    fetchStatus();
  } catch (err) {
    console.warn("Could not sync pairing mode with bridge:", err.message);
  }
}

function formatPairingCode(raw) {
  if (!raw) return "---- - ----";
  const clean = String(raw).replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
  if (clean.length === 8) {
    return `${clean.substring(0, 4)} - ${clean.substring(4)}`;
  }
  return clean;
}

async function handleRequestPairingCode() {
  const inputPhone = document.getElementById("input-pairing-phone");
  const btn = document.getElementById("btn-request-pair-code");
  const textBtn = document.getElementById("text-btn-pair-code");
  const banner = document.getElementById("banner-pairing-code");
  const valCode = document.getElementById("val-pairing-code");

  const rawPhone = inputPhone?.value.trim() || "";
  const cleanPhone = rawPhone.replace(/\D/g, "");

  if (cleanPhone.length < 10) {
    showToast("warning", "Eksik Numara", "Lütfen en az 10 haneli geçerli bir cep telefonu numarası giriniz.");
    return;
  }

  try {
    if (btn) btn.disabled = true;
    if (textBtn) textBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Kod İsteniyor...`;
    if (valCode) valCode.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
    if (banner) banner.classList.remove("hidden");

    showToast("info", "Kod Üretiliyor", "WhatsApp sunucularından eşleştirme kodu isteniyor...");

    const res = await fetch(`${API_BASE}/api/bridge/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone_number: cleanPhone }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Eşleştirme kodu başlatılamadı");
    }

    const data = await res.json().catch(() => ({}));
    if (data.code || data.pairingCode) {
      const code = data.code || data.pairingCode;
      if (valCode) valCode.textContent = formatPairingCode(code);
      if (banner) banner.classList.remove("hidden");
      showToast("success", "Kod Hazır!", "WhatsApp 8 haneli eşleştirme kodu oluşturuldu.");
      return;
    }

    // Fast poll for the pairing code
    let attempts = 0;
    const pollInterval = setInterval(async () => {
      attempts++;
      await fetchStatus();

      const valCodeElem = document.getElementById("val-pairing-code");
      if (valCodeElem && valCodeElem.textContent && !valCodeElem.textContent.includes("fa-spin") && valCodeElem.textContent !== "---- - ----") {
        clearInterval(pollInterval);
        showToast("success", "Kod Hazır!", "Müşterinize iletebileceğiniz 8 haneli kod oluşturuldu.");
      }

      if (currentBridgeState === "CONNECTED" || attempts > 25) {
        clearInterval(pollInterval);
      }
    }, 1000);
  } catch (err) {
    showToast("error", "Eşleştirme Hatası", err.message);
    if (banner) banner.classList.add("hidden");
  } finally {
    if (btn) btn.disabled = false;
    if (textBtn) textBtn.textContent = "Eşleştirme Kodu Üret";
  }
}

function copyOnlyPairingCode() {
  const codeElem = document.getElementById("val-pairing-code");
  const code = (codeElem?.textContent || "").replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
  if (!code || code.length < 4) return;

  navigator.clipboard.writeText(code).then(() => {
    showToast("info", "Kod Kopyalandı", `"${code}" panoya kopyalandı.`);
  });
}

function copyCustomerWhatsappText() {
  const codeElem = document.getElementById("val-pairing-code");
  const code = (codeElem?.textContent || "").replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
  const formatted = code.length === 8 ? `${code.substring(0, 4)}-${code.substring(4)}` : code;

  const text = `Merhaba, WhatsApp yapay zeka kamp asistanı bağlantısını tamamlamak için lütfen şu adımları yapın:\n\n1️⃣ WhatsApp uygulamasını açın > Sağ üstteki 3 nokta > "Bağlı Cihazlar"\n2️⃣ "Cihaz Bağla" butonuna basın\n3️⃣ Alttaki "Telefon Numarası ile Bağla" seçeneğine tıklayın\n4️⃣ Ekrana şu 8 haneli kodu girin:\n\n👉 *${formatted}*\n\n(Kod yaklaşık 3 dakika geçerlidir)`;

  navigator.clipboard.writeText(text).then(() => {
    showToast("success", "Mesaj Panoya Kopyalandı!", "WhatsApp'a yapıştırıp müşterinize doğrudan gönderebilirsiniz.");
  });
}

// =========================================================================
// 2. Bridge Control Actions
// =========================================================================

async function handleBridgeConnect() {
  const btn = document.getElementById("btn-connect");
  const qrPlaceholder = document.getElementById("qr-placeholder");
  const qrSpinner = document.getElementById("qr-spinner");
  const qrImage = document.getElementById("qr-image");
  const qrBox = document.getElementById("qr-box");
  const connectedProfile = document.getElementById("connected-profile");

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Başlatılıyor...`;
    }
    if (connectedProfile) connectedProfile.classList.add("hidden");
    if (qrBox) qrBox.classList.remove("hidden");
    if (qrPlaceholder) qrPlaceholder.classList.add("hidden");
    if (qrImage) qrImage.classList.add("hidden");
    if (qrSpinner) qrSpinner.classList.remove("hidden");

    const res = await fetch(`${API_BASE}/api/bridge/connect`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Köprü başlatılamadı");
    }
    const data = await res.json();
    console.log("Connect response:", data);
    if (data.qr) {
      if (qrSpinner) qrSpinner.classList.add("hidden");
      if (qrImage) {
        qrImage.classList.remove("hidden");
        qrImage.src = data.qr;
      }
    }

    // Fast poll for the QR code
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      await fetchStatus();
      if (currentBridgeState === "QR_READY" || currentBridgeState === "CONNECTED" || attempts > 20) {
        clearInterval(interval);
      }
    }, 800);
  } catch (err) {
    showToast("error", "Köprü Hatası", "Köprü başlatılırken hata: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-link"></i> <span id="btn-connect-text">Bağlan / QR Yenile</span>`;
    }
  }
}

async function handleBridgeDisconnect(clearSession = false) {
  const confirmMsg = clearSession
    ? "WhatsApp oturum verilerini (LocalAuth) tamamen temizlemek ve sıfırlamak istediğinize emin misiniz? Tekrar bağlanmak için QR okutmanız gerekecektir."
    : "WhatsApp oturum bağlantısını kesmek istediğinize emin misiniz?";

  if (!confirm(confirmMsg)) return;

  const btnDisconnect = document.getElementById("btn-disconnect");
  const btnUnlink = document.getElementById("btn-unlink-cache");
  const targetBtn = clearSession ? btnUnlink : btnDisconnect;

  try {
    if (targetBtn) {
      targetBtn.disabled = true;
      targetBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> İşleniyor...`;
    }

    const res = await fetch(`${API_BASE}/api/bridge/disconnect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clearSession: !!clearSession })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "Bağlantı kesilemedi");
    }

    const data = await res.json();
    console.log("Disconnect response:", data);

    showToast(
      "info",
      clearSession ? "Oturum Sıfırlandı" : "Bağlantı Kesildi",
      clearSession
        ? "WhatsApp oturum önbelleği silindi ve bağlantı kesildi. Yeni QR okutabilirsiniz."
        : "WhatsApp bağlantısı başarıyla kapatıldı."
    );

    // Refresh UI & state immediately
    currentBridgeState = "DISCONNECTED";
    await fetchStatus();
  } catch (err) {
    showToast("error", "Bağlantı Hatası", err.message);
  } finally {
    if (targetBtn) {
      targetBtn.disabled = false;
      if (clearSession) {
        targetBtn.innerHTML = `<i class="fa-solid fa-trash-can"></i> Oturumu Sıfırla`;
      } else {
        targetBtn.innerHTML = `<i class="fa-solid fa-unlink"></i> Bağlantıyı Kes`;
      }
    }
  }
}

async function handleStopBridgeService() {
  if (!confirm("Arka plandaki Node.js köprü sürecini durdurmak istediğinize emin misiniz?")) return;

  const btn = document.getElementById("btn-stop-bridge");
  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Durduruluyor...`;
    }

    const res = await fetch(`${API_BASE}/api/system/stop-bridge`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Köprü durdurulamadı");
    }

    showToast("warning", "Köprü Durduruldu", "WhatsApp köprü servisi durduruldu.");
    currentBridgeState = "OFFLINE";
    await fetchStatus();
  } catch (err) {
    showToast("error", "Hata", err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-stop"></i> Köprüyü Kapat`;
    }
  }
}

async function handleStartServices() {
  const navBtn = document.getElementById("btn-start-services");
  const cardBtn = document.getElementById("card-btn-start-services");

  const setBtnLoading = (loading) => {
    [navBtn, cardBtn].forEach(btn => {
      if (btn) {
        btn.disabled = loading;
        if (loading) {
          btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Başlatılıyor...</span>`;
        } else {
          btn.innerHTML = `<i class="fa-solid fa-play"></i> <span>Servisleri Başlat</span>`;
        }
      }
    });
  };

  try {
    setBtnLoading(true);
    showToast("info", "Servisler Başlatılıyor", "WhatsApp köprüsü ve arka plan servisleri başlatılıyor...");

    const res = await fetch(`${API_BASE}/api/system/start-services`, { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.detail || data.error || "Servisler başlatılamadı.");
    }

    showToast("success", "Başarılı", data.message || "Servisler aktif edildi!");

    // Immediate status refresh
    await fetchStatus();

    // Fast poll for bridge state and QR
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      await fetchStatus();
      if (currentBridgeState === "CONNECTED") {
        clearInterval(interval);
        showToast("success", "WhatsApp Bağlandı", "WhatsApp istemcisi başarıyla bağlandı!");
      } else if (currentBridgeState === "QR_READY") {
        clearInterval(interval);
        showToast("warning", "QR Hazır", "WhatsApp bağlantısı için lütfen Ayarlar > WhatsApp sayfasındaki QR kodu taratın.");
      } else if (attempts > 12) {
        clearInterval(interval);
      }
    }, 1000);
  } catch (err) {
    showToast("error", "Başlatma Hatası", err.message);
  } finally {
    setBtnLoading(false);
  }
}

async function handleStopBridgeService() {
  if (!confirm("Arka plandaki WhatsApp Bridge (Node.js ve Chromium) süreçlerini tamamen sonlandırmak istediğinize emin misiniz?")) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/system/stop-bridge`, { method: "POST" });
    const data = await res.json();
    showToast("info", "Köprü Kapatıldı", data.message || "WhatsApp köprü süreçleri sonlandırıldı.");
    fetchStatus();
  } catch (err) {
    showToast("error", "Hata", "Köprü durdurulurken hata: " + err.message);
  }
}

async function handleSystemShutdown() {
  if (!confirm("TÜM ARKA PLAN SÜREÇLERİNİ (WhatsApp Bridge, Chromium ve FastAPI Backend) tamamen kapatmak istediğinize emin misiniz?\n\nBu işlem tüm servisleri sonlandırır.")) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/system/shutdown`, { method: "POST" });
    const data = await res.json();

    // Show shutdown banner
    document.body.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #0b141a; color: #e9edef; font-family: sans-serif; text-align: center; padding: 20px;">
        <div style="font-size: 3rem; color: #f15c6d; margin-bottom: 16px;"><i class="fa-solid fa-power-off"></i></div>
        <h2 style="margin-bottom: 8px;">Tüm Servisler Başarıyla Kapatıldı</h2>
        <p style="color: #8696a0; max-width: 450px; margin-bottom: 24px;">Arka plandaki Node.js, Chromium ve FastAPI sunucusu sonlandırıldı. Bu sekmeyi kapatabilirsiniz.</p>
        <button onclick="window.location.reload()" style="background: #202c33; border: 1px solid rgba(255,255,255,0.2); color: #fff; padding: 10px 20px; border-radius: 9999px; cursor: pointer;">
          Yeniden Başlatmayı Dene
        </button>
      </div>
    `;
  } catch (err) {
    showToast("warning", "Sistem Kapatma", "Kapatma isteği iletildi: " + err.message);
  }
}

async function handlePrefixSave() {
  const prefix = document.getElementById("input-prefix").value.trim();
  try {
    const res = await fetch(`${API_BASE}/api/bridge/prefix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prefix }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("success", "Önek Güncellendi", `Tetikleyici mesaj öneki: "${prefix}"`);
      document.getElementById("preview-prefix").textContent = prefix || "(önek yok)";
      fetchStatus();
    }
  } catch (err) {
    showToast("error", "Hata", "Önek kaydedilemedi: " + err.message);
  }
}

// =========================================================================
// Filter & Dynamic LLM API Settings
// =========================================================================

async function fetchFilterSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/settings/filters`);
    if (!res.ok) return;
    const data = await res.json();

    const toggleUnknown = document.getElementById("toggle-unknown-only");
    if (toggleUnknown && data.only_unknown_contacts !== undefined) {
      toggleUnknown.checked = data.only_unknown_contacts;
    }

    const toggleAutoMute = document.getElementById("toggle-auto-mute");
    if (toggleAutoMute && data.auto_mute_on_reservation !== undefined) {
      toggleAutoMute.checked = data.auto_mute_on_reservation;
    }

    const inputPrefix = document.getElementById("input-prefix");
    if (inputPrefix && data.trigger_prefix !== undefined) {
      inputPrefix.value = data.trigger_prefix;
      const previewPrefix = document.getElementById("preview-prefix");
      if (previewPrefix) previewPrefix.textContent = data.trigger_prefix || "(önek yok)";
    }

    const inputDebounce = document.getElementById("input-debounce");
    const valDebounce = document.getElementById("val-debounce");
    if (inputDebounce && data.debounce_seconds !== undefined) {
      inputDebounce.value = data.debounce_seconds;
      if (valDebounce) valDebounce.textContent = `${data.debounce_seconds} sn`;
    }

    const inputAdminPhone = document.getElementById("input-admin-phone");
    if (inputAdminPhone && data.admin_notify_phone !== undefined) {
      inputAdminPhone.value = data.admin_notify_phone;
    }

    const inputBlacklist = document.getElementById("input-blacklist");
    if (inputBlacklist && Array.isArray(data.blacklist)) {
      inputBlacklist.value = data.blacklist.join(", ");
    }

    const inputNtfy = document.getElementById("input-ntfy-topic");
    if (inputNtfy && data.ntfy_topic) {
      inputNtfy.value = data.ntfy_topic;
      updateNtfyLinks(data.ntfy_topic);
    }

    // Update API Key status badge
    const badge = document.getElementById("api-key-badge");
    if (badge) {
      if (data.has_llm_api_key) {
        badge.className = "api-key-badge badge-success";
        badge.innerHTML = `<i class="fa-solid fa-circle-check"></i> ${data.llm_provider?.toUpperCase() || 'API'} Aktif (${data.masked_api_key})`;
      } else {
        badge.className = "api-key-badge badge-neutral";
        badge.innerHTML = `<i class="fa-solid fa-circle-info"></i> API Anahtarı Tanımlı Değil (Varsayılan Model)`;
      }
    }

    // Select current model if available
    const selectModel = document.getElementById("select-model");
    if (selectModel && data.llm_model) {
      for (let i = 0; i < selectModel.options.length; i++) {
        if (selectModel.options[i].value === data.llm_model) {
          selectModel.selectedIndex = i;
          break;
        }
      }
    }
  } catch (err) {
    console.warn("Could not load filter settings:", err.message);
  }
}

async function handleFilterSettingsSave() {
  const onlyUnknown = document.getElementById("toggle-unknown-only")?.checked;
  const autoMute = document.getElementById("toggle-auto-mute")?.checked;
  const prefix = document.getElementById("input-prefix")?.value;
  const debounce = parseInt(document.getElementById("input-debounce")?.value || "30", 10);
  const adminPhone = document.getElementById("input-admin-phone")?.value;
  const blacklistStr = document.getElementById("input-blacklist")?.value || "";
  const blacklist = blacklistStr.split(",").map(s => s.trim()).filter(Boolean);
  const ntfyTopic = document.getElementById("input-ntfy-topic")?.value;

  try {
    const res = await fetch(`${API_BASE}/api/settings/filters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        only_unknown_contacts: onlyUnknown,
        auto_mute_on_reservation: autoMute,
        trigger_prefix: prefix,
        debounce_seconds: debounce,
        admin_notify_phone: adminPhone,
        blacklist: blacklist,
        ntfy_topic: ntfyTopic,
      }),
    });
    if (!res.ok) throw new Error("Ayarlar kaydedilemedi");
    showToast("success", "Ayarlar Kaydedildi", "Filtre ve davranış ayarları güncellendi.");
    fetchFilterSettings();
  } catch (err) {
    showToast("error", "Kayıt Hatası", err.message);
  }
}

// =========================================================================
// AI Knowledge Base Management
// =========================================================================

async function fetchKnowledgeSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/settings/knowledge`);
    if (!res.ok) return;
    const data = await res.json();
    const textarea = document.getElementById("knowledge-textarea");
    if (textarea && data.knowledge !== undefined) {
      textarea.value = data.knowledge;
      updateKnowledgeCounters();
    }
    const badge = document.getElementById("kb-status-badge");
    if (badge) {
      if (data.is_custom) {
        badge.className = "badge badge-accent";
        badge.innerHTML = `<i class="fa-solid fa-pen-to-square"></i> Özel Bilgi Aktif`;
      } else {
        badge.className = "badge badge-success";
        badge.innerHTML = `<i class="fa-solid fa-circle-check"></i> Varsayılan Aktif`;
      }
    }
  } catch (err) {
    console.warn("Could not fetch knowledge settings:", err);
  }
}

function updateKnowledgeCounters() {
  const textarea = document.getElementById("knowledge-textarea");
  if (!textarea) return;
  const text = textarea.value;
  const charCount = text.length;
  const lineCount = text ? text.split("\n").length : 0;

  const charEl = document.getElementById("kb-char-count");
  if (charEl) {
    charEl.innerHTML = `<i class="fa-solid fa-font"></i> ${charCount.toLocaleString("tr-TR")} Karakter`;
  }
  const lineEl = document.getElementById("kb-line-count");
  if (lineEl) {
    lineEl.innerHTML = `<i class="fa-solid fa-bars-staggered"></i> ${lineCount.toLocaleString("tr-TR")} Satır`;
  }
}

async function handleKnowledgeSave() {
  const textarea = document.getElementById("knowledge-textarea");
  const btn = document.getElementById("btn-save-knowledge");
  if (!textarea) return;

  const content = textarea.value.trim();
  if (!content) {
    showToast("error", "Hata", "Bilgi bankası metni boş bırakılamaz!");
    return;
  }

  const originalBtnHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Kaydediliyor...</span>`;
  }

  try {
    const res = await fetch(`${API_BASE}/api/settings/knowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ knowledge: content }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("success", "Başarılı", data.message || "Bilgi bankası kaydedildi!");
      updateKnowledgeCounters();
      const badge = document.getElementById("kb-status-badge");
      if (badge) {
        badge.className = "badge badge-accent";
        badge.innerHTML = `<i class="fa-solid fa-pen-to-square"></i> Özel Bilgi Aktif`;
      }
    } else {
      showToast("error", "Kaydedilemedi", data.detail || "Bir hata oluştu.");
    }
  } catch (err) {
    showToast("error", "Bağlantı Hatası", err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalBtnHtml;
    }
  }
}

async function handleKnowledgeReset() {
  if (!confirm("Bilgi bankasını orijinal varsayılan metne sıfırlamak istediğinizden emin misiniz? Yapılan özel değişiklikler geri alınacaktır.")) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/settings/knowledge/reset`, {
      method: "POST",
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const textarea = document.getElementById("knowledge-textarea");
      if (textarea && data.knowledge) {
        textarea.value = data.knowledge;
        updateKnowledgeCounters();
      }
      const badge = document.getElementById("kb-status-badge");
      if (badge) {
        badge.className = "badge badge-success";
        badge.innerHTML = `<i class="fa-solid fa-circle-check"></i> Varsayılan Aktif`;
      }
      showToast("success", "Sıfırlandı", "Bilgi bankası varsayılan orijinal haline getirildi.");
    } else {
      showToast("error", "Hata", data.detail || "Sıfırlama başarısız.");
    }
  } catch (err) {
    showToast("error", "Bağlantı Hatası", err.message);
  }
}

function copyKnowledgeContent() {
  const textarea = document.getElementById("knowledge-textarea");
  if (!textarea || !textarea.value) {
    showToast("warning", "Uyarı", "Kopyalanacak metin yok.");
    return;
  }
  navigator.clipboard.writeText(textarea.value).then(() => {
    showToast("success", "Kopyalandı", "Bilgi bankası panoya kopyalandı.");
  }).catch(() => {
    textarea.select();
    document.execCommand("copy");
    showToast("success", "Kopyalandı", "Bilgi bankası panoya kopyalandı.");
  });
}

function clearKnowledgeEditor() {
  const textarea = document.getElementById("knowledge-textarea");
  if (!textarea) return;
  if (confirm("Metin alanını temizlemek istediğinizden emin misiniz? (Kaydet butonuna basana kadar kalıcı olarak silinmez)")) {
    textarea.value = "";
    updateKnowledgeCounters();
    textarea.focus();
  }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById("input-api-key");
  const icon = document.getElementById("icon-toggle-key");
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    if (icon) icon.className = "fa-solid fa-eye-slash";
  } else {
    input.type = "password";
    if (icon) icon.className = "fa-solid fa-eye";
  }
}

async function handleApiKeySave() {
  const inputKey = document.getElementById("input-api-key");
  const selectModel = document.getElementById("select-model");
  const btn = document.getElementById("btn-save-api-key");
  const textBtn = document.getElementById("text-save-api-key");
  const badge = document.getElementById("api-key-badge");

  const apiKey = inputKey?.value.trim() || "";
  if (!apiKey) {
    showToast("warning", "Eksik Bilgi", "Lütfen geçerli bir API anahtarı giriniz.");
    return;
  }

  let selectedModel = selectModel?.value || "gpt-4o-mini";
  let provider = "openai";

  if (apiKey.startsWith("gsk_")) {
    provider = "groq";
    if (!selectedModel.includes("llama")) selectedModel = "llama-3.3-70b-versatile";
  } else if (apiKey.startsWith("sk-or-")) {
    provider = "openrouter";
    selectedModel = "meta-llama/llama-3.3-70b-instruct";
  } else if (apiKey.startsWith("sk-")) {
    provider = "openai";
    if (!selectedModel.startsWith("gpt")) {
      selectedModel = "gpt-4o-mini";
    }
  }

  // Auto-sync select dropdown UI
  if (selectModel) {
    selectModel.value = selectedModel;
  }

  try {
    if (btn) btn.disabled = true;
    if (textBtn) textBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Doğrulanıyor...`;
    if (badge) {
      badge.className = "api-key-badge badge-neutral";
      badge.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Bağlantı test ediliyor...`;
    }

    const res = await fetch(`${API_BASE}/api/settings/llm/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey,
        provider: provider,
        model: selectedModel,
      }),
    });

    const data = await res.json();
    if (data.success) {
      showToast("success", "API Doğrulandı!", data.message);
      if (badge) {
        badge.className = "api-key-badge badge-success";
        badge.innerHTML = `<i class="fa-solid fa-circle-check"></i> ${data.provider.toUpperCase()} Aktif (${data.masked_key})`;
      }
      if (inputKey) inputKey.value = ""; // Clear plain text
      fetchStatus();
    } else {
      showToast("error", "Doğrulama Başarısız", data.message || "API anahtarı kabul edilmedi.");
      if (badge) {
        badge.className = "api-key-badge badge-warning";
        badge.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> Hata: ${data.message || 'Geçersiz anahtar'}`;
      }
    }
  } catch (err) {
    showToast("error", "Bağlantı Hatası", "API doğrulaması yapılamadı: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
    if (textBtn) textBtn.textContent = "Doğrula & Kaydet";
  }
}

async function handleSendNtfyTest() {
  const btn = document.getElementById("btn-ntfy-test");
  const topic = document.getElementById("input-ntfy-topic")?.value || "masal-kamp-admin";
  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Gönderiliyor...`;
    }
    const res = await fetch(`${API_BASE}/api/settings/ntfy/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("success", "Test Alarmı Çaldı!", "Telefonunuza test bildirimi iletildi.");
    } else {
      throw new Error(data.detail || "Bildirim gönderilemedi");
    }
  } catch (err) {
    showToast("error", "Alarm Hatası", err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-bell"></i> Telefonuma Test Alarmı Çal`;
    }
  }
}

function updateNtfyLinks(topic) {
  const cleanTopic = (topic || document.getElementById("input-ntfy-topic")?.value || "masal-kamp-admin").trim().toLowerCase();
  const codeTopic = document.getElementById("code-ntfy-topic");
  const quickTopic = document.getElementById("quick-ntfy-topic");
  const qrImg = document.getElementById("img-ntfy-qr");
  const textUrl = document.getElementById("text-ntfy-url");
  const webLink = document.getElementById("link-ntfy-web");

  if (codeTopic) codeTopic.textContent = cleanTopic;
  if (quickTopic) quickTopic.textContent = cleanTopic;
  if (textUrl) textUrl.textContent = `ntfy.sh/${cleanTopic}`;
  if (webLink) webLink.href = `https://ntfy.sh/${cleanTopic}`;
  if (qrImg) qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=140x140&data=https://ntfy.sh/${cleanTopic}&bgcolor=20-2c-33&color=e9-ed-ef`;
}

function copyNtfyTopic() {
  const topic = document.getElementById("code-ntfy-topic")?.textContent || "masal-kamp-admin";
  navigator.clipboard.writeText(topic).then(() => {
    const copyBtnText = document.getElementById("btn-copy-text");
    if (copyBtnText) {
      const orig = copyBtnText.textContent;
      copyBtnText.textContent = "Kopyalandı!";
      setTimeout(() => { copyBtnText.textContent = orig; }, 2000);
    }
    showToast("info", "Kanal Kopyalandı", `"${topic}" panoya kopyalandı.`);
  });
}

async function handleModelChange() {
  const select = document.getElementById("select-model");
  const model = select.value;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/set-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("success", "Model Değiştirildi", `Aktif model: ${model}`);
      fetchStatus();
    }
  } catch (err) {
    showToast("error", "Model Hatası", "Model değiştirilemedi: " + err.message);
  }
}

async function handleClearMemory() {
  if (!confirm("Tüm SQLite konuşma geçmişini temizlemek istediğinize emin misiniz?")) return;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/clear-memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    showToast("info", "Hafıza Temizlendi", `${data.cleared_count || 0} mesaj silindi.`);
    fetchConversations();
    fetchActiveConversationMessages();
    fetchMessages();
    fetchStatus();
  } catch (err) {
    showToast("error", "Hata", "Hafıza temizlenirken hata: " + err.message);
  }
}

function switchLeftTab(tabId) {
  const buttons = document.querySelectorAll(".panel-tab");
  buttons.forEach(b => b.classList.remove("active"));
  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  if (activeBtn) activeBtn.classList.add("active");

  const cards = {
    bridge: document.getElementById("card-bridge"),
    filters: document.getElementById("card-filters"),
    ntfy: document.getElementById("card-ntfy"),
    security: document.getElementById("card-security"),
    server: document.getElementById("card-server")
  };

  if (tabId === "all") {
    Object.values(cards).forEach(c => c && c.classList.remove("hidden"));
  } else {
    Object.keys(cards).forEach(key => {
      if (cards[key]) {
        if (key === tabId) cards[key].classList.remove("hidden");
        else cards[key].classList.add("hidden");
      }
    });
  }
}

function showToast(type = "info", title = "", message = "") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const icons = {
    success: "fa-solid fa-circle-check",
    warning: "fa-solid fa-triangle-exclamation",
    error: "fa-solid fa-circle-xmark",
    info: "fa-solid fa-circle-info"
  };

  const toast = document.createElement("div");
  toast.className = `toast-item toast-${type}`;
  toast.innerHTML = `
    <i class="${icons[type] || icons.info}"></i>
    <div class="toast-content">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(message)}</p>
    </div>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = "toastFadeOut 0.3s forwards";
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }, 3500);
}

async function copyNtfyTopic() {
  const ntfyTopicEl = document.getElementById("input-ntfy-topic");
  const topic = (ntfyTopicEl && ntfyTopicEl.value.trim()) || "masal-kamp-admin";
  const btnText = document.getElementById("btn-copy-text");

  try {
    await navigator.clipboard.writeText(topic);
    if (btnText) {
      const orig = btnText.textContent;
      btnText.textContent = "Kopyalandı! ✓";
      setTimeout(() => { btnText.textContent = orig; }, 2000);
    }
    showToast("success", "Kopyalandı", `Kanal kodu (${topic}) panoya kopyalandı.`);
  } catch (err) {
    showToast("info", "Kanal Adı", topic);
  }
}

function updateNtfyLinks() {
  const ntfyTopicEl = document.getElementById("input-ntfy-topic");
  const topic = (ntfyTopicEl && ntfyTopicEl.value.trim()) || "masal-kamp-admin";
  const webLinkEl = document.getElementById("link-ntfy-web");
  const textUrlEl = document.getElementById("text-ntfy-url");
  const codeTopicEl = document.getElementById("code-ntfy-topic");
  const qrImg = document.getElementById("img-ntfy-qr");

  if (webLinkEl) webLinkEl.href = `https://ntfy.sh/${topic}`;
  if (textUrlEl) textUrlEl.textContent = `ntfy.sh/${topic}`;
  if (codeTopicEl) codeTopicEl.textContent = topic;
  if (qrImg) {
    qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=140x140&data=https://ntfy.sh/${encodeURIComponent(topic)}&bgcolor=20-2c-33&color=e9-ed-ef`;
  }
}

async function handleFilterSettingsSave() {
  const only_unknown_contacts = document.getElementById("toggle-unknown-only").checked;
  const debounce_seconds = parseInt(document.getElementById("input-debounce").value, 10) || 30;
  const admin_notify_phone = document.getElementById("input-admin-phone").value.trim();
  const rawBlacklist = document.getElementById("input-blacklist").value;
  const blacklist = rawBlacklist.split(",").map(x => x.trim()).filter(Boolean);
  const ntfyTopicEl = document.getElementById("input-ntfy-topic");
  const ntfy_topic = (ntfyTopicEl && ntfyTopicEl.value.trim()) || "masal-kamp-admin";

  const debounceValEl = document.getElementById("val-debounce");
  if (debounceValEl) debounceValEl.textContent = `${debounce_seconds} sn`;

  updateNtfyLinks();

  try {
    const res = await fetch(`${API_BASE}/api/settings/filters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        only_unknown_contacts,
        debounce_seconds,
        admin_notify_phone,
        blacklist,
        ntfy_topic,
        ntfy_enabled: true,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("success", "Ayarlar Kaydedildi", "Filtre ve telefon alarmı ayarları kaydedildi.");
    }
  } catch (err) {
    showToast("error", "Hata", "Filtre ayarları kaydedilemedi: " + err.message);
  }
}

async function handleSendNtfyTest() {
  const btn = document.getElementById("btn-ntfy-test");
  const originalHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Gönderiliyor...`;
  }

  // Ensure topic is saved first
  await handleFilterSettingsSave();

  try {
    const res = await fetch(`${API_BASE}/api/settings/ntfy/test`, {
      method: "POST",
    });
    const data = await res.json();
    if (data.success) {
      showToast("success", "Alarm Gönderildi! 🔔", "Telefonunuza test alarmı başarıyla ulaştı.");
      if (btn) {
        btn.innerHTML = `<i class="fa-solid fa-check" style="color:#00a884;"></i> Alarm Gönderildi!`;
        setTimeout(() => {
          btn.innerHTML = originalHtml;
          btn.disabled = false;
        }, 3000);
      }
    } else {
      showToast("error", "Bildirim Hatası", data.error || "Bilinmeyen hata");
      if (btn) {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
      }
    }
  } catch (err) {
    showToast("error", "Bağlantı Hatası", err.message);
    if (btn) {
      btn.innerHTML = originalHtml;
      btn.disabled = false;
    }
  }
}

async function toggleActiveChatMute() {
  const badgeMuted = document.getElementById("badge-chat-muted");
  const isCurrentlyMuted = !badgeMuted.classList.contains("hidden");

  try {
    if (isCurrentlyMuted) {
      // Unmute
      const res = await fetch(`${API_BASE}/api/chat/unmute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: activeChatPhone }),
      });
      const data = await res.json();
      if (data.success) {
        badgeMuted.classList.add("hidden");
        updateMuteButtonState(false);
        fetchConversations();
        showToast("success", "Bot Devreye Alındı", `${formatPhoneNumber(activeChatPhone)} için bot aktif edildi.`);
      }
    } else {
      // Mute for 2 hours (120 min)
      const res = await fetch(`${API_BASE}/api/chat/mute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: activeChatPhone, duration_minutes: 120, reason: "admin_manual_mute" }),
      });
      const data = await res.json();
      if (data.success) {
        badgeMuted.classList.remove("hidden");
        updateMuteButtonState(true);
        fetchConversations();
        showToast("warning", "Bot Susturuldu", `${formatPhoneNumber(activeChatPhone)} için bot 2 saat susturuldu.`);
      }
    }
  } catch (err) {
    showToast("error", "Hata", "Susturma durumu değiştirilemedi: " + err.message);
  }
}

function updateMuteButtonState(isMuted) {
  const btn = document.getElementById("btn-chat-mute");
  const text = document.getElementById("text-chat-mute");
  if (!btn || !text) return;

  if (isMuted) {
    btn.className = "btn btn-sm btn-outline-success";
    btn.innerHTML = `<i class="fa-solid fa-play"></i> <span id="text-chat-mute">Botu Devreye Al</span>`;
  } else {
    btn.className = "btn btn-sm btn-outline-warning";
    btn.innerHTML = `<i class="fa-solid fa-microphone-slash"></i> <span id="text-chat-mute">Botu Sustur (2 Sa)</span>`;
  }
}

// =========================================================================
// 3. Multi-Chat Management & Real WhatsApp Conversations Browser
// =========================================================================

async function fetchConversations() {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/conversations`);
    if (!res.ok) return;
    const data = await res.json();
    allConversations = data.conversations || [];
    renderConversationsList();
  } catch (err) {
    console.warn("Failed to fetch conversations:", err);
  }
}

function handleChatSearch(e) {
  searchQuery = (e.target.value || "").toLowerCase().trim();
  renderConversationsList();
}

function renderConversationsList() {
  const container = document.getElementById("conversations-list");
  if (!container) return;

  // Ensure default simulator is always in list
  let items = [...allConversations];
  const hasSim = items.some(c => c.phone === DEFAULT_SIMULATOR_PHONE);
  if (!hasSim) {
    items.unshift({
      phone: DEFAULT_SIMULATOR_PHONE,
      last_message: "Masal Kamp Destek Asistanı",
      last_role: "assistant",
      last_time: "Şimdi",
      msg_count: 0,
      is_muted: false,
      is_reservation_lead: false,
    });
  }

  // Filter by search query
  if (searchQuery) {
    items = items.filter(c =>
      c.phone.toLowerCase().includes(searchQuery) ||
      (c.last_message && c.last_message.toLowerCase().includes(searchQuery))
    );
  }

  container.innerHTML = "";

  if (items.length === 0) {
    container.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.8rem;">
        Eşleşen sohbet bulunamadı.
      </div>
    `;
    return;
  }

  items.forEach(c => {
    const isSim = c.phone === DEFAULT_SIMULATOR_PHONE;
    const isActive = c.phone === activeChatPhone;

    // Format Display Title
    let displayName = formatPhoneNumber(c.phone);
    if (isSim) displayName = "Web Simülatörü";

    // Format Avatar Initials
    const avatarInitials = isSim ? "WS" : displayName.slice(0, 2).replace("+", "");

    // Format snippet
    const snippet = c.last_message || "Yeni Konuşma";
    const timeStr = formatTime(c.last_time);

    // Status Badges in List
    let badgeHtml = "";
    if (c.is_reservation_lead) {
      badgeHtml += `<span class="conv-badge-lead" title="Rezervasyon Talebi">🏕️ Rezervasyon</span>`;
    }
    if (c.is_muted) {
      badgeHtml += `<span class="conv-badge-muted" title="Bot Susturuldu">⏸️ Susturuldu</span>`;
    }

    const div = document.createElement("div");
    div.className = `chat-item ${isActive ? "active" : ""}`;
    div.onclick = () => selectChat(c.phone);

    div.innerHTML = `
      <div class="chat-avatar ${isSim ? 'simulator-avatar' : ''}">
        ${isSim ? '<i class="fa-solid fa-laptop-code"></i>' : escapeHtml(avatarInitials)}
      </div>
      <div class="chat-meta">
        <div class="chat-meta-top">
          <span class="chat-name">${escapeHtml(displayName)} ${badgeHtml}</span>
          <span class="chat-time">${timeStr}</span>
        </div>
        <div class="chat-meta-bottom">
          <span class="chat-preview">${escapeHtml(snippet)}</span>
          <span class="chat-badge">${c.msg_count || (isSim ? 'Test' : '1')}</span>
        </div>
      </div>
    `;
    container.appendChild(div);
  });

  // Update Top Nav Live Metrics
  const statChats = document.getElementById("stat-chats-count");
  const statLeads = document.getElementById("stat-leads-count");
  const statMuted = document.getElementById("stat-muted-count");
  if (statChats) statChats.textContent = allConversations.length;
  if (statLeads) statLeads.textContent = allConversations.filter(c => c.is_reservation_lead).length;
  if (statMuted) statMuted.textContent = allConversations.filter(c => c.is_muted).length;
}

function selectChat(phone) {
  activeChatPhone = phone;

  // Update header meta
  const titleEl = document.getElementById("active-chat-title");
  const phoneEl = document.getElementById("active-chat-phone");
  const avatarEl = document.getElementById("active-chat-avatar");

  if (phone === DEFAULT_SIMULATOR_PHONE) {
    titleEl.innerHTML = `Masal Kamp Destek Asistanı <i class="fa-solid fa-circle-check verified-badge"></i>`;
    phoneEl.textContent = `${phone} (Web Simülatörü)`;
    avatarEl.innerHTML = `
      <img src="https://images.unsplash.com/photo-1510312305653-8ed496efae75?w=100&auto=format&fit=crop&q=80" alt="Camp Avatar" />
      <span class="online-indicator"></span>
    `;
  } else {
    const formatted = formatPhoneNumber(phone);
    titleEl.innerHTML = `${escapeHtml(formatted)} <i class="fa-solid fa-user-check verified-badge" style="color: #25d366;"></i>`;
    phoneEl.textContent = `${phone} (WhatsApp Kullanıcısı)`;
    avatarEl.innerHTML = `
      <div class="chat-avatar" style="width: 100%; height: 100%; font-size: 1.1rem; background: #3b82f6;">
        ${escapeHtml(formatted.slice(0, 2).replace("+", ""))}
      </div>
    `;
  }

  renderConversationsList();
  fetchActiveConversationMessages();
}

async function fetchActiveConversationMessages() {
  const container = document.getElementById("chat-messages");
  const typingIndicator = document.getElementById("typing-indicator");
  const badgeMuted = document.getElementById("badge-chat-muted");
  const badgeLead = document.getElementById("badge-chat-lead");

  try {
    const res = await fetch(`${API_BASE}/api/dashboard/conversation/${encodeURIComponent(activeChatPhone)}`);
    if (!res.ok) return;
    const data = await res.json();
    const messages = data.messages || [];
    const status = data.status || {};

    // Update Mute and Lead badges in Header
    if (badgeMuted) {
      if (status.is_muted) badgeMuted.classList.remove("hidden");
      else badgeMuted.classList.add("hidden");
    }
    if (badgeLead) {
      if (status.is_reservation_lead) badgeLead.classList.remove("hidden");
      else badgeLead.classList.add("hidden");
    }
    updateMuteButtonState(!!status.is_muted);

    // Update Chat Alert Banner inside chat pane
    const bannerEl = document.getElementById("chat-alert-banner");
    const bannerTitle = document.getElementById("banner-title");
    const bannerDesc = document.getElementById("banner-desc");
    const bannerBtn = document.getElementById("banner-action-btn");

    if (bannerEl && bannerTitle && bannerDesc && bannerBtn) {
      if (status.is_muted) {
        bannerEl.classList.remove("hidden");
        bannerEl.className = "chat-status-banner";
        bannerTitle.textContent = "Yetkili Devralma Aktif (Bot 2 Saat Susturuldu)";
        bannerDesc.textContent = "Bu müşteri yetkili talep ettiği için bot devre dışı bırakılmıştır. Doğrudan yazabilir veya susturmayı kaldırabilirsiniz.";
        bannerBtn.innerHTML = `<i class="fa-solid fa-play"></i> Susturmayı Aç`;
        bannerBtn.onclick = () => toggleActiveChatMute();
      } else if (status.is_reservation_lead) {
        bannerEl.classList.remove("hidden");
        bannerEl.className = "chat-status-banner banner-lead";
        bannerTitle.textContent = "⭐ Rezervasyon Talebi (Sıcak Aday)";
        bannerDesc.textContent = "Müşterinin rezervasyon niyeti tespit edilmiş ve ntfy üzerinden telefonunuza alarm iletilmiştir.";
        const cleanPhone = (activeChatPhone || "").replace(/[^0-9]/g, "");
        bannerBtn.innerHTML = `<a href="tel:${cleanPhone}" style="color:inherit; text-decoration:none;"><i class="fa-solid fa-phone"></i> Müşteriyi Ara</a>`;
        bannerBtn.onclick = null;
      } else {
        bannerEl.classList.add("hidden");
      }
    }

    // Clear and re-render
    container.innerHTML = "";

    const dateDivider = document.createElement("div");
    dateDivider.className = "chat-date-divider";
    dateDivider.innerHTML = `<span>BUGÜN — ${formatPhoneNumber(activeChatPhone)}</span>`;
    container.appendChild(dateDivider);

    if (messages.length === 0) {
      const emptyMsg = document.createElement("div");
      emptyMsg.className = "wa-msg wa-msg-bot";
      emptyMsg.innerHTML = `
        <div class="msg-bubble">
          <p>Merhaba! 🏕️ Masal Kamp Destek Asistanı aktif. Bu numara ile yapılan konuşmalar burada anlık olarak listelenir.</p>
          <span class="msg-time">${new Date().toLocaleTimeString().substring(0, 5)}</span>
        </div>
      `;
      container.appendChild(emptyMsg);
    } else {
      messages.forEach(m => {
        appendMessageBubble(m.role === "user" ? "user" : "bot", m.content, m.created_at);
      });
    }

    if (typingIndicator) container.appendChild(typingIndicator);
    container.scrollTop = container.scrollHeight;
  } catch (err) {
    console.warn("Failed to fetch conversation history for:", activeChatPhone, err);
  }
}

async function clearCurrentChatMemory() {
  if (!confirm(`"${formatPhoneNumber(activeChatPhone)}" numarasına ait konuşma geçmişini silmek istiyor musunuz?`)) return;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/clear-memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: activeChatPhone }),
    });
    fetchConversations();
    fetchActiveConversationMessages();
    fetchMessages();
    fetchStatus();
    showToast("info", "Sohbet Temizlendi", `${formatPhoneNumber(activeChatPhone)} konuşma geçmişi silindi.`);
  } catch (err) {
    showToast("error", "Hata", "Sohbet silinirken hata oluştu: " + err.message);
  }
}

function startNewTestChat() {
  const customPhone = prompt("Yeni bir test telefon numarası girin (Örn: 905321112233@c.us):", `90555${Math.floor(100000 + Math.random() * 900000)}@c.us`);
  if (!customPhone || !customPhone.trim()) return;
  selectChat(customPhone.trim());
}

// =========================================================================
// 4. Interactive WhatsApp Message Dispatcher
// =========================================================================

function sendPresetMessage(text) {
  document.getElementById("chat-input").value = text;
  handleSendMessage(new Event("submit"));
}

async function handleSendMessage(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("chat-input");
  const rawText = input.value.trim();
  if (!rawText) return;

  const autoPrefix = document.getElementById("auto-prefix-toggle").checked;
  const currentPrefix = document.getElementById("input-prefix").value.trim();

  let messageToSend = rawText;
  let isPrefixed = false;

  if (currentPrefix) {
    if (rawText.toLowerCase().startsWith(currentPrefix.toLowerCase())) {
      isPrefixed = true;
      messageToSend = rawText;
    } else if (rawText.toLowerCase() === "/reset") {
      isPrefixed = true;
      messageToSend = "/reset";
    } else if (autoPrefix) {
      isPrefixed = true;
      messageToSend = `${currentPrefix} ${rawText}`;
    }
  } else {
    isPrefixed = true;
  }

  // Display user's message bubble
  appendMessageBubble("user", messageToSend);
  input.value = "";

  // If message lacks trigger prefix when prefix is required, simulate WhatsApp ignore behavior
  if (!isPrefixed) {
    appendSystemNotice(`⚠️ <strong>[WhatsApp Filtresi Aktif]</strong> Mesajınız <code>${escapeHtml(currentPrefix)}</code> önekiyle başlamadığı için WhatsApp köprüsü tarafından yok sayıldı ve yapay zekaya iletilmedi.`);
    return;
  }

  // Show typing indicator
  showTypingIndicator(true);

  // Strip prefix for backend processing
  let webhookMessage = messageToSend;
  if (currentPrefix && webhookMessage.toLowerCase().startsWith(currentPrefix.toLowerCase())) {
    webhookMessage = webhookMessage.slice(currentPrefix.length).trim();
  }

  try {
    const res = await fetch(`${API_BASE}/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone: activeChatPhone,
        message: webhookMessage,
      }),
    });

    const data = await res.json();
    showTypingIndicator(false);

    if (res.ok && data.reply) {
      appendMessageBubble("bot", data.reply);
    } else {
      appendMessageBubble("bot", `Hata: ${data.detail || "Yanıt alınamadı."}`);
    }

    fetchConversations();
    fetchMessages();
    fetchStatus();
  } catch (err) {
    showTypingIndicator(false);
    appendMessageBubble("bot", `Bağlantı Hatası: ${err.message}`);
  }
}

function appendSystemNotice(htmlContent) {
  const container = document.getElementById("chat-messages");
  const typingIndicator = document.getElementById("typing-indicator");

  const noticeDiv = document.createElement("div");
  noticeDiv.className = "chat-system-notice";
  noticeDiv.innerHTML = htmlContent;

  container.insertBefore(noticeDiv, typingIndicator);
  container.scrollTop = container.scrollHeight;
}

function appendMessageBubble(role, text, timestamp = null) {
  const container = document.getElementById("chat-messages");
  const typingIndicator = document.getElementById("typing-indicator");

  const msgDiv = document.createElement("div");
  msgDiv.className = `wa-msg wa-msg-${role}`;

  let timeStr = "";
  if (timestamp) {
    timeStr = formatTime(timestamp);
  } else {
    const now = new Date();
    timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  }

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "msg-bubble";

  const p = document.createElement("p");
  p.textContent = text;
  bubbleDiv.appendChild(p);

  const timeSpan = document.createElement("span");
  timeSpan.className = "msg-time";
  timeSpan.innerHTML = `${timeStr} ${role === "user" ? '<i class="fa-solid fa-check-double check-icon"></i>' : ''}`;
  bubbleDiv.appendChild(timeSpan);

  msgDiv.appendChild(bubbleDiv);
  if (typingIndicator) {
    container.insertBefore(msgDiv, typingIndicator);
  } else {
    container.appendChild(msgDiv);
  }

  container.scrollTop = container.scrollHeight;
}

function showTypingIndicator(show) {
  const indicator = document.getElementById("typing-indicator");
  const container = document.getElementById("chat-messages");
  if (!indicator) return;
  if (show) {
    indicator.classList.remove("hidden");
    container.scrollTop = container.scrollHeight;
  } else {
    indicator.classList.add("hidden");
  }
}

// =========================================================================
// 5. Logs & SQLite Memory Tab Inspector
// =========================================================================

function switchTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));

  const btn = document.getElementById(`tab-btn-${tabName}`);
  const pane = document.getElementById(`pane-${tabName}`);
  if (btn) btn.classList.add("active");
  if (pane) pane.classList.add("active");

  if (tabName === "memory") {
    fetchMessages();
  }
}

function renderLogs(logs) {
  if (!logs || logs.length === 0) return;
  const container = document.getElementById("logs-container");
  if (!container) return;

  container.innerHTML = "";
  logs.forEach(log => {
    const entry = document.createElement("div");
    entry.className = `log-entry log-${log.type || 'info'}`;
    entry.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: baseline;">
        <span class="log-title">${escapeHtml(log.title)}</span>
        <span class="log-time">${log.timestamp}</span>
      </div>
      ${log.detail ? `<p class="log-detail">${escapeHtml(log.detail)}</p>` : ''}
    `;
    container.appendChild(entry);
  });

  if (logs.length !== lastKnownLogsCount) {
    container.scrollTop = container.scrollHeight;
    lastKnownLogsCount = logs.length;
  }
}

async function fetchMessages() {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/messages?limit=30`);
    if (!res.ok) return;
    const data = await res.json();
    renderMemoryView(data.messages || []);
  } catch (err) {
    console.warn("Failed to fetch SQLite memory:", err.message);
  }
}

function renderMemoryView(messages) {
  const container = document.getElementById("memory-container");
  if (!container) return;

  if (messages.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <i class="fa-solid fa-inbox"></i>
        <p>Kayıtlı mesaj bulunmuyor.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  messages.forEach(msg => {
    const item = document.createElement("div");
    item.className = "memory-item";
    const isUser = msg.role === "user";

    item.innerHTML = `
      <div class="memory-meta">
        <span class="memory-phone"><i class="fa-solid fa-phone"></i> ${escapeHtml(formatPhoneNumber(msg.phone))}</span>
        <span class="memory-badge ${isUser ? 'user' : 'assistant'}">${isUser ? 'Kullanıcı' : 'Yapay Zeka'}</span>
      </div>
      <p class="memory-text">${escapeHtml(msg.content)}</p>
      <span class="memory-time">${msg.created_at || ''}</span>
    `;
    item.onclick = () => selectChat(msg.phone);
    container.appendChild(item);
  });
}

// Utility Helpers
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatPhoneNumber(phone) {
  if (!phone) return "Bilinmeyen";
  let clean = phone.replace("@c.us", "").replace("@g.us", "");
  if (clean.startsWith("90") && clean.length === 12) {
    return `+90 ${clean.slice(2, 5)} ${clean.slice(5, 8)} ${clean.slice(8, 10)} ${clean.slice(10, 12)}`;
  }
  return clean;
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  try {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return timestamp;
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch (e) {
    return timestamp;
  }
}

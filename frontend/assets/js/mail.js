(() => {
  const REAL_FOLDERS = ["inbox", "sent", "drafts", "junk", "trash"];
  const VIRTUAL_FOLDERS = ["starred", "snoozed", "important", "scheduled", "all_mail", "purchases"];
  const ALL_FOLDERS = [...REAL_FOLDERS, ...VIRTUAL_FOLDERS];
  const INBOX_CATEGORIES = ["primary", "promotions", "social", "updates"];

  const NAV_ITEMS = [
    { key: "inbox", label: "Entrada", type: "folder" },
    { key: "starred", label: "Com estrela", type: "folder" },
    { key: "snoozed", label: "Adiados", type: "folder" },
    { key: "sent", label: "Enviados", type: "folder" },
    { key: "drafts", label: "Rascunhos", type: "folder" },
    { key: "purchases", label: "Compras", type: "folder" },
    { key: "important", label: "Importante", type: "folder" },
    { key: "scheduled", label: "Programados", type: "folder" },
    { key: "all_mail", label: "Todos os e-mails", type: "folder" },
    { key: "junk", label: "Spam", type: "folder" },
    { key: "trash", label: "Lixeira", type: "folder" },
    { key: "manage_subscriptions", label: "Gerenciar inscrições", type: "action" },
    { key: "manage_labels", label: "Gerenciar marcadores", type: "action" },
    { key: "create_label", label: "Criar novo marcador", type: "action" },
  ];

  const state = {
    authMode: null,
    context: null,
    company: null,
    user: null,
    domains: [],
    mailboxes: [],
    currentDomainId: null,
    currentMailboxId: null,
    currentFolder: "inbox",
    messages: [],
    selectedMessageId: null,
    selectedMessage: null,
    selectedMessageIds: [],
    search: "",
    searchTimer: null,
    autoRefreshTimer: null,
    isLoadingMessages: false,
    loadingDepth: 0,
    sidebarPrimeToken: 0,
    inboxInsightsToken: 0,
    inboxCategory: "primary",
    inboxCategoryCounts: {
      primary: 0,
      promotions: 0,
      social: 0,
      updates: 0,
    },
    inboxCategorySamples: {
      primary: "",
      promotions: "",
      social: "",
      updates: "",
    },
    folderSummaries: createEmptyFolderSummaries(),
    page: 1,
    pageSize: 50,
    total: 0,
    totalPages: 1,
    hasNext: false,
    hasPrev: false,
    startIndex: 0,
    endIndex: 0,
    density: localStorage.getItem("auremail-density") || "default",
  };

  function createEmptyFolderSummaries() {
    return Object.fromEntries(
      ALL_FOLDERS.map((folder) => [folder, { count: 0, preview: "Sem mensagens recentes" }])
    );
  }

  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value ?? "";
  }

  function setHtml(id, value) {
    const el = $(id);
    if (el) el.innerHTML = value ?? "";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function getQuerySelection() {
    const params = new URLSearchParams(window.location.search);
    return {
      dominioId: Number(params.get("dominio_id") || 0) || null,
      caixaId: Number(params.get("caixa_id") || 0) || null,
    };
  }

  function syncUrlSelection() {
    const url = new URL(window.location.href);

    if (state.currentDomainId) url.searchParams.set("dominio_id", String(state.currentDomainId));
    else url.searchParams.delete("dominio_id");

    if (state.currentMailboxId) url.searchParams.set("caixa_id", String(state.currentMailboxId));
    else url.searchParams.delete("caixa_id");

    window.history.replaceState({}, "", url.toString());
  }

  function currentDomain() {
    return state.domains.find((item) => Number(item.id) === Number(state.currentDomainId)) || null;
  }

  function currentMailbox() {
    return state.mailboxes.find((item) => Number(item.id) === Number(state.currentMailboxId)) || null;
  }

  function mailboxOptionsForCurrentDomain() {
    if (!state.currentDomainId) return [];
    return state.mailboxes.filter((item) => Number(item.dominio_id) === Number(state.currentDomainId));
  }

  function closeMobileSidebar() {
    $("mailSidebar")?.classList.remove("open");
    $("sidebarOverlay")?.classList.remove("active");
  }

  function shouldSyncFolder(folder) {
    return ["inbox", "junk"].includes(String(folder || "").toLowerCase());
  }

  function folderLabel(folder) {
    const map = {
      inbox: "Entrada",
      starred: "Com estrela",
      snoozed: "Adiados",
      sent: "Enviados",
      drafts: "Rascunhos",
      purchases: "Compras",
      important: "Importante",
      scheduled: "Programados",
      all_mail: "Todos os e-mails",
      junk: "Spam",
      trash: "Lixeira",
    };
    return map[folder] || "Mensagens";
  }

  function resetPagination() {
    state.page = 1;
    state.total = 0;
    state.totalPages = 1;
    state.hasNext = false;
    state.hasPrev = false;
    state.startIndex = 0;
    state.endIndex = 0;
  }

  function isComposeOpen() {
    return $("composeModal")?.classList.contains("active");
  }

  function hasActiveMessage() {
    return Boolean(state.selectedMessage && state.selectedMessageId);
  }

  function renderLayoutState() {
    const root = $("mailContent");
    if (!root) return;

    const opened = hasActiveMessage();
    root.classList.toggle("message-open", opened);
    root.classList.toggle("list-mode", !opened);
  }

  function truncateText(value, max = 38) {
    const text = String(value || "").trim();
    if (!text) return "";
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  function formatNewBadge(count) {
    const total = Number(count || 0);
    if (total <= 0) return "";
    return total === 1 ? "1 novo" : `${total} novos`;
  }

  function classifyInboxCategory(item) {
    if (item?.category && INBOX_CATEGORIES.includes(String(item.category))) {
      return String(item.category);
    }

    const text = [
      item?.subject || "",
      item?.preview || "",
      item?.from_email || "",
      item?.from_name || "",
      item?.body_text || "",
    ]
      .join(" ")
      .toLowerCase();

    if (/(facebook|instagram|linkedin|twitter|x\.com|tiktok|youtube|discord|telegram|amizade|seguidores|comentou|curtiu|marcou você|social)/.test(text)) {
      return "social";
    }

    if (/(promo|promoção|promocao|oferta|cupom|desconto|sale|novidades|frete|compre|pedido|checkout|amazon|mercado livre|mercadolivre|shopee|shein|magalu)/.test(text)) {
      return "promotions";
    }

    if (/(segurança|seguranca|security|alerta|login|acesso|senha|verificação|verificacao|código|codigo|invoice|fatura|configuração|configuracao|notificação|notificacao|update|apple|google)/.test(text)) {
      return "updates";
    }

    return "primary";
  }

  function getVisibleMessages() {
    return Array.isArray(state.messages) ? state.messages : [];
  }

  function categoryIcon(category) {
    const icons = {
      primary: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <path d="M19 3H5a2 2 0 0 0-2 2v14l4-2 4 2 4-2 4 2V5a2 2 0 0 0-2-2z"></path>
        </svg>
      `,
      promotions: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20.59 13.41 11 3H4v7l9.59 9.59a2 2 0 0 0 2.82 0l4.18-4.18a2 2 0 0 0 0-2.82Z"></path>
          <path d="M7 7h.01"></path>
        </svg>
      `,
      social: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path>
          <circle cx="9" cy="7" r="4"></circle>
          <path d="M22 21v-2a4 4 0 0 0-3-3.87"></path>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
        </svg>
      `,
      updates: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"></circle>
          <line x1="12" y1="10" x2="12" y2="16"></line>
          <line x1="12" y1="8" x2="12.01" y2="8"></line>
        </svg>
      `,
    };

    return icons[category] || "";
  }

  function categorySubtitle(category) {
    const fallback = {
      primary: "Mensagens pessoais e importantes",
      promotions: "Ofertas, compras e campanhas",
      social: "Redes sociais e interações",
      updates: "Alertas, recibos e notificações",
    };
    return state.inboxCategorySamples[category] || fallback[category] || "";
  }

  function navIcon(key) {
    const icons = {
      inbox: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline>
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
        </svg>
      `,
      starred: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <path d="M12 2.8l2.73 5.53 6.1.89-4.42 4.31 1.04 6.08L12 16.78 6.55 19.6l1.04-6.08L3.17 9.22l6.1-.89L12 2.8z"></path>
        </svg>
      `,
      snoozed: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"></circle>
          <polyline points="12 7 12 12 15 15"></polyline>
        </svg>
      `,
      sent: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      `,
      drafts: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="16" y1="13" x2="8" y2="13"></line>
          <line x1="16" y1="17" x2="8" y2="17"></line>
        </svg>
      `,
      purchases: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="9" cy="21" r="1"></circle>
          <circle cx="20" cy="21" r="1"></circle>
          <path d="M1 1h4l2.68 12.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path>
        </svg>
      `,
      important: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 3l2.7 5.47 6.03.88-4.36 4.25 1.03 6.01L12 16.77l-5.4 2.84 1.03-6.01L3.27 9.35l6.03-.88L12 3z"></path>
        </svg>
      `,
      scheduled: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 8V21H3V8"></path>
          <path d="M1 3H23V8H1z"></path>
          <path d="M10 12h4"></path>
          <path d="M12 10v4"></path>
        </svg>
      `,
      all_mail: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 4h16v16H4z"></path>
          <path d="M4 8l8 5 8-5"></path>
        </svg>
      `,
      junk: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9"></circle>
          <line x1="8" y1="8" x2="16" y2="16"></line>
        </svg>
      `,
      trash: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      `,
      manage_subscriptions: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 12h-4l-3 9L9 3l-3 9H2"></path>
        </svg>
      `,
      manage_labels: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20.59 13.41 11 3H4v7l9.59 9.59a2 2 0 0 0 2.82 0l4.18-4.18a2 2 0 0 0 0-2.82Z"></path>
          <path d="M7 7h.01"></path>
        </svg>
      `,
      create_label: `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 12h-8"></path>
          <path d="M16 8v8"></path>
          <path d="M8.59 13.41 18 4H11L2 13v7h7l3.59-3.59"></path>
        </svg>
      `,
    };

    return icons[key] || "";
  }

  function applyDensityClass() {
    document.body.classList.remove("density-default", "density-compact", "density-comfortable");
    document.body.classList.add(`density-${state.density}`);
    localStorage.setItem("auremail-density", state.density);
  }

  let feedbackTimeout = null;

  function setFeedback(message, type = "") {
    const box = $("mailFeedback");
    if (!box) return;

    clearTimeout(feedbackTimeout);

    if (!message || !String(message).trim()) {
      box.textContent = "";
      box.className = "mail-feedback";
      return;
    }

    box.textContent = message;
    box.className = `mail-feedback show ${type}`.trim();

    feedbackTimeout = setTimeout(() => {
      box.className = "mail-feedback";
      box.textContent = "";
    }, 3500);
  }

  function clearFeedback() {
    setFeedback("");
  }

  function showLoading(message = "Carregando...") {
    const overlay = $("loadingOverlay");
    const text = $("loadingText");

    state.loadingDepth += 1;

    if (text) text.textContent = message;
    if (overlay) {
      overlay.classList.add("show");
      overlay.setAttribute("aria-hidden", "false");
    }
  }

  function hideLoading() {
    const overlay = $("loadingOverlay");
    state.loadingDepth = Math.max(0, state.loadingDepth - 1);

    if (state.loadingDepth > 0) return;

    if (overlay) {
      overlay.classList.remove("show");
      overlay.setAttribute("aria-hidden", "true");
    }
  }

  function extractErrorMessage(response, payload, rawText) {
    if (payload?.detail) {
      if (typeof payload.detail === "string") return payload.detail;
      if (Array.isArray(payload.detail)) {
        return payload.detail.map((item) => item?.msg || JSON.stringify(item)).join(" | ");
      }
    }

    if (payload?.message) return payload.message;

    const text = String(rawText || "").trim();
    if (!text) return `Erro ${response.status}`;
    if (text.includes("Service is not reachable")) return "O serviço não está alcançável.";
    if (text.startsWith("<!DOCTYPE html") || text.startsWith("<html")) return `Erro ${response.status} ao falar com o servidor.`;

    return text.slice(0, 400);
  }

  async function parseApiResponse(response) {
    const rawText = await response.text();
    let payload = null;

    try {
      payload = rawText ? JSON.parse(rawText) : {};
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const error = new Error(extractErrorMessage(response, payload, rawText));
      error.status = response.status;
      error.payload = payload;
      error.rawText = rawText;
      throw error;
    }

    return payload || {};
  }

  async function api(url, options = {}) {
    const config = {
      method: options.method || "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
      ...(options.body ? { body: JSON.stringify(options.body) } : {}),
    };

    const response = await fetch(url, config);

    if (response.status === 401) {
      window.location.href = state.authMode === "platform" ? "/login" : "/webmail-login";
      throw new Error("Sessão expirada.");
    }

    return parseApiResponse(response);
  }

  async function fetchContext() {
    const initial = getQuerySelection();
    const params = new URLSearchParams();

    if (initial.dominioId) params.set("dominio_id", String(initial.dominioId));
    if (initial.caixaId) params.set("caixa_id", String(initial.caixaId));

    const suffix = params.toString() ? `?${params.toString()}` : "";
    const response = await fetch(`/api/webmail/context${suffix}`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });

    if (response.status === 401) {
      window.location.href = "/webmail-login";
      throw new Error("Acesso ao webmail não autorizado.");
    }

    return parseApiResponse(response);
  }

  function applyMailboxOnlyUi() {
    const domainSelect = $("domainSelect");
    const mailboxSelect = $("mailboxSelect");
    const contextRow = document.querySelector(".mail-context-row");

    if (state.authMode === "mailbox") {
      if (domainSelect) domainSelect.disabled = true;
      if (mailboxSelect) mailboxSelect.disabled = true;
      if (contextRow) contextRow.style.display = "none";
      return;
    }

    if (contextRow) contextRow.style.display = "flex";
  }

  function ensureSelectedContext() {
    if (!state.domains.length) {
      state.currentDomainId = null;
      state.currentMailboxId = null;
      return;
    }

    if (!state.domains.some((item) => Number(item.id) === Number(state.currentDomainId))) {
      state.currentDomainId = Number(state.domains[0]?.id) || null;
    }

    const mailboxItems = mailboxOptionsForCurrentDomain();
    if (!mailboxItems.some((item) => Number(item.id) === Number(state.currentMailboxId))) {
      const firstActive = mailboxItems.find((item) => item.is_active) || mailboxItems[0] || null;
      state.currentMailboxId = firstActive?.id || null;
    }
  }

  function renderDomainOptions() {
    const select = $("domainSelect");
    if (!select) return;

    if (!state.domains.length) {
      select.innerHTML = `<option value="">Nenhum domínio cadastrado</option>`;
      select.disabled = true;
      return;
    }

    select.disabled = state.authMode === "mailbox";
    select.innerHTML = state.domains
      .map((domain) => {
        const selected = Number(domain.id) === Number(state.currentDomainId) ? "selected" : "";
        const label = domain.is_primary ? `${domain.name} (principal)` : domain.name;
        return `<option value="${domain.id}" ${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

  function renderMailboxOptions() {
    const select = $("mailboxSelect");
    if (!select) return;

    const items = mailboxOptionsForCurrentDomain();

    if (!items.length) {
      select.innerHTML = `<option value="">Nenhuma caixa nesse domínio</option>`;
      select.disabled = true;
      return;
    }

    if (!items.some((item) => Number(item.id) === Number(state.currentMailboxId))) {
      const activeFirst = items.find((item) => item.is_active) || items[0] || null;
      state.currentMailboxId = activeFirst?.id || null;
    }

    select.disabled = state.authMode === "mailbox";
    select.innerHTML = items
      .map((mailbox) => {
        const selected = Number(mailbox.id) === Number(state.currentMailboxId) ? "selected" : "";
        const status = mailbox.is_active ? "" : " (inativa)";
        return `<option value="${mailbox.id}" ${selected}>${escapeHtml(mailbox.email + status)}</option>`;
      })
      .join("");
  }

  function renderCurrentContext() {
    const info = $("currentContextInfo");
    if (!info) return;

    const company = state.company || {};
    const mailbox = currentMailbox();

    if (!state.domains.length || !mailbox) {
      info.textContent = company.name || "AureMail";
      return;
    }

    if (state.authMode === "mailbox") {
      info.textContent = `Caixa: ${mailbox.email}`;
      return;
    }

    info.textContent = company.name || "AureMail";
  }

  function updateComposeFrom() {
    const fromInput = $("from");
    const mailbox = currentMailbox();
    if (fromInput) fromInput.value = mailbox?.email || "";
  }

  function resetFolderSummaries() {
    state.folderSummaries = createEmptyFolderSummaries();
    renderFolderNav();
  }

  async function loadContext() {
    const data = await fetchContext();

    state.context = data;
    state.authMode = data?.auth_mode || "mailbox";
    state.company = data?.company || null;
    state.user = data?.user || null;
    state.domains = Array.isArray(data?.domains) ? data.domains : [];
    state.mailboxes = Array.isArray(data?.mailboxes) ? data.mailboxes : [];
    state.currentDomainId = data?.selected_domain_id || null;
    state.currentMailboxId = data?.selected_mailbox_id || null;

    ensureSelectedContext();
    resetFolderSummaries();
    renderDomainOptions();
    renderMailboxOptions();
    renderCurrentContext();
    updateComposeFrom();
    applyMailboxOnlyUi();
    syncUrlSelection();
  }

  function buildFolderPreview(folder, item) {
    if (!item) return "Sem mensagens recentes";

    const person =
      folder === "sent" || folder === "drafts" || folder === "scheduled"
        ? item.to_email || "Sem destinatário"
        : item.from_name || item.from_email || "Sem remetente";

    const mainText = item.subject || item.preview || "(sem assunto)";
    return `${person} · ${mainText}`;
  }

  function renderSidebarNav() {
    const nav = $("mailNav");
    if (!nav) return;

    nav.innerHTML = NAV_ITEMS.map((item) => {
      if (item.type === "action") {
        return `
          <button type="button" class="mail-nav__item mail-nav__item--action" data-action="${item.key}">
            <div class="mail-nav__top">
              <div class="nav-label">
                ${navIcon(item.key)}
                <span>${escapeHtml(item.label)}</span>
              </div>
            </div>
          </button>
        `;
      }

      const summary = state.folderSummaries[item.key] || { count: 0, preview: "Sem mensagens recentes" };
      const active = item.key === state.currentFolder ? "active" : "";
      const tooltip = `${item.label} — ${summary.preview || "Sem mensagens recentes"}`;

      return `
        <a
          href="#"
          class="mail-nav__item ${active}"
          data-folder="${item.key}"
          title="${escapeHtml(tooltip)}"
          aria-label="${escapeHtml(tooltip)}"
        >
          <div class="mail-nav__top">
            <div class="nav-label">
              ${navIcon(item.key)}
              <span>${escapeHtml(item.label)}</span>
            </div>
            <strong class="nav-count">${Number(summary.count || 0)}</strong>
          </div>
        </a>
      `;
    }).join("");
  }

  function renderFolderNav() {
    renderSidebarNav();
  }

  async function fetchInboxCategoryInsights() {
    const mailbox = currentMailbox();
    if (!mailbox || state.currentFolder !== "inbox" || state.search) {
      return;
    }

    const token = Date.now();
    state.inboxInsightsToken = token;

    const categories = [
      { key: "primary" },
      { key: "promotions" },
      { key: "social" },
      { key: "updates" },
    ];

    const results = await Promise.allSettled(
      categories.map(async ({ key }) => {
        const params = new URLSearchParams({
          folder: "inbox",
          category: key,
          sync: "false",
          page: "1",
          page_size: "1",
        });

        const data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages?${params.toString()}`);
        return {
          key,
          total: Number(data?.total || 0),
          sample: buildFolderPreview("inbox", (data?.items || [])[0] || null),
        };
      })
    );

    if (state.inboxInsightsToken !== token) return;

    const nextCounts = {
      primary: 0,
      promotions: 0,
      social: 0,
      updates: 0,
    };

    const nextSamples = {
      primary: "",
      promotions: "",
      social: "",
      updates: "",
    };

    results.forEach((result) => {
      if (result.status !== "fulfilled") return;
      nextCounts[result.value.key] = result.value.total;
      nextSamples[result.value.key] = result.value.sample;
    });

    state.inboxCategoryCounts = nextCounts;
    state.inboxCategorySamples = nextSamples;
    renderCategoryTabs();
  }

  function renderCategoryTabs() {
    const box = $("mailCategoryTabs");
    if (!box) return;

    if (state.currentFolder !== "inbox" || hasActiveMessage()) {
      box.style.display = "none";
      box.innerHTML = "";
      return;
    }

    const categories = [
      { key: "primary", label: "Principal", badgeClass: "badge-primary" },
      { key: "promotions", label: "Promoções", badgeClass: "badge-promotions" },
      { key: "social", label: "Social", badgeClass: "badge-social" },
      { key: "updates", label: "Atualizações", badgeClass: "badge-updates" },
    ];

    box.style.display = "grid";
    box.innerHTML = categories
      .map((tab) => {
        const active = state.inboxCategory === tab.key ? "active" : "";
        const count = Number(state.inboxCategoryCounts[tab.key] || 0);
        const badgeText = tab.key === "primary" ? "" : formatNewBadge(count);

        return `
          <button type="button" class="mail-category-tab ${active}" data-category="${tab.key}">
            <span class="mail-category-tab__icon">${categoryIcon(tab.key)}</span>

            <span class="mail-category-tab__content">
              <span class="mail-category-tab__line">
                <span class="mail-category-tab__title">${escapeHtml(tab.label)}</span>
                ${badgeText ? `<span class="mail-category-tab__badge ${tab.badgeClass}">${escapeHtml(badgeText)}</span>` : ""}
              </span>

              <span class="mail-category-tab__subtitle">${escapeHtml(categorySubtitle(tab.key))}</span>
            </span>
          </button>
        `;
      })
      .join("");
  }

  function applyFolderCounts(counts = {}) {
    ALL_FOLDERS.forEach((folder) => {
      const safeCount = Number(counts?.[folder] ?? state.folderSummaries[folder]?.count ?? 0);
      state.folderSummaries[folder] = {
        ...(state.folderSummaries[folder] || {}),
        count: Number.isFinite(safeCount) ? safeCount : 0,
      };
    });

    renderFolderNav();
  }

  function updateFolderSummaryFromItems(folder, items) {
    const list = Array.isArray(items) ? items : [];
    const firstItem = list[0] || null;

    state.folderSummaries[folder] = {
      ...(state.folderSummaries[folder] || {}),
      preview: buildFolderPreview(folder, firstItem),
    };

    renderFolderNav();
  }

  async function primeSidebarSummaries() {
    const mailbox = currentMailbox();
    if (!mailbox || state.search) return;

    const token = Date.now();
    state.sidebarPrimeToken = token;

    const tasks = ALL_FOLDERS.map(async (folder) => {
      try {
        const params = new URLSearchParams({
          folder,
          sync: "false",
          page: "1",
          page_size: "1",
        });

        const data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages?${params.toString()}`);
        if (state.sidebarPrimeToken !== token) return;

        applyFolderCounts(data?.folder_counts || {});
        updateFolderSummaryFromItems(folder, data?.items || []);
      } catch (error) {
        console.error(`Erro ao carregar resumo da pasta ${folder}:`, error);
      }
    });

    await Promise.allSettled(tasks);
  }

  function getSelectedMessageIds() {
    return Array.from(
      new Set(
        (state.selectedMessageIds || [])
          .map((id) => Number(id))
          .filter((id) => Number.isFinite(id) && id > 0)
      )
    );
  }

  function isMessageSelected(messageId) {
    return getSelectedMessageIds().includes(Number(messageId));
  }

  function setSelectedMessageIds(ids) {
    state.selectedMessageIds = Array.from(
      new Set(
        (ids || [])
          .map((id) => Number(id))
          .filter((id) => Number.isFinite(id) && id > 0)
      )
    );
  }

  function clearSelections() {
    setSelectedMessageIds([]);
  }

  function toggleMessageSelection(messageId, forceValue = null) {
    const id = Number(messageId);
    const selected = getSelectedMessageIds();
    const has = selected.includes(id);
    const shouldSelect = forceValue === null ? !has : Boolean(forceValue);

    if (shouldSelect && !has) selected.push(id);
    if (!shouldSelect && has) selected.splice(selected.indexOf(id), 1);

    setSelectedMessageIds(selected);
    renderMessageList();
    updateActionButtons();
  }

  function setAllSelections(forceValue) {
    const visibleIds = getVisibleMessages()
      .map((item) => Number(item.id))
      .filter((id) => id > 0);

    setSelectedMessageIds(forceValue ? visibleIds : []);
    renderMessageList();
    updateActionButtons();
  }

  function syncSelectionState() {
    const visibleIds = new Set(
      getVisibleMessages()
        .map((item) => Number(item.id))
        .filter((id) => id > 0)
    );

    setSelectedMessageIds(getSelectedMessageIds().filter((id) => visibleIds.has(id)));

    if (state.selectedMessageId && !visibleIds.has(Number(state.selectedMessageId))) {
      state.selectedMessageId = null;
      state.selectedMessage = null;
    }
  }

  function canReplyOrForward() {
    return hasActiveMessage() && getSelectedMessageIds().length === 0;
  }

  function formatDate(value) {
    if (!value) return "Agora";

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Data inválida";

    const now = new Date();
    if (date.toDateString() === now.toDateString()) {
      return new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(date);
    }

    return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" }).format(date);
  }

  function formatDateTime(value) {
    if (!value) return "Agora";

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Data inválida";

    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date);
  }

  function toDatetimeLocalValue(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";

    const pad = (num) => String(num).padStart(2, "0");
    const year = date.getFullYear();
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  }

  function messageBadges(item) {
    const badges = [];

    if (item.is_starred) badges.push(`<span class="mail-badge mail-badge--starred">★ Estrela</span>`);
    if (item.is_important) badges.push(`<span class="mail-badge mail-badge--important">Importante</span>`);
    if (item.snoozed_until) badges.push(`<span class="mail-badge">Adiado</span>`);
    if (item.schedule_status === "scheduled" && item.scheduled_for) badges.push(`<span class="mail-badge">Programado</span>`);

    return badges.join("");
  }

  function renderPageUi() {
    const statusEl = $("mailPageStatus");
    const prevBtn = $("prevPageBtn");
    const nextBtn = $("nextPageBtn");

    const start = Number(state.startIndex || 0);
    const end = Number(state.endIndex || 0);
    const total = Number(state.total || 0);

    if (statusEl) {
      statusEl.textContent = total > 0 ? `${start}-${end} de ${total}` : "0 de 0";
    }

    if (prevBtn) prevBtn.disabled = !state.hasPrev || state.isLoadingMessages;
    if (nextBtn) nextBtn.disabled = !state.hasNext || state.isLoadingMessages;
  }

  function renderNoDomainState() {
    clearSelections();
    resetFolderSummaries();
    resetPagination();
    setText("mailResultsCount", "");
    setHtml("mailList", `<div class="mail-empty-state"><span>Sem domínios.</span></div>`);
    setHtml("mailView", `<div class="mail-empty-state mail-empty-state--plain"><span>Nenhum domínio disponível.</span></div>`);
    renderLayoutState();
    renderCategoryTabs();
    renderPageUi();
    updateActionButtons();
  }

  function renderNoMailboxState() {
    clearSelections();
    resetFolderSummaries();
    resetPagination();
    setText("mailResultsCount", "");
    setHtml("mailList", `<div class="mail-empty-state"><span>Nenhuma caixa.</span></div>`);
    setHtml("mailView", `<div class="mail-empty-state mail-empty-state--plain"><span>Nenhuma caixa.</span></div>`);
    renderLayoutState();
    renderCategoryTabs();
    renderPageUi();
    updateActionButtons();
  }

  function renderMessageList() {
    const list = $("mailList");
    if (!list) return;

    const items = getVisibleMessages();
    const total = Number(state.total || items.length || 0);

    setText("mailResultsCount", `${total} conversas`);
    renderPageUi();

    if (!items.length) {
      let emptyText = `Sua pasta ${folderLabel(state.currentFolder).toLowerCase()} está vazia.`;

      if (state.currentFolder === "junk") emptyText = "Nenhuma mensagem em spam.";
      if (state.search) emptyText = "Nenhuma mensagem encontrada para a sua pesquisa.";
      if (state.currentFolder === "inbox") {
        const catLabel = {
          primary: "Principal",
          promotions: "Promoções",
          social: "Social",
          updates: "Atualizações",
        };
        emptyText = `Nenhuma mensagem na aba ${catLabel[state.inboxCategory] || "Principal"}.`;
      }

      list.innerHTML = `<div class="mail-empty-state"><span>${escapeHtml(emptyText)}</span></div>`;
      renderCategoryTabs();
      updateActionButtons();
      return;
    }

    list.innerHTML = items
      .map((item) => {
        const active = Number(item.id) === Number(state.selectedMessageId);
        const selected = isMessageSelected(item.id);
        const unread = !item.is_read;

        const person =
          item.direction === "outbound"
            ? item.to_email || "Destinatário"
            : item.from_name || item.from_email || "Remetente";

        const dateValue = item.scheduled_for || item.sent_at || item.created_at;

        return `
          <div class="mail-item ${active ? "active" : ""} ${selected ? "selected" : ""} ${unread ? "unread" : ""}" data-message-id="${item.id}">
            <div class="mail-item__check">
              <input
                type="checkbox"
                class="mail-item__checkbox"
                data-message-id="${item.id}"
                ${selected ? "checked" : ""}
                aria-label="Selecionar mensagem"
              />
            </div>

            <button
              type="button"
              class="mail-item__star ${item.is_starred ? "is-active" : ""}"
              data-star-message-id="${item.id}"
              aria-label="Marcar com estrela"
              title="Marcar com estrela"
            >
              ★
            </button>

            <div class="mail-item__from">${escapeHtml(person)}</div>

            <div class="mail-item__summary">
              <span class="mail-item__subject">${escapeHtml(item.subject || "(sem assunto)")}</span>
              <span class="mail-item__separator">-</span>
              <span class="mail-item__preview">${escapeHtml(item.preview || "")}</span>
            </div>

            <div class="mail-item__date">${escapeHtml(formatDate(dateValue))}</div>
          </div>
        `;
      })
      .join("");

    renderCategoryTabs();
    updateActionButtons();
  }

  function renderEmptyMessageView() {
    setHtml(
      "mailView",
      `
        <div class="mail-empty-state mail-empty-state--plain">
          <span>Selecione uma conversa</span>
        </div>
      `
    );
    renderLayoutState();
    renderCategoryTabs();
    updateActionButtons();
  }

  function renderMessageView() {
    const view = $("mailView");
    const msg = state.selectedMessage;

    if (!view || !msg) {
      renderEmptyMessageView();
      return;
    }

    const metaDate = msg.scheduled_for || msg.sent_at || msg.created_at;
    const scheduledInfo =
      msg.schedule_status === "scheduled" && msg.scheduled_for
        ? `<div class="mail-view__extra">Programado para: ${escapeHtml(formatDateTime(msg.scheduled_for))}</div>`
        : "";

    const snoozedInfo = msg.snoozed_until
      ? `<div class="mail-view__extra">Adiado até: ${escapeHtml(formatDateTime(msg.snoozed_until))}</div>`
      : "";

    const senderInitial = (msg.from_name || msg.from_email || "?").trim().charAt(0).toUpperCase();

    view.innerHTML = `
      <div class="mail-detail">
        <div class="mail-detail__subject-row">
          <h2>${escapeHtml(msg.subject || "(sem assunto)")}</h2>
          <div class="mail-detail__badges">${messageBadges(msg)}</div>
        </div>

        <div class="mail-detail__meta">
          <div class="mail-detail__avatar">${escapeHtml(senderInitial)}</div>

          <div class="mail-detail__meta-main">
            <div class="mail-detail__sender-line">
              <strong>${escapeHtml(msg.from_name || msg.from_email || "-")}</strong>
              <span>&lt;${escapeHtml(msg.from_email || "-")}&gt;</span>
            </div>

            <div class="mail-detail__to-line">
              para ${escapeHtml(msg.to_email || "-")}
            </div>

            ${scheduledInfo}
            ${snoozedInfo}
          </div>

          <div class="mail-detail__time">
            ${escapeHtml(formatDateTime(metaDate))}
          </div>
        </div>

        <div class="mail-detail__body">
          ${escapeHtml(msg.body_text || "Esta mensagem não possui conteúdo de texto.")}
        </div>

        <div class="mail-detail__footer-actions">
          <button class="reply-pill" type="button" id="replyInlineBtn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="9 17 4 12 9 7"></polyline>
              <path d="M20 18v-2a4 4 0 0 0-4-4H4"></path>
            </svg>
            Reply
          </button>

          <button class="reply-pill" type="button" id="forwardInlineBtn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="15 17 20 12 15 7"></polyline>
              <path d="M4 18v-2a4 4 0 0 1 4-4h12"></path>
            </svg>
            Forward
          </button>
        </div>
      </div>
    `;

    $("replyInlineBtn")?.addEventListener("click", prefillReply);
    $("forwardInlineBtn")?.addEventListener("click", prefillForward);

    renderLayoutState();
    renderCategoryTabs();
    updateActionButtons();
  }

  async function forceMailboxSync(mailboxId) {
    return api(`/api/webmail/mailboxes/${mailboxId}/sync`, { method: "POST" });
  }

  async function loadMessages(options = {}) {
    if (state.isLoadingMessages) return;

    const {
      silent = false,
      primeSidebar = false,
      loadingText = "Carregando mensagens...",
      page = state.page,
    } = options;

    if (!state.domains.length) {
      renderNoDomainState();
      return;
    }

    const mailbox = currentMailbox();
    if (!mailbox) {
      renderNoMailboxState();
      return;
    }

    state.isLoadingMessages = true;

    if (!silent) {
      clearFeedback();
      showLoading(loadingText);
    }

    try {
      const params = new URLSearchParams({
        folder: state.currentFolder,
        sync: shouldSyncFolder(state.currentFolder) ? "true" : "false",
        page: String(page || 1),
        page_size: String(state.pageSize || 50),
      });

      if (state.search) params.set("q", state.search);
      if (state.currentFolder === "inbox") params.set("category", state.inboxCategory);

      let data;

      try {
        data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages?${params.toString()}`);
      } catch (error) {
        const isSyncFailure = shouldSyncFolder(state.currentFolder) && [500, 502].includes(Number(error?.status));

        if (!isSyncFailure) throw error;

        if (!silent) {
          setFeedback(`${error.message || "Falha na sincronização."} Exibindo salvas.`, "error");
        }

        params.set("sync", "false");
        data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages?${params.toString()}`);
      }

      if (data?.sync_error && !silent) {
        setFeedback(data.sync_error, "error");
      }

      state.messages = Array.isArray(data?.items) ? data.items : [];
      state.page = Number(data?.page || page || 1);
      state.pageSize = Number(data?.page_size || state.pageSize || 50);
      state.total = Number(data?.total || state.messages.length || 0);
      state.totalPages = Number(data?.total_pages || 1);
      state.hasNext = Boolean(data?.has_next);
      state.hasPrev = Boolean(data?.has_prev);
      state.startIndex = Number(data?.start_index || 0);
      state.endIndex = Number(data?.end_index || 0);

      syncSelectionState();

      applyFolderCounts(data?.folder_counts || {});
      if (!state.search) updateFolderSummaryFromItems(state.currentFolder, state.messages);

      renderMessageList();

      if (state.selectedMessageId) {
        const exists = getVisibleMessages().some((item) => Number(item.id) === Number(state.selectedMessageId));
        if (!exists) {
          state.selectedMessageId = null;
          state.selectedMessage = null;
        }
      }

      if (state.selectedMessageId) {
        await loadMessageDetail(state.selectedMessageId, false);
      } else {
        renderEmptyMessageView();
      }

      updateActionButtons();

      const backgroundTasks = [];
      if (primeSidebar && !state.search) {
        backgroundTasks.push(primeSidebarSummaries());
      }
      if (state.currentFolder === "inbox" && !state.search) {
        backgroundTasks.push(fetchInboxCategoryInsights());
      }

      if (backgroundTasks.length) {
        Promise.allSettled(backgroundTasks).catch(() => {});
      }
    } finally {
      state.isLoadingMessages = false;
      if (!silent) hideLoading();
      renderPageUi();
    }
  }

  async function loadMessageDetail(messageId, markAsRead = true) {
    const mailbox = currentMailbox();
    if (!mailbox || !messageId) {
      renderEmptyMessageView();
      return;
    }

    const data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${messageId}`);
    state.selectedMessageId = Number(messageId);
    state.selectedMessage = data?.item || null;
    renderMessageView();

    if (markAsRead && state.selectedMessage && !state.selectedMessage.is_read) {
      try {
        await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${messageId}/read`, { method: "POST" });

        state.selectedMessage.is_read = true;
        state.messages = state.messages.map((item) =>
          Number(item.id) === Number(messageId)
            ? { ...item, is_read: true }
            : item
        );

        renderMessageList();
        updateActionButtons();
      } catch (_) {}
    }
  }

  function openCompose() {
    if (!currentMailbox()) {
      setFeedback("Selecione uma caixa real.", "error");
      return;
    }

    $("composeOverlay")?.classList.add("active");
    $("composeModal")?.classList.add("active");
    $("composeModal")?.setAttribute("aria-hidden", "false");
    updateComposeFrom();
  }

  function closeCompose() {
    $("composeOverlay")?.classList.remove("active");
    $("composeModal")?.classList.remove("active");
    $("composeModal")?.setAttribute("aria-hidden", "true");
  }

  function resetComposeForm() {
    $("composeForm")?.reset();
    updateComposeFrom();
    setScheduledPanel(false);
    if ($("scheduledFor")) $("scheduledFor").value = "";
  }

  function setScheduledPanel(open) {
    const panel = $("composeSchedulePanel");
    if (!panel) return;
    panel.style.display = open ? "flex" : "none";
  }

  async function sendCompose(mode = "send") {
    const mailbox = currentMailbox();

    if (!mailbox) {
      setFeedback("Nenhuma caixa selecionada.", "error");
      return;
    }

    const to = $("to")?.value?.trim();
    const subject = $("subject")?.value?.trim();
    const body = $("message")?.value?.trim();
    const scheduledFor = $("scheduledFor")?.value?.trim();

    if (!to) {
      setFeedback("Informe o destinatário.", "error");
      return;
    }

    if (mode === "scheduled" && !scheduledFor) {
      setFeedback("Informe a data e hora do agendamento.", "error");
      return;
    }

    const loadingMap = {
      send: "Enviando mensagem...",
      draft: "Salvando rascunho...",
      scheduled: "Programando envio...",
    };

    showLoading(loadingMap[mode] || "Processando...");

    try {
      const result = await api(`/api/webmail/mailboxes/${mailbox.id}/compose`, {
        method: "POST",
        body: {
          to,
          subject: subject || null,
          body: body || null,
          save_as_draft: mode === "draft",
          save_as_scheduled: mode === "scheduled",
          scheduled_for: mode === "scheduled" ? new Date(scheduledFor).toISOString() : null,
        },
      });

      closeCompose();
      resetComposeForm();

      clearSelections();
      resetPagination();

      if (mode === "draft") state.currentFolder = "drafts";
      else if (mode === "scheduled") state.currentFolder = "scheduled";
      else state.currentFolder = "sent";

      state.selectedMessageId = result?.item?.id || null;
      state.selectedMessage = null;

      await loadMessages({ silent: true, primeSidebar: true, page: 1 });
      setFeedback(result?.message || "Mensagem processada.", "success");
    } finally {
      hideLoading();
    }
  }

  async function moveMessagesToFolder(targetFolder, successMessage) {
    const mailbox = currentMailbox();
    if (!mailbox) {
      setFeedback("Nenhuma caixa selecionada.", "error");
      return;
    }

    const selectedIds = getSelectedMessageIds();

    if (selectedIds.length === 0 && !state.selectedMessageId) {
      setFeedback("Selecione uma ou mais mensagens.", "error");
      return;
    }

    showLoading("Movendo mensagens...");

    try {
      if (selectedIds.length > 0) {
        await api(`/api/webmail/mailboxes/${mailbox.id}/messages/bulk-move`, {
          method: "POST",
          body: {
            message_ids: selectedIds,
            target_folder: targetFolder,
          },
        });
      } else if (state.selectedMessageId) {
        await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${state.selectedMessageId}/move`, {
          method: "POST",
          body: { target_folder: targetFolder },
        });
      }

      if (selectedIds.includes(Number(state.selectedMessageId))) {
        state.selectedMessageId = null;
        state.selectedMessage = null;
      }

      clearSelections();
      await loadMessages({ silent: true, primeSidebar: true, page: 1 });
      setFeedback(successMessage, "success");
    } finally {
      hideLoading();
    }
  }

  async function deleteMessagesForever(successMessage) {
    const mailbox = currentMailbox();
    if (!mailbox) {
      setFeedback("Nenhuma caixa selecionada.", "error");
      return;
    }

    const selectedIds = getSelectedMessageIds();

    if (selectedIds.length === 0 && !state.selectedMessageId) {
      setFeedback("Selecione uma ou mais mensagens.", "error");
      return;
    }

    showLoading("Apagando mensagens...");

    try {
      if (selectedIds.length > 0) {
        await api(`/api/webmail/mailboxes/${mailbox.id}/messages/bulk-delete`, {
          method: "POST",
          body: { message_ids: selectedIds },
        });
      } else if (state.selectedMessageId) {
        await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${state.selectedMessageId}`, {
          method: "DELETE",
        });
      }

      state.selectedMessageId = null;
      state.selectedMessage = null;
      clearSelections();
      await loadMessages({ silent: true, primeSidebar: true, page: 1 });
      setFeedback(successMessage, "success");
    } finally {
      hideLoading();
    }
  }

  async function runPrimaryDeleteAction() {
    if (state.currentFolder === "trash") {
      await deleteMessagesForever("Mensagem(ns) apagada(s) permanentemente.");
      return;
    }

    await moveMessagesToFolder("trash", "Mensagem(ns) movida(s) para a lixeira.");
  }

  async function moveSelectedToJunk() {
    await moveMessagesToFolder("junk", "Mensagem(ns) movida(s) para spam.");
  }

  async function moveSelectedToInbox() {
    await moveMessagesToFolder("inbox", "Mensagem(ns) movida(s) para entrada.");
  }

  async function toggleMessageStarById(messageId) {
    const mailbox = currentMailbox();
    if (!mailbox || !messageId) return;

    const current = (state.messages || []).find((item) => Number(item.id) === Number(messageId));
    if (!current) return;

    const nextValue = !Boolean(current.is_starred);

    const result = await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${messageId}/star`, {
      method: "POST",
      body: { value: nextValue },
    });

    state.messages = state.messages.map((item) =>
      Number(item.id) === Number(messageId)
        ? { ...item, is_starred: nextValue }
        : item
    );

    if (state.selectedMessage && Number(state.selectedMessage.id) === Number(messageId)) {
      state.selectedMessage = {
        ...state.selectedMessage,
        is_starred: nextValue,
      };
      renderMessageView();
    }

    applyFolderCounts(result?.folder_counts || {});
    renderMessageList();
  }

  async function toggleActiveMessageStar() {
    const mailbox = currentMailbox();
    const msg = state.selectedMessage;
    if (!mailbox || !msg || getSelectedMessageIds().length > 0) {
      setFeedback("Abra apenas uma mensagem para alterar a estrela.", "error");
      return;
    }

    showLoading("Atualizando estrela...");

    try {
      const nextValue = !Boolean(msg.is_starred);
      const result = await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${msg.id}/star`, {
        method: "POST",
        body: { value: nextValue },
      });

      state.selectedMessage = result?.item || { ...msg, is_starred: nextValue };
      state.messages = state.messages.map((item) =>
        Number(item.id) === Number(msg.id)
          ? { ...item, is_starred: nextValue }
          : item
      );

      renderMessageList();
      renderMessageView();
      applyFolderCounts(result?.folder_counts || {});
      setFeedback(result?.message || "Estrela atualizada.", "success");
    } finally {
      hideLoading();
    }
  }

  async function toggleActiveMessageImportant() {
    const mailbox = currentMailbox();
    const msg = state.selectedMessage;
    if (!mailbox || !msg || getSelectedMessageIds().length > 0) {
      setFeedback("Abra apenas uma mensagem para alterar o importante.", "error");
      return;
    }

    showLoading("Atualizando importância...");

    try {
      const nextValue = !Boolean(msg.is_important);
      const result = await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${msg.id}/important`, {
        method: "POST",
        body: { value: nextValue },
      });

      state.selectedMessage = result?.item || { ...msg, is_important: nextValue };
      state.messages = state.messages.map((item) =>
        Number(item.id) === Number(msg.id)
          ? { ...item, is_important: nextValue }
          : item
      );

      renderMessageList();
      renderMessageView();
      applyFolderCounts(result?.folder_counts || {});
      setFeedback(result?.message || "Importância atualizada.", "success");
    } finally {
      hideLoading();
    }
  }

  async function snoozeActiveMessage(remove = false) {
    const mailbox = currentMailbox();
    const msg = state.selectedMessage;
    if (!mailbox || !msg || getSelectedMessageIds().length > 0) {
      setFeedback("Abra apenas uma mensagem para adiar.", "error");
      return;
    }

    let snoozedUntil = null;

    if (!remove) {
      const currentSuggestion = (() => {
        const date = new Date();
        date.setHours(date.getHours() + 2);
        return toDatetimeLocalValue(date.toISOString());
      })();

      const typed = window.prompt(
        "Digite a data e hora do adiamento no formato AAAA-MM-DDTHH:MM",
        currentSuggestion
      );

      if (!typed) return;

      const parsed = new Date(typed);
      if (Number.isNaN(parsed.getTime())) {
        setFeedback("Data de adiamento inválida.", "error");
        return;
      }

      snoozedUntil = parsed.toISOString();
    }

    showLoading(remove ? "Removendo adiamento..." : "Adiando mensagem...");

    try {
      const result = await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${msg.id}/snooze`, {
        method: "POST",
        body: { snoozed_until: remove ? null : snoozedUntil },
      });

      state.selectedMessage = result?.item || { ...msg, snoozed_until: remove ? null : snoozedUntil };
      state.messages = state.messages.map((item) =>
        Number(item.id) === Number(msg.id)
          ? { ...item, snoozed_until: remove ? null : snoozedUntil }
          : item
      );

      renderMessageList();
      renderMessageView();
      applyFolderCounts(result?.folder_counts || {});
      setFeedback(result?.message || "Adiamento atualizado.", "success");
    } finally {
      hideLoading();
    }
  }

  function prefillReply() {
    const msg = state.selectedMessage;

    if (!canReplyOrForward() || !msg) {
      setFeedback("Abra apenas uma mensagem para responder.", "error");
      return;
    }

    openCompose();

    if ($("to")) $("to").value = msg.from_email || "";
    if ($("subject")) {
      $("subject").value = msg.subject?.startsWith("Re:")
        ? msg.subject
        : `Re: ${msg.subject || ""}`.trim();
    }
    if ($("message")) {
      $("message").value = `\n\n---\n${msg.body_text || ""}`;
    }
  }

  function prefillForward() {
    const msg = state.selectedMessage;

    if (!canReplyOrForward() || !msg) {
      setFeedback("Abra apenas uma mensagem para encaminhar.", "error");
      return;
    }

    openCompose();

    if ($("to")) $("to").value = "";
    if ($("subject")) {
      $("subject").value = msg.subject?.startsWith("Fwd:")
        ? msg.subject
        : `Fwd: ${msg.subject || ""}`.trim();
    }
    if ($("message")) {
      $("message").value = [
        "",
        "",
        "--- Encaminhado ---",
        `De: ${msg.from_email || ""}`,
        `Para: ${msg.to_email || ""}`,
        `Data: ${formatDateTime(msg.sent_at || msg.created_at)}`,
        `Assunto: ${msg.subject || ""}`,
        "",
        msg.body_text || "",
      ].join("\n");
    }
  }

  async function logout() {
    try {
      stopAutoRefresh();

      if (state.authMode === "mailbox") {
        await api("/api/webmail-auth/logout", { method: "POST" });
      } else {
        await api("/api/logout", { method: "POST" });
      }
    } finally {
      window.location.href = state.authMode === "mailbox" ? "/webmail-login" : "/login";
    }
  }

  function stopAutoRefresh() {
    if (state.autoRefreshTimer) {
      clearInterval(state.autoRefreshTimer);
      state.autoRefreshTimer = null;
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();

    state.autoRefreshTimer = setInterval(async () => {
      if (document.hidden) return;
      if (!currentMailbox()) return;
      if (!shouldSyncFolder(state.currentFolder)) return;
      if (isComposeOpen()) return;
      if (state.isLoadingMessages) return;

      try {
        await loadMessages({ silent: true, page: state.page });
      } catch (error) {
        console.error("Erro no auto refresh:", error);
      }
    }, 10000);
  }

  function resetMessageContext() {
    clearSelections();
    state.selectedMessageId = null;
    state.selectedMessage = null;
    renderLayoutState();
    renderCategoryTabs();
  }

  function updateSelectionUi() {
    const selectedIds = getSelectedMessageIds();
    const visibleTotal = getVisibleMessages().length;

    setText("selectedCountLabel", `${selectedIds.length} selecionados`);

    const clearBtn = $("clearSelectionBtn");
    if (clearBtn) {
      clearBtn.style.display = selectedIds.length ? "inline-flex" : "none";
    }

    const selectAll = $("selectAllCheckbox");
    if (selectAll) {
      selectAll.checked = visibleTotal > 0 && selectedIds.length === visibleTotal;
      selectAll.indeterminate = selectedIds.length > 0 && selectedIds.length < visibleTotal;
    }

    renderPageUi();
  }

  function updateActionButtons() {
    const selectionCount = getSelectedMessageIds().length;
    const hasAnyTarget = selectionCount > 0 || hasActiveMessage();
    const folder = state.currentFolder;
    const singleActive = hasActiveMessage() && selectionCount === 0;
    const msg = state.selectedMessage;

    const spamBtn = $("spamBtn");
    const restoreBtn = $("restoreInboxBtn");
    const deleteBtn = $("archiveBtn");
    const replyBtn = $("replyBtn");
    const forwardBtn = $("forwardBtn");
    const starToggleBtn = $("starToggleBtn");
    const importantToggleBtn = $("importantToggleBtn");
    const snoozeBtn = $("snoozeBtn");
    const unsnoozeBtn = $("unsnoozeBtn");
    const detailBackBtn = $("detailBackBtn");

    if (spamBtn) spamBtn.disabled = !hasAnyTarget;

    if (restoreBtn) {
      const showRestore = ["junk", "trash"].includes(folder);
      restoreBtn.style.display = showRestore ? "inline-flex" : "none";
      restoreBtn.disabled = !hasAnyTarget;
    }

    if (deleteBtn) deleteBtn.disabled = !hasAnyTarget;
    if (replyBtn) replyBtn.disabled = !canReplyOrForward();
    if (forwardBtn) forwardBtn.disabled = !canReplyOrForward();

    if (starToggleBtn) {
      starToggleBtn.disabled = !singleActive;
      starToggleBtn.classList.toggle("is-active", Boolean(msg?.is_starred));
    }

    if (importantToggleBtn) {
      importantToggleBtn.disabled = !singleActive;
      importantToggleBtn.classList.toggle("is-active", Boolean(msg?.is_important));
    }

    if (snoozeBtn) {
      snoozeBtn.style.display = singleActive && !msg?.snoozed_until ? "inline-flex" : "none";
      snoozeBtn.disabled = !singleActive;
    }

    if (unsnoozeBtn) {
      unsnoozeBtn.style.display = singleActive && msg?.snoozed_until ? "inline-flex" : "none";
      unsnoozeBtn.disabled = !singleActive;
    }

    if (detailBackBtn) {
      detailBackBtn.style.display = hasActiveMessage() ? "inline-flex" : "none";
    }

    updateSelectionUi();
  }

  function handleSidebarAction(action) {
    if (action === "manage_subscriptions") {
      setFeedback("Tela de gerenciar inscrições ainda não implementada.", "error");
      return;
    }

    if (action === "manage_labels") {
      setFeedback("Tela de gerenciar marcadores ainda não implementada.", "error");
      return;
    }

    if (action === "create_label") {
      const name = window.prompt("Nome do novo marcador:");
      if (!name || !name.trim()) return;
      setFeedback("Marcadores personalizados entram na próxima etapa.", "success");
    }
  }

  async function refreshCurrentView() {
    showLoading("Sincronizando...");

    try {
      await loadContext();

      const mailbox = currentMailbox();
      if (mailbox && shouldSyncFolder(state.currentFolder)) {
        try {
          await forceMailboxSync(mailbox.id);
        } catch (error) {
          setFeedback(`${error.message} Exibindo locais.`, "error");
        }
      }

      await loadMessages({ silent: true, primeSidebar: true, page: state.page });
      setFeedback("Sincronizado.", "success");
    } catch (error) {
      setFeedback(error.message, "error");
    } finally {
      hideLoading();
    }
  }

  function bindEvents() {
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;

      let handled = false;

      if ($("composeModal")?.classList.contains("active")) {
        closeCompose();
        handled = true;
      }

      if ($("mailSidebar")?.classList.contains("open")) {
        closeMobileSidebar();
        handled = true;
      }

      if (!handled && hasActiveMessage()) {
        resetMessageContext();
        renderMessageList();
        renderEmptyMessageView();
      }
    });

    document.addEventListener("visibilitychange", async () => {
      if (document.hidden) return;
      if (!currentMailbox()) return;
      if (state.isLoadingMessages) return;

      try {
        await loadMessages({ silent: true, page: state.page });
      } catch (error) {
        console.error("Erro ao atualizar ao voltar para a aba:", error);
      }
    });

    $("menuToggleBtn")?.addEventListener("click", () => {
      $("mailSidebar")?.classList.add("open");
      $("sidebarOverlay")?.classList.add("active");
    });

    $("sidebarOverlay")?.addEventListener("click", closeMobileSidebar);

    $("selectAllCheckbox")?.addEventListener("change", (event) => {
      setAllSelections(Boolean(event.target.checked));
    });

    $("clearSelectionBtn")?.addEventListener("click", () => {
      clearSelections();
      renderMessageList();
      updateActionButtons();
    });

    $("domainSelect")?.addEventListener("change", async (event) => {
      if (state.authMode === "mailbox") return;

      state.currentDomainId = Number(event.target.value || 0) || null;
      const items = mailboxOptionsForCurrentDomain();
      const activeFirst = items.find((item) => item.is_active) || items[0] || null;
      state.currentMailboxId = activeFirst?.id || null;

      renderMailboxOptions();
      renderCurrentContext();
      updateComposeFrom();
      syncUrlSelection();
      resetMessageContext();
      resetFolderSummaries();
      resetPagination();

      try {
        await loadMessages({ primeSidebar: true, page: 1 });
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("mailboxSelect")?.addEventListener("change", async (event) => {
      if (state.authMode === "mailbox") return;

      state.currentMailboxId = Number(event.target.value || 0) || null;
      renderCurrentContext();
      updateComposeFrom();
      syncUrlSelection();
      resetMessageContext();
      resetFolderSummaries();
      resetPagination();

      try {
        await loadMessages({ primeSidebar: true, page: 1 });
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    document.addEventListener("click", async (event) => {
      const folderItem = event.target.closest("[data-folder]");
      if (folderItem) {
        event.preventDefault();

        state.currentFolder = folderItem.dataset.folder || "inbox";
        if (state.currentFolder !== "inbox") state.inboxCategory = "primary";
        resetPagination();
        resetMessageContext();
        closeMobileSidebar();
        renderFolderNav();

        try {
          await loadMessages({ page: 1 });
        } catch (error) {
          setFeedback(error.message, "error");
        }
        return;
      }

      const actionItem = event.target.closest("[data-action]");
      if (actionItem) {
        event.preventDefault();
        handleSidebarAction(actionItem.dataset.action);
        return;
      }

      const categoryItem = event.target.closest("[data-category]");
      if (categoryItem) {
        const category = categoryItem.dataset.category || "primary";
        state.inboxCategory = category;

        clearSelections();
        resetPagination();

        if (state.selectedMessageId) {
          state.selectedMessageId = null;
          state.selectedMessage = null;
          renderEmptyMessageView();
        }

        renderCategoryTabs();

        try {
          await loadMessages({ page: 1, silent: false });
        } catch (error) {
          setFeedback(error.message, "error");
        }
      }
    });

    $("mailList")?.addEventListener("click", async (event) => {
      const checkbox = event.target.closest(".mail-item__checkbox");
      if (checkbox) {
        const messageId = Number(checkbox.getAttribute("data-message-id"));
        if (!messageId) return;
        toggleMessageSelection(messageId, checkbox.checked);
        return;
      }

      const starButton = event.target.closest("[data-star-message-id]");
      if (starButton) {
        event.preventDefault();
        event.stopPropagation();

        const messageId = Number(starButton.getAttribute("data-star-message-id"));
        if (!messageId) return;

        try {
          await toggleMessageStarById(messageId);
        } catch (error) {
          setFeedback(error.message, "error");
        }
        return;
      }

      const item = event.target.closest("[data-message-id]");
      if (!item) return;

      const messageId = Number(item.getAttribute("data-message-id"));
      if (!messageId) return;

      try {
        await loadMessageDetail(messageId, true);
        renderMessageList();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("openComposeBtn")?.addEventListener("click", () => {
      closeMobileSidebar();
      openCompose();
    });

    $("closeComposeBtn")?.addEventListener("click", closeCompose);
    $("composeOverlay")?.addEventListener("click", closeCompose);

    $("toggleSchedulePanelBtn")?.addEventListener("click", () => {
      const panel = $("composeSchedulePanel");
      if (!panel) return;
      setScheduledPanel(panel.style.display === "none");
    });

    $("clearScheduledForBtn")?.addEventListener("click", () => {
      if ($("scheduledFor")) $("scheduledFor").value = "";
    });

    $("draftBtn")?.addEventListener("click", async () => {
      try {
        await sendCompose("draft");
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("scheduleSendBtn")?.addEventListener("click", async () => {
      try {
        await sendCompose("scheduled");
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("composeForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await sendCompose("send");
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("replyBtn")?.addEventListener("click", prefillReply);
    $("forwardBtn")?.addEventListener("click", prefillForward);

    $("archiveBtn")?.addEventListener("click", async () => {
      try {
        await runPrimaryDeleteAction();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("spamBtn")?.addEventListener("click", async () => {
      try {
        await moveSelectedToJunk();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("restoreInboxBtn")?.addEventListener("click", async () => {
      try {
        await moveSelectedToInbox();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("starToggleBtn")?.addEventListener("click", async () => {
      try {
        await toggleActiveMessageStar();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("importantToggleBtn")?.addEventListener("click", async () => {
      try {
        await toggleActiveMessageImportant();
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("snoozeBtn")?.addEventListener("click", async () => {
      try {
        await snoozeActiveMessage(false);
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("unsnoozeBtn")?.addEventListener("click", async () => {
      try {
        await snoozeActiveMessage(true);
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("detailBackBtn")?.addEventListener("click", () => {
      resetMessageContext();
      renderMessageList();
      renderEmptyMessageView();
    });

    $("refreshBtn")?.addEventListener("click", refreshCurrentView);
    $("refreshListBtn")?.addEventListener("click", refreshCurrentView);
    $("logoutBtn")?.addEventListener("click", logout);

    $("prevPageBtn")?.addEventListener("click", async () => {
      if (!state.hasPrev || state.isLoadingMessages) return;
      try {
        await loadMessages({ page: state.page - 1 });
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("nextPageBtn")?.addEventListener("click", async () => {
      if (!state.hasNext || state.isLoadingMessages) return;
      try {
        await loadMessages({ page: state.page + 1 });
      } catch (error) {
        setFeedback(error.message, "error");
      }
    });

    $("densityBtn")?.addEventListener("click", () => {
      const order = ["default", "compact", "comfortable"];
      const currentIndex = order.indexOf(state.density);
      state.density = order[(currentIndex + 1) % order.length];
      applyDensityClass();

      const labelMap = {
        default: "Densidade padrão",
        compact: "Densidade compacta",
        comfortable: "Densidade confortável",
      };

      setFeedback(labelMap[state.density] || "Densidade atualizada.", "success");
    });

    $("listMoreBtn")?.addEventListener("click", async () => {
      const mailbox = currentMailbox();
      if (!mailbox) return;

      if (state.currentFolder === "scheduled" && state.authMode === "platform") {
        try {
          showLoading("Processando fila programada...");
          const result = await api("/api/webmail/scheduled/run-now", { method: "POST" });
          setFeedback(result?.message || "Fila processada.", "success");
          await loadMessages({ silent: true, primeSidebar: true, page: state.page });
        } catch (error) {
          setFeedback(error.message, "error");
        } finally {
          hideLoading();
        }
        return;
      }

      setFeedback("Menu adicional entra na próxima etapa.", "success");
    });

    $("mailSearch")?.addEventListener("input", (event) => {
      state.search = String(event.target.value || "").trim();

      if (state.searchTimer) clearTimeout(state.searchTimer);

      state.searchTimer = setTimeout(async () => {
        try {
          resetPagination();
          resetMessageContext();
          await loadMessages({ page: 1 });
        } catch (error) {
          setFeedback(error.message, "error");
        }
      }, 250);
    });
  }

  async function init() {
    try {
      applyDensityClass();
      await loadContext();
      bindEvents();
      renderFolderNav();
      renderCategoryTabs();
      renderLayoutState();
      renderPageUi();
      await loadMessages({ primeSidebar: true, page: 1 });
      updateActionButtons();
      startAutoRefresh();
    } catch (error) {
      setFeedback(error.message || "Erro ao carregar o webmail.", "error");
    }
  }

  window.addEventListener("beforeunload", stopAutoRefresh);
  document.addEventListener("DOMContentLoaded", init);
})();
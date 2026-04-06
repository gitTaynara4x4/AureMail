(function () {
  const state = {
    me: null,
    authMode: "platform",
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
    search: "",
    searchTimer: null,
  };

  function $(id) { return document.getElementById(id); }

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

  function setFeedback(message, type = "") {
    const box = $("mailFeedback");
    if (!box) return;
    box.textContent = message || "";
    box.className = `mail-feedback ${type}`.trim();
  }

  async function parseJson(response) {
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }

    if (!response.ok) {
      const message = payload?.detail || payload?.message || `Erro ${response.status}`;
      throw new Error(message);
    }

    return payload;
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
      window.location.href = state.authMode === "mailbox" ? "/webmail-login" : "/login";
      throw new Error("Sessão expirada.");
    }

    return parseJson(response);
  }

  async function tryGetJson(url) {
    try {
      const response = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });

      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    }
  }

  async function mountSidebar() {
    if (state.authMode === "mailbox") {
      const mount = $("sidebarMount");
      if (mount) mount.innerHTML = "";
      return;
    }

    const mount = $("sidebarMount");
    if (!mount) return;

    const response = await fetch("/assets/partials/sidebar.html", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "text/html" },
    });

    if (!response.ok) return;
    mount.innerHTML = await response.text();

    mount.querySelectorAll("script").forEach((oldScript) => {
      const newScript = document.createElement("script");
      Array.from(oldScript.attributes).forEach((attr) => {
        newScript.setAttribute(attr.name, attr.value);
      });
      newScript.textContent = oldScript.textContent;
      oldScript.replaceWith(newScript);
    });

    highlightCurrentSidebarLink();
  }

  function highlightCurrentSidebarLink() {
    const currentPath = (window.location.pathname || "/").replace(/\/+$/, "") || "/";
    document.querySelectorAll("#sidebarMount a[href]").forEach((link) => {
      const href = (link.getAttribute("href") || "").trim();
      if (!href || href.startsWith("#") || href.startsWith("http")) return;
      const normalizedHref = href.replace(/\/+$/, "") || "/";
      const active = normalizedHref === currentPath;

      link.classList.toggle("active", active);
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  async function loadMe() {
    const platformMe = await tryGetJson("/api/me");
    if (platformMe?.success) {
      state.authMode = "platform";
      state.me = platformMe;
      if (window.AureMailSidebar?.apply) window.AureMailSidebar.apply(state.me);
      return;
    }

    const mailboxMe = await tryGetJson("/api/webmail-auth/me");
    if (mailboxMe?.success) {
      state.authMode = "mailbox";
      state.me = mailboxMe;
      return;
    }

    window.location.href = "/webmail-login";
  }

  async function loadContext() {
    const initial = getQuerySelection();
    const params = new URLSearchParams();

    if (initial.dominioId) params.set("dominio_id", String(initial.dominioId));
    if (initial.caixaId) params.set("caixa_id", String(initial.caixaId));

    const data = await api(`/api/webmail/context?${params.toString()}`);
    state.context = data;
    state.company = data?.company || null;
    state.user = data?.user || null;
    state.domains = Array.isArray(data?.domains) ? data.domains : [];
    state.mailboxes = Array.isArray(data?.mailboxes) ? data.mailboxes : [];
    state.currentDomainId = data?.selected_domain_id || null;
    state.currentMailboxId = data?.selected_mailbox_id || null;

    renderDomainOptions();
    renderMailboxOptions();
    renderCurrentContext();
    updateComposeFrom();
    syncUrlSelection();
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
      const activeFirst = items.find((item) => item.is_active) || items[0];
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
    const company = state.company || {};
    const domain = currentDomain();
    const mailbox = currentMailbox();
    if (!info) return;

    if (!state.domains.length) {
      info.innerHTML = `Empresa <strong>${escapeHtml(company.name || "AureMail")}</strong> &bull; Sem domínios.`;
      return;
    }

    if (!mailbox) {
      info.innerHTML = `Empresa <strong>${escapeHtml(company.name || "AureMail")}</strong> &bull; <strong>${escapeHtml(domain?.name || "-")}</strong> &bull; Nenhuma caixa.`;
      return;
    }

    info.innerHTML = `Empresa <strong>${escapeHtml(company.name || "AureMail")}</strong> &bull; <strong>${escapeHtml(domain?.name || "-")}</strong> &bull; Acessando <strong>${escapeHtml(mailbox.email)}</strong>`;
  }

  function updateComposeFrom() {
    const fromInput = $("from");
    const mailbox = currentMailbox();
    if (fromInput) fromInput.value = mailbox?.email || "";
  }

  function renderFolderCounts(counts = {}) {
    document.querySelectorAll(".mail-nav__item").forEach((item) => {
      const folder = item.dataset.folder;
      const counter = item.querySelector("strong");
      const isActive = folder === state.currentFolder;

      item.classList.toggle("active", isActive);

      if (counter) {
        counter.textContent = String(counts?.[folder] ?? 0);
      }
    });
  }

  function formatDate(value) {
    if (!value) return "Agora";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Data inválida";

    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(date);
    }
    return new Intl.DateTimeFormat("pt-BR", { month: "short", day: "numeric" }).format(date);
  }

  function renderNoDomainState() {
    renderFolderCounts({});
    $("mailResultsCount").textContent = "0 resultados";
    $("mailList").innerHTML = `
      <div class="mail-empty-state">
        Sua empresa ainda não possui domínio cadastrado.<br /><br />
        <a href="/dominios">Ir para domínios</a>
      </div>
    `;
    $("mailView").innerHTML = `<div class="mail-empty-state">Cadastre um domínio para começar a usar o webmail.</div>`;
    $("mailViewSubtitle").textContent = "Mensagem selecionada";
  }

  function renderNoMailboxState() {
    renderFolderCounts({});
    $("mailResultsCount").textContent = "0 resultados";
    $("mailList").innerHTML = `
      <div class="mail-empty-state">
        Não existe caixa de e-mail para o domínio selecionado.<br /><br />
        <a href="/caixas-email">Ir para caixas de e-mail</a>
      </div>
    `;
    $("mailView").innerHTML = `<div class="mail-empty-state">Crie uma caixa para este domínio antes de usar o webmail.</div>`;
    $("mailViewSubtitle").textContent = "Mensagem selecionada";
  }

  async function loadMessages() {
    if (!state.domains.length) {
      renderNoDomainState();
      return;
    }

    const mailbox = currentMailbox();
    if (!mailbox) {
      renderNoMailboxState();
      return;
    }

    const params = new URLSearchParams({ folder: state.currentFolder });
    if (state.search) params.set("q", state.search);

    const data = await api(`/api/webmail/mailboxes/${mailbox.id}/messages?${params.toString()}`);
    state.messages = Array.isArray(data?.items) ? data.items : [];

    renderFolderCounts(data?.folder_counts || {});
    renderMessageList();

    $("mailResultsCount").textContent = `${state.messages.length} itens`;

    const exists = state.messages.some((item) => Number(item.id) === Number(state.selectedMessageId));
    if (!exists) {
      state.selectedMessageId = state.messages[0]?.id || null;
      state.selectedMessage = null;
    }

    if (state.selectedMessageId) {
      await loadMessageDetail(state.selectedMessageId, false);
    } else {
      renderEmptyMessageView();
    }
  }

  function renderMessageList() {
    const list = $("mailList");
    if (!list) return;

    if (!state.messages.length) {
      list.innerHTML = `<div class="mail-empty-state">Nenhuma mensagem encontrada.</div>`;
      return;
    }

    list.innerHTML = state.messages
      .map((item) => {
        const active = Number(item.id) === Number(state.selectedMessageId);
        const unread = !item.is_read;
        const person = item.direction === "outbound"
          ? item.to_email
          : (item.from_name || item.from_email || "Remetente");

        return `
          <div class="mail-item ${active ? "active" : ""} ${unread ? "unread" : ""}" data-message-id="${item.id}">
            <div class="mail-item__top">
              <div class="mail-item__from">${escapeHtml(person)}</div>
              <div class="mail-item__date">${escapeHtml(formatDate(item.sent_at || item.created_at))}</div>
            </div>
            <div class="mail-item__subject">${escapeHtml(item.subject || "(sem assunto)")}</div>
            <div class="mail-item__preview">${escapeHtml(item.preview || "Sem visualização disponível.")}</div>
          </div>
        `;
      })
      .join("");
  }

  function renderEmptyMessageView() {
    $("mailView").innerHTML = `<div class="mail-empty-state">Selecione uma mensagem na lista para ler o conteúdo.</div>`;
    $("mailViewSubtitle").textContent = "Nenhuma mensagem";
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
          Number(item.id) === Number(messageId) ? { ...item, is_read: true } : item
        );
        renderMessageList();
      } catch (_) {}
    }
  }

  function renderMessageView() {
    const view = $("mailView");
    const msg = state.selectedMessage;

    if (!view || !msg) {
      renderEmptyMessageView();
      return;
    }

    $("mailViewSubtitle").textContent = msg.subject || "Sem assunto";

    view.innerHTML = `
      <div class="mail-view__header">
        <h2>${escapeHtml(msg.subject || "(sem assunto)")}</h2>
        <div class="mail-view__meta">
          <div><strong>De:</strong> ${escapeHtml(msg.from_name ? `${msg.from_name} <${msg.from_email}>` : msg.from_email)}</div>
          <div><strong>Para:</strong> ${escapeHtml(msg.to_email || "-")}</div>
          <div><strong>Data:</strong> ${escapeHtml(formatDate(msg.sent_at || msg.created_at))}</div>
        </div>
      </div>
      <div class="mail-view__body">${escapeHtml(msg.body_text || "Esta mensagem não possui conteúdo de texto.")}</div>
    `;
  }

  function openCompose() {
    if (!currentMailbox()) {
      setFeedback("Selecione uma caixa real antes de compor um e-mail.", "error");
      return;
    }
    $("composeOverlay").classList.add("active");
    $("composeModal").classList.add("active");
    $("composeModal").setAttribute("aria-hidden", "false");
    updateComposeFrom();
  }

  function closeCompose() {
    $("composeOverlay").classList.remove("active");
    $("composeModal").classList.remove("active");
    $("composeModal").setAttribute("aria-hidden", "true");
  }

  function resetComposeForm() {
    $("composeForm")?.reset();
    updateComposeFrom();
  }

  async function sendCompose(saveAsDraft) {
    const mailbox = currentMailbox();
    if (!mailbox) {
      setFeedback("Nenhuma caixa selecionada.", "error");
      return;
    }

    const to = $("to")?.value?.trim();
    const subject = $("subject")?.value?.trim();
    const body = $("message")?.value?.trim();

    if (!to) {
      setFeedback("Informe o destinatário.", "error");
      return;
    }

    const result = await api(`/api/webmail/mailboxes/${mailbox.id}/compose`, {
      method: "POST",
      body: { to, subject: subject || null, body: body || null, save_as_draft: Boolean(saveAsDraft) },
    });

    closeCompose();
    resetComposeForm();

    state.currentFolder = saveAsDraft ? "drafts" : "sent";
    state.selectedMessageId = result?.item?.id || null;

    await loadMessages();
    setFeedback(result?.message || "Mensagem processada com sucesso.", "success");
  }

  async function moveSelectedToTrash() {
    const mailbox = currentMailbox();
    const msg = state.selectedMessage;
    if (!mailbox || !msg) {
      setFeedback("Selecione uma mensagem primeiro.", "error");
      return;
    }

    await api(`/api/webmail/mailboxes/${mailbox.id}/messages/${msg.id}/move`, {
      method: "POST",
      body: { target_folder: "trash" },
    });

    state.selectedMessage = null;
    state.selectedMessageId = null;
    await loadMessages();
    setFeedback("Mensagem movida para a lixeira.", "success");
  }

  function prefillReply() {
    const msg = state.selectedMessage;
    if (!msg) {
      setFeedback("Selecione uma mensagem para responder.", "error");
      return;
    }

    openCompose();
    $("to").value = msg.from_email || "";
    $("subject").value = msg.subject?.startsWith("Re:") ? msg.subject : `Re: ${msg.subject || ""}`.trim();
    $("message").value = `\n\n---\n${msg.body_text || ""}`;
  }

  function prefillForward() {
    const msg = state.selectedMessage;
    if (!msg) {
      setFeedback("Selecione uma mensagem para encaminhar.", "error");
      return;
    }

    openCompose();
    $("to").value = "";
    $("subject").value = msg.subject?.startsWith("Fwd:") ? msg.subject : `Fwd: ${msg.subject || ""}`.trim();
    $("message").value = [
      "", "", "--- Encaminhado ---",
      `De: ${msg.from_email || ""}`,
      `Para: ${msg.to_email || ""}`,
      `Data: ${formatDate(msg.sent_at || msg.created_at)}`,
      `Assunto: ${msg.subject || ""}`,
      "", msg.body_text || "",
    ].join("\n");
  }

  async function logout() {
    try {
      if (state.authMode === "mailbox") {
        await api("/api/webmail-auth/logout", { method: "POST" });
      } else {
        await api("/api/logout", { method: "POST" });
      }
    } finally {
      window.location.href = state.authMode === "mailbox" ? "/webmail-login" : "/login";
    }
  }

  function bindEvents() {
    $("domainSelect")?.addEventListener("change", async (event) => {
      state.currentDomainId = Number(event.target.value || 0) || null;
      const items = mailboxOptionsForCurrentDomain();
      const activeFirst = items.find((item) => item.is_active) || items[0] || null;
      state.currentMailboxId = activeFirst?.id || null;

      renderMailboxOptions();
      renderCurrentContext();
      updateComposeFrom();
      syncUrlSelection();

      state.selectedMessageId = null;
      state.selectedMessage = null;
      await loadMessages();
    });

    $("mailboxSelect")?.addEventListener("change", async (event) => {
      state.currentMailboxId = Number(event.target.value || 0) || null;
      renderCurrentContext();
      updateComposeFrom();
      syncUrlSelection();

      state.selectedMessageId = null;
      state.selectedMessage = null;
      await loadMessages();
    });

    document.querySelectorAll(".mail-nav__item").forEach((item) => {
      item.addEventListener("click", async (event) => {
        event.preventDefault();
        state.currentFolder = item.dataset.folder || "inbox";
        state.selectedMessageId = null;
        state.selectedMessage = null;
        await loadMessages();
      });
    });

    $("mailList")?.addEventListener("click", async (event) => {
      const item = event.target.closest("[data-message-id]");
      if (!item) return;
      const messageId = Number(item.getAttribute("data-message-id"));
      if (!messageId) return;

      await loadMessageDetail(messageId, true);
      renderMessageList();
    });

    $("openComposeBtn")?.addEventListener("click", openCompose);
    $("closeComposeBtn")?.addEventListener("click", closeCompose);
    $("composeOverlay")?.addEventListener("click", closeCompose);

    $("draftBtn")?.addEventListener("click", async () => {
      try {
        await sendCompose(true);
      } catch (error) {
        setFeedback(error.message || "Erro ao salvar rascunho.", "error");
      }
    });

    $("composeForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await sendCompose(false);
      } catch (error) {
        setFeedback(error.message || "Erro ao enviar mensagem.", "error");
      }
    });

    $("replyBtn")?.addEventListener("click", prefillReply);
    $("forwardBtn")?.addEventListener("click", prefillForward);
    $("archiveBtn")?.addEventListener("click", async () => {
      try {
        await moveSelectedToTrash();
      } catch (error) {
        setFeedback(error.message || "Erro ao mover mensagem.", "error");
      }
    });

    $("refreshBtn")?.addEventListener("click", async () => {
      try {
        await loadContext();
        await loadMessages();
      } catch (error) {
        setFeedback(error.message || "Erro ao atualizar webmail.", "error");
      }
    });

    $("logoutBtn")?.addEventListener("click", logout);

    $("mailSearch")?.addEventListener("input", (event) => {
      state.search = String(event.target.value || "").trim();
      if (state.searchTimer) clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(async () => {
        try {
          state.selectedMessageId = null;
          state.selectedMessage = null;
          await loadMessages();
        } catch (error) {
          setFeedback(error.message || "Erro ao buscar mensagens.", "error");
        }
      }, 250);
    });
  }

  async function init() {
    try {
      await loadMe();
      await mountSidebar();
      await loadContext();
      bindEvents();
      await loadMessages();
    } catch (error) {
      setFeedback(error.message || "Erro ao carregar o webmail.", "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
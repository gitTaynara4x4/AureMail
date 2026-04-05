(function () {
  const state = {
    me: null,
    domains: [],
    mailboxes: [],
    editingId: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeLocalPart(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "");
  }

  function humanizeMailboxStatus(isActive) {
    return isActive ? "Ativa" : "Inativa";
  }

  function formatQuota(value) {
    const quota = Number(value || 0);
    return `${quota} MB`;
  }

  function formatDate(value) {
    if (!value) return "Agora há pouco";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Data inválida";
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date);
  }

  function setMessage(message, type = "info") {
    const box = $("mailboxFormMessage");
    if (!box) return;
    box.textContent = message || "";
    box.className = `form-message ${type}`.trim();
    box.style.display = message ? "block" : "none";
  }

  function clearMessage() {
    setMessage("", "info");
  }

  async function parseJson(response) {
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const errorMessage = payload?.detail || payload?.message || `Erro ${response.status}`;
      throw new Error(errorMessage);
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
      window.location.href = "/login";
      throw new Error("Sessão expirada.");
    }

    return parseJson(response);
  }

  async function mountSidebar() {
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
    state.me = await api("/api/me");
    if (window.AureMailSidebar?.apply) {
      window.AureMailSidebar.apply(state.me);
    }
  }

  async function loadDomains() {
    const data = await api("/api/dominios");
    state.domains = Array.isArray(data?.items) ? data.items : [];
    renderDomainOptions();
    toggleMailboxFormAvailability();
  }

  async function loadMailboxes(showFeedback = false) {
    const data = await api("/api/caixas-email");
    state.mailboxes = Array.isArray(data?.items) ? data.items : [];
    renderMailboxes();

    if (showFeedback) {
      setMessage("Lista de caixas atualizada.", "success");
    }
  }

  function renderDomainOptions(selectedId = "") {
    const select = $("mailboxDomainId");
    if (!select) return;

    if (!state.domains.length) {
      select.innerHTML = `<option value="">Nenhum domínio cadastrado</option>`;
      return;
    }

    const options = state.domains
      .map((domain) => {
        const selected = String(domain.id) === String(selectedId) ? "selected" : "";
        const label = domain.is_primary ? `${domain.name} (principal)` : domain.name;
        return `<option value="${domain.id}" ${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");

    select.innerHTML = options;
  }

  function renderDomainSelectHtml(selectedId) {
    if (!state.domains.length) {
      return `<option value="">Nenhum domínio disponível</option>`;
    }

    return state.domains
      .map((domain) => {
        const selected = String(domain.id) === String(selectedId) ? "selected" : "";
        const label = domain.is_primary ? `${domain.name} (principal)` : domain.name;
        return `<option value="${domain.id}" ${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

  function toggleMailboxFormAvailability() {
    const form = $("mailboxForm");
    const button = $("createMailboxBtn");
    const disabled = !state.domains.length;

    form?.querySelectorAll("input, select, button").forEach((el) => {
      if (el.id === "createMailboxBtn") return;
      el.disabled = disabled;
    });

    if (button) button.disabled = disabled;

    if (disabled) {
      setMessage("Cadastre pelo menos um domínio antes de criar caixas.", "info");
    }
  }

  function renderMailboxes() {
    const list = $("mailboxList");
    const count = $("mailboxesCount");

    if (count) {
      const total = state.mailboxes.length;
      count.textContent = `${total} ${total === 1 ? "item" : "itens"}`;
    }

    if (!list) return;

    if (!state.mailboxes.length) {
      list.innerHTML = `
        <div class="empty-note">
          Nenhuma caixa cadastrada ainda. Crie a primeira conta profissional da empresa.
        </div>
      `;
      return;
    }

    list.innerHTML = state.mailboxes.map((item) => renderMailboxItem(item)).join("");
  }

  // --- NOVA RENDERIZAÇÃO VISUAL PARA O MODO CLEAR/SAAS ---
  function renderMailboxItem(item) {
    const isEditing = state.editingId === item.id;
    const statusClass = item.is_active ? "active" : "inactive";

    if (isEditing) {
      return `
        <div class="domain-item edit-inline" data-mailbox-id="${item.id}">
          <form class="mailbox-edit-form" data-mailbox-id="${item.id}">
            <div class="field">
              <label for="edit-domain-${item.id}">Domínio</label>
              <div class="select-wrapper">
                <select id="edit-domain-${item.id}" name="dominio_id" required>
                  ${renderDomainSelectHtml(item.dominio_id)}
                </select>
                <svg class="select-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
              </div>
            </div>

            <div class="field">
              <label for="edit-local-${item.id}">Nome da Conta</label>
              <input type="text" id="edit-local-${item.id}" name="local_part" value="${escapeHtml(item.local_part)}" maxlength="120" required />
            </div>

            <div class="field">
              <label for="edit-display-${item.id}">Nome de Exibição</label>
              <input type="text" id="edit-display-${item.id}" name="display_name" value="${escapeHtml(item.display_name || "")}" maxlength="150" />
            </div>

            <div class="field">
              <label for="edit-quota-${item.id}">Quota (MB)</label>
              <input type="number" id="edit-quota-${item.id}" name="quota_mb" min="128" max="102400" step="128" value="${Number(item.quota_mb || 2048)}" required />
            </div>

            <label class="checkbox-row" for="edit-active-${item.id}">
              <input type="checkbox" id="edit-active-${item.id}" name="is_active" ${item.is_active ? "checked" : ""} />
              <span class="checkbox-box"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
              <span class="checkbox-text">Caixa Ativa</span>
            </label>

            <div class="edit-actions">
              <button type="submit" class="btn btn-primary">Salvar alterações</button>
              <button type="button" class="btn btn-secondary" data-action="cancel-edit" data-id="${item.id}">Cancelar</button>
            </div>
          </form>
        </div>
      `;
    }

    return `
      <div class="domain-item" data-mailbox-id="${item.id}">
        <div class="domain-item__top">
          <div class="domain-info">
            <h4>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
              ${escapeHtml(item.email)}
            </h4>
            
            <div class="domain-meta">
              <span class="status-chip ${statusClass}">${escapeHtml(humanizeMailboxStatus(item.is_active))}</span>
              <span>${item.display_name ? `<strong>${escapeHtml(item.display_name)}</strong> &bull; ` : ""}Domínio: ${escapeHtml(item.domain_name || "-")}</span>
              <span>&bull; Quota: ${escapeHtml(formatQuota(item.quota_mb))}</span>
            </div>
            
            <div class="domain-meta" style="margin-top: 4px;">
              <span style="font-size: 12px;">Atualizado em ${escapeHtml(formatDate(item.updated_at || item.created_at))}</span>
            </div>
          </div>

          <div class="domain-actions">
            <button type="button" class="btn-icon" data-action="edit" data-id="${item.id}" title="Editar Caixa">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
            </button>
            <button type="button" class="btn-icon danger" data-action="delete" data-id="${item.id}" title="Excluir Caixa">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function resetCreateForm() {
    const form = $("mailboxForm");
    if (!form) return;

    form.reset();
    $("mailboxQuotaMb").value = "2048";
    $("mailboxIsActive").checked = true;

    if (state.domains.length) {
      renderDomainOptions(state.domains[0].id);
    }
  }

  async function handleCreate(event) {
    event.preventDefault();
    clearMessage();

    const dominioId = Number($("mailboxDomainId")?.value);
    const localPart = normalizeLocalPart($("mailboxLocalPart")?.value);
    const displayName = ($("mailboxDisplayName")?.value || "").trim();
    const quotaMb = Number($("mailboxQuotaMb")?.value || 2048);
    const isActive = Boolean($("mailboxIsActive")?.checked);

    if (!dominioId) {
      setMessage("Selecione um domínio.", "error");
      return;
    }

    if (!localPart) {
      setMessage("Informe o nome da caixa.", "error");
      return;
    }

    try {
      const result = await api("/api/caixas-email", {
        method: "POST",
        body: {
          dominio_id: dominioId,
          local_part: localPart,
          display_name: displayName || null,
          quota_mb: quotaMb,
          is_active: isActive,
        },
      });

      resetCreateForm();
      state.editingId = null;
      await loadMailboxes();
      setMessage(result?.message || "Caixa criada com sucesso.", "success");
    } catch (error) {
      setMessage(error.message || "Erro ao criar caixa.", "error");
    }
  }

  async function handleListClick(event) {
    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) return;

    const action = actionButton.getAttribute("data-action");
    const mailboxId = Number(actionButton.getAttribute("data-id"));

    if (!mailboxId) return;

    if (action === "edit") {
      state.editingId = mailboxId;
      renderMailboxes();
      return;
    }

    if (action === "cancel-edit") {
      state.editingId = null;
      renderMailboxes();
      return;
    }

    if (action === "delete") {
      const confirmed = window.confirm("Deseja realmente excluir esta caixa de e-mail?");
      if (!confirmed) return;

      try {
        clearMessage();
        const result = await api(`/api/caixas-email/${mailboxId}`, {
          method: "DELETE",
        });

        if (state.editingId === mailboxId) {
          state.editingId = null;
        }

        await loadMailboxes();
        setMessage(result?.message || "Caixa removida com sucesso.", "success");
      } catch (error) {
        setMessage(error.message || "Erro ao excluir caixa.", "error");
      }
    }
  }

  async function handleEditSubmit(event) {
    const form = event.target.closest(".mailbox-edit-form");
    if (!form) return;

    event.preventDefault();
    clearMessage();

    const mailboxId = Number(form.getAttribute("data-mailbox-id"));
    if (!mailboxId) return;

    const dominioId = Number(form.elements.dominio_id?.value);
    const localPart = normalizeLocalPart(form.elements.local_part?.value);
    const displayName = (form.elements.display_name?.value || "").trim();
    const quotaMb = Number(form.elements.quota_mb?.value || 2048);
    const isActive = Boolean(form.elements.is_active?.checked);

    if (!dominioId) {
      setMessage("Selecione um domínio.", "error");
      return;
    }

    if (!localPart) {
      setMessage("Informe o nome da caixa.", "error");
      return;
    }

    try {
      const result = await api(`/api/caixas-email/${mailboxId}`, {
        method: "PATCH",
        body: {
          dominio_id: dominioId,
          local_part: localPart,
          display_name: displayName || null,
          quota_mb: quotaMb,
          is_active: isActive,
        },
      });

      state.editingId = null;
      await loadMailboxes();
      setMessage(result?.message || "Caixa atualizada com sucesso.", "success");
    } catch (error) {
      setMessage(error.message || "Erro ao atualizar caixa.", "error");
    }
  }

  async function init() {
    try {
      await mountSidebar();
      await loadMe();
      await loadDomains();
      await loadMailboxes();

      if (state.domains.length) {
        renderDomainOptions(state.domains[0].id);
      }
    } catch (error) {
      setMessage(error.message || "Erro ao carregar a página.", "error");
    }

    $("mailboxForm")?.addEventListener("submit", handleCreate);
    $("mailboxList")?.addEventListener("click", handleListClick);
    $("mailboxList")?.addEventListener("submit", handleEditSubmit);

    $("refreshMailboxesBtn")?.addEventListener("click", async () => {
      clearMessage();
      try {
        await loadDomains();
        await loadMailboxes(true);
      } catch (error) {
        setMessage(error.message || "Erro ao atualizar lista.", "error");
      }
    });

    $("backToDomainsBtn")?.addEventListener("click", () => {
      window.location.href = "/dominios";
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
(function () {
  const params = new URLSearchParams(window.location.search);

  const state = {
    me: null,
    domains: [],
    mailboxes: [],
    editingId: null,
    preferredDomainId: Number(params.get("dominio_id") || 0) || null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  const elements = {
    sidebarMount: $("sidebarMount"),
    openModalBtn: $("openModalBtn"),
    openModalBtnInline: $("openModalBtnInline"),
    refreshBtn: $("refreshMailboxesBtn"),
    backBtn: $("backToDomainsBtn"),

    totalMailboxes: $("totalMailboxes"),
    activeMailboxes: $("activeMailboxes"),
    totalDomains: $("totalDomains"),
    count: $("mailboxesCount"),
    list: $("mailboxList"),

    modalOverlay: $("mailboxModalOverlay"),
    modal: $("mailboxModal"),
    modalTitle: $("modalTitle"),
    modalSubtitle: $("modalSubtitle"),
    closeModalBtn: $("closeModalBtn"),
    cancelModalBtn: $("cancelModalBtn"),
    form: $("mailboxForm"),
    saveBtn: $("saveMailboxBtn"),
    modalAlert: $("modalAlert"),

    domainId: $("mailboxDomainId"),
    localPart: $("mailboxLocalPart"),
    displayName: $("mailboxDisplayName"),
    password: $("mailboxPassword"),
    confirmPassword: $("mailboxConfirmPassword"),
    quotaMb: $("mailboxQuotaMb"),
    isActive: $("mailboxIsActive"),

    toastContainer: $("toastContainer"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

  function formatQuota(mb) {
    const quota = Number(mb || 0);
    if (quota >= 1024) {
      return `${(quota / 1024).toFixed(1)} GB`;
    }
    return `${quota} MB`;
  }

  function getDomainNameById(id) {
    const domain = state.domains.find((item) => Number(item.id) === Number(id));
    return domain?.name || "Sem domínio";
  }

  function getDefaultDomainId() {
    if (state.preferredDomainId && state.domains.some((d) => Number(d.id) === Number(state.preferredDomainId))) {
      return state.preferredDomainId;
    }

    const primary = state.domains.find((item) => item.is_primary);
    if (primary) return Number(primary.id);

    return state.domains[0]?.id || "";
  }

  function setModalMessage(message, type = "info") {
    if (!elements.modalAlert) return;
    elements.modalAlert.textContent = message || "";
    elements.modalAlert.className = `form-message ${type}`.trim();
    elements.modalAlert.style.display = message ? "block" : "none";
  }

  function clearModalMessage() {
    setModalMessage("", "info");
  }

  function showToast(message, type = "info", title = "") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    const iconMap = {
      info: "fa-circle-info",
      success: "fa-circle-check",
      error: "fa-circle-exclamation"
    };

    const titleMap = {
      info: "Atualização",
      success: "Sucesso",
      error: "Erro"
    };

    toast.innerHTML = `
      <i class="fa-solid ${iconMap[type] || iconMap.info}"></i>
      <div>
        <strong>${title || titleMap[type] || "Aviso"}</strong>
        <p>${message}</p>
      </div>
      <button type="button" aria-label="Fechar">
        <i class="fa-solid fa-xmark"></i>
      </button>
    `;

    toast.querySelector("button").addEventListener("click", () => {
      toast.remove();
    });

    elements.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
  }

  function setSaveLoading(isLoading) {
    if (!elements.saveBtn) return;

    elements.saveBtn.disabled = isLoading;
    elements.saveBtn.innerHTML = isLoading
      ? `<span class="loading-spinner"></span> Salvando`
      : state.editingId
        ? `Salvar alterações`
        : `Salvar caixa`;
  }

  function openModal() {
    clearModalMessage();
    elements.modalOverlay?.classList.add("active");
    elements.modal?.classList.add("active");
    elements.modal?.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    setTimeout(() => {
      if (elements.localPart) elements.localPart.focus();
    }, 30);
  }

  function closeModal() {
    elements.modalOverlay?.classList.remove("active");
    elements.modal?.classList.remove("active");
    elements.modal?.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function resetForm() {
    state.editingId = null;
    clearModalMessage();

    if (elements.form) elements.form.reset();
    if (elements.modalTitle) elements.modalTitle.textContent = "Nova caixa de e-mail";
    if (elements.modalSubtitle) elements.modalSubtitle.textContent = "Crie uma nova conta vinculada a um domínio cadastrado.";
    if (elements.quotaMb) elements.quotaMb.value = "2048";
    if (elements.isActive) elements.isActive.checked = true;

    renderDomainOptions(getDefaultDomainId());
    setSaveLoading(false);
  }

  function enterEditMode(mailbox) {
    state.editingId = Number(mailbox.id);
    clearModalMessage();

    if (elements.modalTitle) elements.modalTitle.textContent = "Editar caixa de e-mail";
    if (elements.modalSubtitle) elements.modalSubtitle.textContent = `Atualize os dados de ${mailbox.email}.`;
    renderDomainOptions(mailbox.dominio_id);

    elements.localPart.value = mailbox.local_part || "";
    elements.displayName.value = mailbox.display_name || "";
    elements.password.value = "";
    elements.confirmPassword.value = "";
    elements.quotaMb.value = String(mailbox.quota_mb || 2048);
    elements.isActive.checked = Boolean(mailbox.is_active);

    setModalMessage("Preencha os campos de senha apenas se quiser alterá-la.", "info");
    setSaveLoading(false);
  }

  async function parseJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

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
      window.location.href = "/login";
      throw new Error("Sessão expirada.");
    }

    return parseJson(response);
  }

  async function mountSidebar() {
    const mount = elements.sidebarMount;
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
    renderDomainOptions(getDefaultDomainId());
    updateStats();
  }

  async function loadMailboxes(showFeedback = false) {
    const data = await api("/api/caixas-email");
    state.mailboxes = Array.isArray(data?.items) ? data.items : [];
    renderMailboxes();
    updateStats();

    if (showFeedback) {
      showToast("Lista de caixas atualizada.", "success");
    }
  }

  function renderDomainOptions(selectedId = "") {
    if (!elements.domainId) return;

    if (!state.domains.length) {
      elements.domainId.innerHTML = `<option value="">Nenhum domínio disponível</option>`;
      return;
    }

    elements.domainId.innerHTML = state.domains.map((domain) => {
      const selected = String(selectedId || "") === String(domain.id) ? "selected" : "";
      const label = domain.is_primary ? `${domain.name} (Principal)` : domain.name;
      return `<option value="${escapeHtml(domain.id)}" ${selected}>${escapeHtml(label)}</option>`;
    }).join("");
  }

  function updateStats() {
    if (elements.totalMailboxes) {
      elements.totalMailboxes.textContent = state.mailboxes.length;
    }

    if (elements.activeMailboxes) {
      elements.activeMailboxes.textContent = state.mailboxes.filter((m) => m.is_active).length;
    }

    if (elements.totalDomains) {
      elements.totalDomains.textContent = state.domains.length;
    }

    if (elements.count) {
      elements.count.textContent = `${state.mailboxes.length} caixa${state.mailboxes.length !== 1 ? "s" : ""}`;
    }
  }

  function renderMailboxes() {
    if (!elements.list) return;

    if (!state.mailboxes.length) {
      elements.list.innerHTML = `
        <div class="empty-note">
          Nenhuma caixa encontrada. Use o botão <strong>Nova caixa</strong> para criar a primeira.
        </div>
      `;
      return;
    }

    elements.list.innerHTML = state.mailboxes.map((mailbox) => {
      const activeClass = mailbox.is_active ? "active" : "inactive";
      const activeLabel = mailbox.is_active ? "Ativa" : "Inativa";

      return `
        <div class="mailbox-item">
          <div class="mailbox-top">
            <div class="mailbox-info">
              <div class="mailbox-email">
                <i class="fa-solid fa-envelope"></i>
                ${escapeHtml(mailbox.email)}
              </div>

              ${mailbox.display_name ? `
                <div class="mailbox-display">
                  ${escapeHtml(mailbox.display_name)}
                </div>
              ` : ""}

              <div class="mailbox-meta">
                <span class="status-chip ${activeClass}">${activeLabel}</span>

                <span class="meta-item">
                  <i class="fa-solid fa-globe"></i>
                  ${escapeHtml(mailbox.domain_name || getDomainNameById(mailbox.dominio_id))}
                </span>

                <span class="meta-item">
                  <i class="fa-solid fa-database"></i>
                  ${escapeHtml(formatQuota(mailbox.quota_mb || 0))}
                </span>

                <span class="meta-item">
                  <i class="fa-solid fa-clock"></i>
                  ${escapeHtml(formatDate(mailbox.updated_at || mailbox.created_at))}
                </span>
              </div>
            </div>

            <div class="mailbox-actions">
              <button type="button" class="btn-icon" data-action="edit" data-id="${mailbox.id}" title="Editar caixa">
                <i class="fa-solid fa-pen"></i>
              </button>

              <button type="button" class="btn-icon danger" data-action="delete" data-id="${mailbox.id}" data-email="${escapeHtml(mailbox.email)}" title="Excluir caixa">
                <i class="fa-solid fa-trash"></i>
              </button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    bindListActions();
  }

  function bindListActions() {
    elements.list.querySelectorAll("[data-action='edit']").forEach((button) => {
      button.addEventListener("click", () => {
        const id = Number(button.getAttribute("data-id") || 0);
        const mailbox = state.mailboxes.find((item) => Number(item.id) === id);
        if (!mailbox) return;

        enterEditMode(mailbox);
        openModal();
      });
    });

    elements.list.querySelectorAll("[data-action='delete']").forEach((button) => {
      button.addEventListener("click", async () => {
        const id = Number(button.getAttribute("data-id") || 0);
        const email = String(button.getAttribute("data-email") || "");
        await deleteMailbox(id, email);
      });
    });
  }

  function validatePasswordFields() {
    const password = String(elements.password?.value || "").trim();
    const confirmPassword = String(elements.confirmPassword?.value || "").trim();

    if (!password && !confirmPassword) return null;

    if (!password || !confirmPassword) {
      throw new Error("Preencha a senha e a confirmação.");
    }

    if (password.length < 8) {
      throw new Error("A senha precisa ter pelo menos 8 caracteres.");
    }

    if (password !== confirmPassword) {
      throw new Error("As senhas não conferem.");
    }

    return password;
  }

  function buildPayload() {
    const dominioId = Number(elements.domainId?.value || 0);
    const localPart = String(elements.localPart?.value || "").trim().toLowerCase().replace(/\s+/g, "");
    const displayName = String(elements.displayName?.value || "").trim() || null;
    const quotaMb = Number(elements.quotaMb?.value || 0);
    const password = validatePasswordFields();

    if (!dominioId) throw new Error("Selecione um domínio.");
    if (!localPart) throw new Error("Informe o nome da conta.");

    if (!/^[a-z0-9](?:[a-z0-9._-]{0,118}[a-z0-9])?$/.test(localPart)) {
      throw new Error("Use apenas letras, números, ponto, hífen ou underline.");
    }

    if (!quotaMb || quotaMb < 128 || quotaMb > 102400) {
      throw new Error("A quota deve estar entre 128 MB e 102400 MB.");
    }

    const payload = {
      dominio_id: dominioId,
      local_part: localPart,
      display_name: displayName,
      quota_mb: quotaMb,
      is_active: Boolean(elements.isActive?.checked),
    };

    if (!state.editingId && password) {
      payload.password = password;
    }

    return { payload, password };
  }

  async function createMailbox(payload) {
    return api("/api/caixas-email", {
      method: "POST",
      body: payload,
    });
  }

  async function updateMailbox(mailboxId, payload) {
    return api(`/api/caixas-email/${mailboxId}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function updateMailboxPassword(mailboxId, password) {
    return api(`/api/caixas-email/${mailboxId}/set-password`, {
      method: "POST",
      body: { password },
    });
  }

  async function deleteMailbox(mailboxId, email) {
    const confirmed = window.confirm(`Excluir permanentemente a caixa ${email}?`);
    if (!confirmed) return;

    try {
      await api(`/api/caixas-email/${mailboxId}`, {
        method: "DELETE",
      });

      if (state.editingId === mailboxId) {
        closeModal();
      }

      await loadMailboxes();
      showToast(`Caixa ${email} removida com sucesso.`, "success");
    } catch (error) {
      showToast(error.message || "Erro ao excluir caixa.", "error");
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    clearModalMessage();
    setSaveLoading(true);

    try {
      const { payload, password } = buildPayload();

      if (state.editingId) {
        const mailboxId = Number(state.editingId);
        const response = await updateMailbox(mailboxId, payload);

        if (password) {
          await updateMailboxPassword(mailboxId, password);
        }

        await loadMailboxes();
        showToast(password ? "Caixa e senha atualizadas." : (response?.message || "Caixa atualizada com sucesso."), "success");
        closeModal();
        setTimeout(resetForm, 180);
        return;
      }

      const response = await createMailbox(payload);
      await loadMailboxes();

      if (response?.generated_password) {
        showToast(`Caixa criada. Senha gerada: ${response.generated_password}`, "success", "Caixa criada");
      } else {
        showToast(response?.message || "Caixa criada com sucesso.", "success");
      }

      closeModal();
      setTimeout(resetForm, 180);
    } catch (error) {
      setModalMessage(error.message || "Erro ao salvar caixa.", "error");
    } finally {
      setSaveLoading(false);
    }
  }

  function bindEvents() {
    elements.openModalBtn?.addEventListener("click", () => {
      resetForm();
      openModal();
    });

    elements.openModalBtnInline?.addEventListener("click", () => {
      resetForm();
      openModal();
    });

    elements.closeModalBtn?.addEventListener("click", () => {
      closeModal();
      setTimeout(resetForm, 180);
    });

    elements.cancelModalBtn?.addEventListener("click", () => {
      closeModal();
      setTimeout(resetForm, 180);
    });

    elements.modalOverlay?.addEventListener("click", () => {
      closeModal();
      setTimeout(resetForm, 180);
    });

    elements.form?.addEventListener("submit", handleSubmit);

    elements.refreshBtn?.addEventListener("click", async () => {
      try {
        await loadDomains();
        await loadMailboxes(true);
      } catch (error) {
        showToast(error.message || "Erro ao atualizar.", "error");
      }
    });

    elements.backBtn?.addEventListener("click", () => {
      window.location.href = "/dominios";
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && elements.modal?.classList.contains("active")) {
        closeModal();
        setTimeout(resetForm, 180);
      }
    });
  }

  async function init() {
    try {
      await mountSidebar();
      await loadMe();
      await loadDomains();
      await loadMailboxes();
      bindEvents();
    } catch (error) {
      console.error(error);
      showToast(error.message || "Erro ao inicializar a página.", "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
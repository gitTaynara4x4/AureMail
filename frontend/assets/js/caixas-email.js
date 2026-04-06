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

  const elements = {
    form: $("mailboxForm"),
    formTitle: $("mailboxFormTitle"),
    domainId: $("mailboxDomainId"),
    localPart: $("mailboxLocalPart"),
    displayName: $("mailboxDisplayName"),
    password: $("mailboxPassword"),
    confirmPassword: $("mailboxConfirmPassword"),
    quotaMb: $("mailboxQuotaMb"),
    isActive: $("mailboxIsActive"),
    submitBtn: $("createMailboxBtn"),
    cancelEditBtn: $("cancelMailboxEditBtn"),
    messageBox: $("mailboxFormMessage"),
    list: $("mailboxList"),
    count: $("mailboxesCount"),
    refreshBtn: $("refreshMailboxesBtn"),
    backBtn: $("backToDomainsBtn"),
    sidebarMount: $("sidebarMount"),
  };

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

  function normalizeDisplayName(value) {
    const text = String(value || "").trim();
    return text || null;
  }

  function humanizeMailboxStatus(isActive) {
    return isActive ? "ATIVA" : "INATIVA";
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
    if (!elements.messageBox) return;
    elements.messageBox.textContent = message || "";
    elements.messageBox.className = `form-message ${type}`.trim();
    elements.messageBox.style.display = message ? "block" : "none";
  }

  function clearMessage() {
    setMessage("", "info");
  }

  function setLoading(isLoading) {
    if (!elements.submitBtn) return;
    elements.submitBtn.disabled = isLoading;
    elements.submitBtn.textContent = isLoading
      ? (state.editingId ? "Salvando alterações..." : "Criando caixa...")
      : (state.editingId ? "Salvar alterações" : "Salvar caixa de e-mail");
  }

  async function parseJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const errorMessage =
        payload?.detail ||
        payload?.message ||
        `Erro ${response.status}`;
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
    renderDomainOptions();
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
    if (!elements.domainId) return;

    if (!state.domains.length) {
      elements.domainId.innerHTML = `<option value="">Nenhum domínio ativo disponível</option>`;
      elements.domainId.disabled = true;
      return;
    }

    elements.domainId.disabled = false;
    elements.domainId.innerHTML = state.domains
      .map((domain) => {
        const selected = String(selectedId || "") === String(domain.id) ? "selected" : "";
        const label = domain.is_primary ? `${domain.name} (principal)` : domain.name;
        return `<option value="${escapeHtml(domain.id)}" ${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

  function renderMailboxes() {
    if (!elements.list || !elements.count) return;

    elements.count.textContent = `${state.mailboxes.length} ${state.mailboxes.length === 1 ? "item" : "itens"}`;

    if (!state.mailboxes.length) {
      elements.list.innerHTML = `<div class="empty-note">Nenhuma caixa cadastrada ainda. Crie a primeira conta profissional da empresa.</div>`;
      return;
    }

    elements.list.innerHTML = state.mailboxes
      .map((mailbox) => {
        const statusLabel = humanizeMailboxStatus(mailbox.is_active);
        const displayName = mailbox.display_name ? `${escapeHtml(mailbox.display_name)} • ` : "";
        const domainName = mailbox.domain_name || "Sem domínio";
        const updatedAt = formatDate(mailbox.updated_at || mailbox.created_at);

        return `
          <article class="domain-item">
            <div class="domain-item__main">
              <div class="domain-item__top">
                <div class="domain-item__title-wrap">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
                  <h4>${escapeHtml(mailbox.email)}</h4>
                </div>
                <div class="domain-item__actions">
                  <button type="button" class="icon-btn" data-action="edit" data-id="${mailbox.id}" title="Editar">
                    ✎
                  </button>
                  <button type="button" class="icon-btn" data-action="delete" data-id="${mailbox.id}" data-email="${escapeHtml(mailbox.email)}" title="Excluir">
                    🗑
                  </button>
                </div>
              </div>

              <div class="domain-item__meta">
                <span class="status-chip ${mailbox.is_active ? "is-active" : "is-inactive"}">${statusLabel}</span>
                <span>${displayName}Domínio: ${escapeHtml(domainName)} • Quota: ${escapeHtml(formatQuota(mailbox.quota_mb))}</span>
              </div>

              <div class="domain-item__date">
                Atualizado em ${escapeHtml(updatedAt)}
              </div>
            </div>
          </article>
        `;
      })
      .join("");

    bindListActions();
  }

  function bindListActions() {
    elements.list.querySelectorAll("[data-action='edit']").forEach((button) => {
      button.addEventListener("click", () => {
        const id = Number(button.getAttribute("data-id") || 0);
        const mailbox = state.mailboxes.find((item) => Number(item.id) === id);
        if (mailbox) {
          enterEditMode(mailbox);
        }
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

  function resetForm(clearFeedback = false) {
    state.editingId = null;

    if (elements.form) elements.form.reset();
    if (elements.formTitle) elements.formTitle.textContent = "Criar Nova Caixa";
    if (elements.submitBtn) elements.submitBtn.textContent = "Salvar caixa de e-mail";
    if (elements.cancelEditBtn) elements.cancelEditBtn.style.display = "none";

    if (elements.quotaMb) elements.quotaMb.value = "2048";
    if (elements.isActive) elements.isActive.checked = true;
    if (elements.password) elements.password.value = "";
    if (elements.confirmPassword) elements.confirmPassword.value = "";

    renderDomainOptions();

    if (clearFeedback) {
      clearMessage();
    }
  }

  function enterEditMode(mailbox) {
    state.editingId = Number(mailbox.id);

    if (elements.formTitle) elements.formTitle.textContent = "Editar Caixa";
    if (elements.submitBtn) elements.submitBtn.textContent = "Salvar alterações";
    if (elements.cancelEditBtn) elements.cancelEditBtn.style.display = "block";

    renderDomainOptions(mailbox.dominio_id);
    elements.localPart.value = mailbox.local_part || "";
    elements.displayName.value = mailbox.display_name || "";
    elements.password.value = "";
    elements.confirmPassword.value = "";
    elements.quotaMb.value = String(mailbox.quota_mb || 2048);
    elements.isActive.checked = Boolean(mailbox.is_active);

    setMessage(
      `Editando ${mailbox.email}. Se quiser trocar a senha, preencha os dois campos de senha.`,
      "info"
    );

    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function validatePasswordFields() {
    const password = String(elements.password?.value || "").trim();
    const confirmPassword = String(elements.confirmPassword?.value || "").trim();

    if (!password && !confirmPassword) {
      return null;
    }

    if (!password || !confirmPassword) {
      throw new Error("Preencha a senha e a confirmação da senha.");
    }

    if (password.length < 8) {
      throw new Error("A senha da caixa precisa ter pelo menos 8 caracteres.");
    }

    if (password !== confirmPassword) {
      throw new Error("A confirmação da senha não confere.");
    }

    return password;
  }

  function buildPayload() {
    const dominioId = Number(elements.domainId?.value || 0);
    const localPart = normalizeLocalPart(elements.localPart?.value || "");
    const displayName = normalizeDisplayName(elements.displayName?.value || "");
    const quotaMb = Number(elements.quotaMb?.value || 0);
    const password = validatePasswordFields();

    if (!dominioId) {
      throw new Error("Selecione um domínio.");
    }

    if (!localPart) {
      throw new Error("Informe o nome da conta antes do @.");
    }

    if (!/^[a-z0-9](?:[a-z0-9._-]{0,118}[a-z0-9])?$/.test(localPart)) {
      throw new Error("Use apenas letras, números, ponto, hífen ou underline no nome da conta.");
    }

    if (!quotaMb || quotaMb < 128 || quotaMb > 102400) {
      throw new Error("Informe uma quota válida entre 128 MB e 102400 MB.");
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
    const confirmed = window.confirm(`Tem certeza que deseja excluir a caixa ${email}?`);
    if (!confirmed) return;

    try {
      await api(`/api/caixas-email/${mailboxId}`, {
        method: "DELETE",
      });

      if (state.editingId === mailboxId) {
        resetForm(false);
      }

      await loadMailboxes();
      setMessage(`Caixa ${email} removida com sucesso.`, "success");
    } catch (error) {
      console.error(error);
      setMessage(error.message || "Não foi possível excluir a caixa.", "error");
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    clearMessage();
    setLoading(true);

    try {
      const { payload, password } = buildPayload();

      if (state.editingId) {
        const mailboxId = Number(state.editingId);
        const response = await updateMailbox(mailboxId, payload);

        if (password) {
          await updateMailboxPassword(mailboxId, password);
        }

        await loadMailboxes();
        setMessage(
          password
            ? "Caixa atualizada com sucesso e senha alterada."
            : (response?.message || "Caixa atualizada com sucesso."),
          "success"
        );
        resetForm(false);
        return;
      }

      const response = await createMailbox(payload);
      await loadMailboxes();

      if (response?.generated_password) {
        setMessage(
          `Caixa criada com sucesso. Senha gerada: ${response.generated_password}`,
          "success"
        );
      } else {
        setMessage(response?.message || "Caixa criada com sucesso.", "success");
      }

      resetForm(false);
    } catch (error) {
      console.error(error);
      setMessage(error.message || "Não foi possível salvar a caixa.", "error");
    } finally {
      setLoading(false);
    }
  }

  async function init() {
    try {
      await mountSidebar();
      await loadMe();
      await loadDomains();
      await loadMailboxes();
      resetForm(true);
    } catch (error) {
      console.error(error);
      setMessage(error.message || "Erro ao carregar a tela de caixas.", "error");
    }
  }

  if (elements.form) {
    elements.form.addEventListener("submit", handleSubmit);
  }

  if (elements.cancelEditBtn) {
    elements.cancelEditBtn.addEventListener("click", () => {
      resetForm(true);
    });
  }

  if (elements.refreshBtn) {
    elements.refreshBtn.addEventListener("click", async () => {
      try {
        clearMessage();
        await loadDomains();
        await loadMailboxes(true);
      } catch (error) {
        console.error(error);
        setMessage(error.message || "Não foi possível atualizar as caixas.", "error");
      }
    });
  }

  if (elements.backBtn) {
    elements.backBtn.addEventListener("click", () => {
      window.location.href = "/dominios";
    });
  }

  init();
})();
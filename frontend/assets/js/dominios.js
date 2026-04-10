(function () {
  const state = {
    me: null,
    domains: [],
    editingId: null,
    selectedDomainId: null,
    selectedDomainSetup: null,
    selectedDomainVerification: null,
    selectedProviderId: null,
  };

  const PROVIDERS = [
    {
      id: "registrobr",
      label: "Registro.br",
      type: "exact",
      rootMode: "blank",
      accessTitle: "Como abrir no Registro.br",
      accessSteps: [
        "Entre no painel do domínio.",
        "Abra a área de Zona DNS / Configurar Zona DNS.",
        "Crie os registros exatamente como o AureMail mostrar.",
      ],
      rootHint: "No Registro.br, quando o host for a raiz do domínio, deixe o campo Nome vazio.",
      txtValueLabel: "Texto",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Nome do servidor de e-mail",
      extraNote: "",
    },
    {
      id: "hostinger",
      label: "Hostinger",
      type: "exact",
      rootMode: "@",
      accessTitle: "Como abrir na Hostinger",
      accessSteps: [
        "Entre no hPanel.",
        "Abra o domínio e vá para DNS / Nameservers ou DNS Zone Editor.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na Hostinger, a raiz do domínio normalmente usa @. Em alguns casos também pode aceitar vazio.",
      txtValueLabel: "Conteúdo",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Aponta para",
      extraNote: "Se o painel já tiver TTL padrão e você não quiser mexer, pode manter o valor padrão.",
    },
    {
      id: "cloudflare",
      label: "Cloudflare Registrar",
      type: "exact",
      rootMode: "@",
      accessTitle: "Como abrir na Cloudflare",
      accessSteps: [
        "Abra o domínio na Cloudflare.",
        "Entre em DNS Records.",
        "Clique em Add record e crie os registros um por um.",
      ],
      rootHint: "Na Cloudflare, a raiz do domínio normalmente usa @.",
      txtValueLabel: "Content",
      mxPriorityLabel: "Priority",
      mxServerLabel: "Mail server",
      extraNote: "Se houver qualquer host auxiliar do seu ambiente central, deixe como DNS only. Para os registros exibidos pelo AureMail, apenas replique exatamente os valores mostrados.",
    },
    {
      id: "godaddy",
      label: "GoDaddy",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na GoDaddy",
      accessSteps: [
        "Entre no domínio.",
        "Abra a área de DNS Management.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na GoDaddy, a raiz do domínio normalmente usa @.",
      txtValueLabel: "Valor",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Servidor",
      extraNote: "",
    },
    {
      id: "locaweb",
      label: "Locaweb",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na Locaweb",
      accessSteps: [
        "Entre no painel da hospedagem ou domínio.",
        "Abra a área de DNS / Zona DNS.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na Locaweb, a raiz do domínio costuma ser representada por @.",
      txtValueLabel: "Texto",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Servidor",
      extraNote: "",
    },
    {
      id: "kinghost",
      label: "KingHost",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na KingHost",
      accessSteps: [
        "Entre no painel da KingHost.",
        "Abra o Editor de DNS.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na KingHost, a raiz do domínio costuma ser representada por @.",
      txtValueLabel: "Conteúdo",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Servidor",
      extraNote: "",
    },
    {
      id: "hostgator",
      label: "HostGator",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na HostGator",
      accessSteps: [
        "Entre no painel da HostGator.",
        "Abra a área de Zona DNS.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na HostGator, a raiz do domínio costuma ser representada por @.",
      txtValueLabel: "Conteúdo",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Servidor",
      extraNote: "",
    },
    {
      id: "namecheap",
      label: "Namecheap",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na Namecheap",
      accessSteps: [
        "Abra o painel do domínio.",
        "Entre em Advanced DNS ou DNS Records.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na Namecheap, a raiz do domínio normalmente usa @.",
      txtValueLabel: "Value",
      mxPriorityLabel: "Priority",
      mxServerLabel: "Mail server",
      extraNote: "",
    },
    {
      id: "ionos",
      label: "IONOS",
      type: "generic",
      rootMode: "@",
      accessTitle: "Como abrir na IONOS",
      accessSteps: [
        "Entre no painel da IONOS.",
        "Abra a área de DNS.",
        "Adicione os registros manualmente.",
      ],
      rootHint: "Na IONOS, a raiz do domínio normalmente usa @.",
      txtValueLabel: "Valor",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Servidor",
      extraNote: "",
    },
  ];

  const HELP_TOPICS = {
    status: {
      title: "O que significa o status do domínio?",
      html: `
        <div class="help-block">
          <h4>Pendente (aguardando DNS)</h4>
          <p>
            Use esse status quando o domínio acabou de ser cadastrado no AureMail,
            mas o cliente ainda <strong>não configurou tudo no DNS</strong>.
          </p>
          <ul>
            <li>O domínio já existe no sistema.</li>
            <li>Os registros como <strong>MX, SPF e DMARC</strong> ainda podem estar faltando.</li>
            <li>É o status mais comum no começo.</li>
          </ul>
        </div>

        <div class="help-block">
          <h4>Ativo</h4>
          <p>
            Use quando o domínio já está pronto para uso no ambiente de e-mail.
          </p>
          <ul>
            <li>Os registros obrigatórios já foram encontrados.</li>
            <li>O domínio está liberado para seguir para caixas de e-mail.</li>
            <li>É o status de domínio operacional.</li>
          </ul>
        </div>

        <div class="help-block">
          <h4>Inativo</h4>
          <p>
            Use quando o domínio não deve ser usado no momento.
          </p>
          <ul>
            <li>Você pode deixar salvo no sistema.</li>
            <li>Mas ele fica fora do fluxo principal.</li>
            <li>Serve para domínio pausado, antigo ou temporariamente desativado.</li>
          </ul>
        </div>

        <div class="help-highlight info">
          Regra prática: se você acabou de cadastrar e ainda vai configurar DNS,
          deixe como <strong>Pendente</strong>.
        </div>
      `,
    },
    primary: {
      title: "O que é domínio principal?",
      html: `
        <div class="help-block">
          <h4>Domínio principal</h4>
          <p>
            É o domínio padrão da empresa dentro do AureMail.
          </p>
          <ul>
            <li>Ele aparece como o domínio principal do ambiente.</li>
            <li>Pode ser usado como padrão quando o sistema precisar escolher um domínio.</li>
            <li>A empresa pode ter vários domínios, mas normalmente um deles fica como principal.</li>
          </ul>
        </div>

        <div class="help-highlight warning">
          Isso <strong>não significa</strong> que os outros domínios deixam de funcionar.
          Significa apenas que esse será o domínio principal do ambiente.
        </div>
      `,
    },
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

  function normalizeDomainInput(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("/")[0]
      .split("?")[0]
      .split("#")[0]
      .replace(/^\.+|\.+$/g, "");
  }

  function humanizeStatus(status) {
    const normalized = String(status || "").trim().toLowerCase();
    if (normalized === "active") return "Ativo";
    if (normalized === "inactive") return "Inativo";
    if (normalized === "error") return "Erro";
    return "Pendente";
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

  function setFormMessage(message, type = "info") {
    const box = $("domainFormMessage");
    if (!box) return;

    box.textContent = message || "";
    box.className = `form-message ${type}`.trim();
    box.style.display = message ? "block" : "none";
  }

  function clearFormMessage() {
    setFormMessage("", "info");
  }

  function setPageMessage(message, type = "info") {
    const box = $("pageFeedback");
    if (!box) return;

    box.textContent = message || "";
    box.className = `page-feedback ${type}`.trim();
    box.style.display = message ? "block" : "none";
  }

  function clearPageMessage() {
    setPageMessage("", "info");
  }

  function showToast(message, tone = "default") {
    const toast = document.createElement("div");
    toast.textContent = message;

    const isDark = document.documentElement.getAttribute("data-theme") === "dark";

    const colors = {
      default: isDark
        ? { bg: "#2f2f2f", text: "#ececec", border: "rgba(255,255,255,0.1)" }
        : { bg: "#111827", text: "#ffffff", border: "transparent" },

      success: isDark
        ? { bg: "#171717", text: "#10a37f", border: "rgba(16, 163, 127, 0.3)" }
        : { bg: "#065f46", text: "#ffffff", border: "transparent" },

      danger: isDark
        ? { bg: "#171717", text: "#ef4444", border: "rgba(239, 68, 68, 0.3)" }
        : { bg: "#7f1d1d", text: "#ffffff", border: "transparent" }
    };

    const palette = colors[tone] || colors.default;

    Object.assign(toast.style, {
      position: "fixed",
      top: "20px",
      right: "20px",
      zIndex: "9999",
      padding: "14px 16px",
      borderRadius: "12px",
      background: palette.bg,
      color: palette.text,
      border: `1px solid ${palette.border}`,
      fontFamily: "Inter, sans-serif",
      fontSize: "14px",
      fontWeight: "600",
      boxShadow: isDark
        ? "0 20px 40px rgba(0,0,0,0.45)"
        : "0 10px 25px rgba(0,0,0,0.12)",
      opacity: "0",
      transform: "translateY(-8px)",
      transition: "all .22s ease"
    });

    document.body.appendChild(toast);

    requestAnimationFrame(() => {
      toast.style.opacity = "1";
      toast.style.transform = "translateY(0)";
    });

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-8px)";
      setTimeout(() => toast.remove(), 220);
    }, 2200);
  }

  function openHelp(topic) {
    const data = HELP_TOPICS[topic];
    if (!data) return;

    $("helpTitle").textContent = data.title;
    $("helpBody").innerHTML = data.html;
    $("helpOverlay").classList.add("active");
    $("helpDrawer").classList.add("active");
    $("helpDrawer").setAttribute("aria-hidden", "false");
  }

  function closeHelp() {
    $("helpOverlay").classList.remove("active");
    $("helpDrawer").classList.remove("active");
    $("helpDrawer").setAttribute("aria-hidden", "true");
  }

  function openDomainModal() {
    resetCreateForm();
    $("domainModalOverlay")?.classList.add("active");
    $("domainModal")?.classList.add("active");
    $("domainModal")?.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    setTimeout(() => {
      $("domainName")?.focus();
    }, 30);
  }

  function closeDomainModal() {
    $("domainModalOverlay")?.classList.remove("active");
    $("domainModal")?.classList.remove("active");
    $("domainModal")?.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function openGuideModal() {
    if (!state.selectedDomainSetup) {
      setPageMessage("Selecione um domínio primeiro.", "info");
      return;
    }

    renderGuideModalContent();

    $("guideModalOverlay")?.classList.add("active");
    $("guideModal")?.classList.add("active");
    $("guideModal")?.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeGuideModal() {
    $("guideModalOverlay")?.classList.remove("active");
    $("guideModal")?.classList.remove("active");
    $("guideModal")?.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  async function parseJson(response) {
    let payload = null;
    let rawText = "";

    try {
      rawText = await response.text();
    } catch (_) {
      rawText = "";
    }

    try {
      payload = rawText ? JSON.parse(rawText) : null;
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      let errorMessage =
        payload?.detail ||
        payload?.message ||
        (rawText && !/^</.test(rawText.trim()) ? rawText : "") ||
        `Erro ${response.status}`;

      if (response.status === 502 && /service is not reachable/i.test(rawText)) {
        errorMessage = "O serviço do app não está acessível no momento.";
      }

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

  async function loadDomains(showFeedback = false) {
    const data = await api("/api/dominios");
    state.domains = Array.isArray(data?.items) ? data.items : [];

    if (!state.selectedDomainId || !state.domains.some((item) => Number(item.id) === Number(state.selectedDomainId))) {
      state.selectedDomainId = state.domains[0]?.id || null;
    }

    renderDomains();

    if (state.selectedDomainId) {
      await loadSelectedDomainSetup();
    } else {
      state.selectedDomainSetup = null;
      state.selectedDomainVerification = null;
      state.selectedProviderId = null;
      renderEnvSummary();
      renderSelectedDomainPanel();
    }

    if (showFeedback) {
      setPageMessage("Lista de domínios atualizada.", "success");
    }
  }

  async function loadSelectedDomainSetup() {
    if (!state.selectedDomainId) {
      state.selectedDomainSetup = null;
      state.selectedDomainVerification = null;
      state.selectedProviderId = null;
      renderEnvSummary();
      renderSelectedDomainPanel();
      return;
    }

    state.selectedDomainSetup = await api(`/api/dominios/${state.selectedDomainId}/dns-setup`);
    state.selectedDomainVerification = null;
    state.selectedProviderId = null;
    renderEnvSummary();
    renderSelectedDomainPanel();

    if ($("guideModal")?.classList.contains("active")) {
      renderGuideModalContent();
    }
  }

  function renderEnvSummary() {
    const generated = state.selectedDomainSetup?.generated || {};

    const setText = (id, value, fallback = "Não configurado") => {
      const el = $(id);
      if (!el) return;
      el.textContent = value || fallback;
    };

    setText("envAppSubdomain", generated.app_subdomain);
    setText("envMailSubdomain", generated.mail_subdomain);
    setText("envPublicIp", generated.public_ip || "AUREMAIL_PUBLIC_IP não configurado");
    setText("envDkimSelector", generated.dkim_selector);
  }

  function filterClientWarnings(warnings) {
    return (Array.isArray(warnings) ? warnings : []).filter((warning) => {
      const text = String(warning || "").toUpperCase();
      if (!text) return false;
      if (text.includes("AUREMAIL_DKIM_PUBLIC_KEY")) return false;
      if (text.includes("DKIM")) return false;
      return true;
    });
  }

  function shouldHideRecord(record) {
    const key = String(record?.key || "").trim().toLowerCase();
    return key === "dkim";
  }

  function getVisibleRecords(records) {
    return (Array.isArray(records) ? records : []).filter((record) => !shouldHideRecord(record));
  }

  function renderDomains() {
    const list = $("domainList");
    const count = $("domainsCount");

    if (count) {
      const total = state.domains.length;
      count.textContent = `${total} ${total === 1 ? "item" : "itens"}`;
    }

    if (!list) return;

    if (!state.domains.length) {
      list.innerHTML = `
        <div class="empty-note">
          Nenhum domínio cadastrado ainda. Use o botão <strong>Novo domínio</strong> para adicionar o primeiro.
        </div>
      `;
      return;
    }

    list.innerHTML = state.domains.map((item) => renderDomainItem(item)).join("");
  }

  function renderDomainItem(item) {
    const isEditing = state.editingId === item.id;
    const isSelected = Number(state.selectedDomainId) === Number(item.id);
    const normalizedStatus = String(item.status || "").trim().toLowerCase();
    const statusClass =
      normalizedStatus === "active"
        ? "active"
        : normalizedStatus === "inactive"
          ? "inactive"
          : "pending";

    if (isEditing) {
      return `
        <div class="domain-item edit-inline" data-domain-id="${item.id}">
          <form class="domain-edit-form" data-domain-id="${item.id}">
            <div class="field">
              <label for="edit-name-${item.id}">Nome do domínio</label>
              <input type="text" id="edit-name-${item.id}" name="name" value="${escapeHtml(item.name)}" maxlength="255" required />
            </div>

            <div class="field">
              <label for="edit-status-${item.id}">Status</label>
              <div class="select-wrapper">
                <select id="edit-status-${item.id}" name="status">
                  <option value="pending" ${normalizedStatus === "pending" ? "selected" : ""}>Pendente</option>
                  <option value="active" ${normalizedStatus === "active" ? "selected" : ""}>Ativo</option>
                  <option value="inactive" ${normalizedStatus === "inactive" ? "selected" : ""}>Inativo</option>
                </select>
                <svg class="select-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="2">
                  <path d="m6 9 6 6 6-6"></path>
                </svg>
              </div>
            </div>

            <label class="checkbox-row" for="edit-primary-${item.id}">
              <input type="checkbox" id="edit-primary-${item.id}" name="is_primary" ${item.is_primary ? "checked" : ""} />
              <span class="checkbox-box">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white"
                  stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </span>
              <span class="checkbox-text">Definir como domínio principal</span>
            </label>

            <div class="edit-actions">
              <button type="submit" class="btn btn-primary">Salvar alterações</button>
              <button type="button" class="btn btn-secondary" data-action="cancel-edit" data-id="${item.id}">
                Cancelar
              </button>
            </div>
          </form>
        </div>
      `;
    }

    return `
      <div class="domain-item ${isSelected ? "selected" : ""}" data-domain-id="${item.id}">
        <div class="domain-item__top">
          <div class="domain-info">
            <h4>
              ${escapeHtml(item.name)}
              ${item.is_primary ? `
                <svg class="primary-star" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
              ` : ""}
            </h4>

            <div class="domain-meta">
              <span class="status-chip ${statusClass}">${escapeHtml(humanizeStatus(item.status))}</span>
              <span>Atualizado em ${escapeHtml(formatDate(item.updated_at || item.created_at))}</span>
            </div>
          </div>

          <div class="domain-actions">
            <button type="button" class="btn btn-secondary btn-small" data-action="select" data-id="${item.id}">
              Selecionar
            </button>

            ${!item.is_primary ? `
              <button type="button" class="btn-icon" data-action="make-primary" data-id="${item.id}" title="Definir principal">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
              </button>
            ` : ""}

            <button type="button" class="btn-icon" data-action="edit" data-id="${item.id}" title="Editar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path>
                <path d="m15 5 4 4"></path>
              </svg>
            </button>

            <button type="button" class="btn-icon danger" data-action="delete" data-id="${item.id}" title="Excluir">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 6h18"></path>
                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 1 2 2 2v2"></path>
              </svg>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function resetCreateForm() {
    const form = $("domainForm");
    if (!form) return;
    form.reset();
    $("domainStatus").value = "pending";
    $("domainPrimary").checked = false;
    clearFormMessage();
  }

  function verificationEntryFor(key) {
    return state.selectedDomainVerification?.records?.find((item) => item.key === key) || null;
  }

  function renderVerificationChip(entry) {
    if (!entry) return `<span class="verify-chip neutral">não verificado</span>`;
    if (entry.status === "ok") return `<span class="verify-chip ok">ok</span>`;
    if (entry.status === "error") return `<span class="verify-chip error">erro</span>`;
    if (entry.status === "pending_config") return `<span class="verify-chip warning">configurar</span>`;
    return `<span class="verify-chip neutral">pendente</span>`;
  }

  function renderFoundValues(entry) {
    if (!entry) return "";

    const found = Array.isArray(entry.found_values) ? entry.found_values : [];
    if (!found.length && !entry.message) return "";

    const content = found.length
      ? `Encontrado: ${found.join(" | ")}`
      : entry.message;

    return `<div class="verify-found">${escapeHtml(content)}</div>`;
  }

  function getProvider() {
    return PROVIDERS.find((item) => item.id === state.selectedProviderId) || null;
  }

  function providerHostDisplay(host, provider) {
    const normalized = String(host || "").trim();

    if (!normalized || normalized === "@") {
      return provider?.rootMode === "blank" ? "(deixe vazio)" : "@";
    }

    return normalized;
  }

  function providerHostCopyValue(host, provider) {
    const normalized = String(host || "").trim();

    if (!normalized || normalized === "@") {
      return provider?.rootMode === "blank" ? "" : "@";
    }

    return normalized;
  }

  function parseMxValue(value) {
    const raw = String(value || "").trim();
    const match = raw.match(/^(\d+)\s+(.+)$/);

    if (match) {
      return {
        priority: match[1],
        server: match[2],
      };
    }

    return {
      priority: "10",
      server: raw,
    };
  }

  function getRecordValue(record) {
    return String(record?.copy_value || record?.display_value || "").trim();
  }

  function renderProviderGuide(records) {
    const provider = getProvider();

    if (!provider) {
      return `
        <div class="provider-intro-empty">
          Escolha um provedor acima para abrir o passo a passo exato daquele painel.
        </div>
      `;
    }

    return `
      <div class="provider-guide">
        <div class="provider-guide__head">
          <h4>${escapeHtml(provider.label)}</h4>
          <p>${provider.type === "exact" ? "Guia detalhado" : "Guia inicial"} para esse provedor.</p>
        </div>

        <div class="provider-guide__body">
          <div class="provider-quick-tip">
            <strong>${escapeHtml(provider.accessTitle)}</strong><br />
            ${provider.accessSteps.map((item, index) => `${index + 1}. ${escapeHtml(item)}`).join("<br />")}
          </div>

          <div class="provider-quick-tip">
            <strong>Raiz do domínio:</strong> ${escapeHtml(provider.rootHint)}
          </div>

          ${provider.extraNote ? `
            <div class="provider-warning">
              <strong>Atenção:</strong> ${escapeHtml(provider.extraNote)}
            </div>
          ` : ""}

          ${records.map((record, index) => renderProviderRecord(record, provider, index + 1)).join("")}

          <div class="provider-summary">
            ${records.map((record) => renderProviderSummaryLine(record, provider)).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderProviderRecord(record, provider, stepNumber) {
    const type = String(record?.type || "").trim().toUpperCase();
    const value = getRecordValue(record);
    const hostDisplay = providerHostDisplay(record?.host || "", provider);
    const hostCopy = providerHostCopyValue(record?.host || "", provider);
    const label = record?.label || record?.key || "Registro";
    const verification = verificationEntryFor(record.key);

    if (type === "MX") {
      const mx = parseMxValue(value);

      return `
        <article class="provider-record">
          <div class="provider-record__top">
            <span class="provider-record__step">Passo ${stepNumber}</span>
            <span class="provider-record__badge">MX</span>
          </div>

          <div class="provider-record__title">
            <h5>${escapeHtml(label)}</h5>
            <p>Crie este registro no painel DNS do provedor.</p>
          </div>

          <div class="provider-fields">
            <div class="provider-field">
              <label>Tipo</label>
              <code>MX</code>
            </div>
            <div class="provider-field">
              <label>Nome</label>
              <code>${escapeHtml(hostDisplay)}</code>
            </div>
            <div class="provider-field">
              <label>${escapeHtml(provider.mxPriorityLabel)}</label>
              <code>${escapeHtml(mx.priority)}</code>
            </div>
            <div class="provider-field">
              <label>${escapeHtml(provider.mxServerLabel)}</label>
              <code>${escapeHtml(mx.server)}</code>
            </div>
          </div>

          <div class="provider-copy-row">
            <button type="button" class="btn btn-secondary btn-small" data-copy="${escapeHtml(hostCopy)}">
              Copiar nome
            </button>
            <button type="button" class="btn btn-secondary btn-small" data-copy="${escapeHtml(mx.server)}">
              Copiar servidor
            </button>
          </div>

          ${renderFoundValues(verification)}
          <div>${renderVerificationChip(verification)}</div>
        </article>
      `;
    }

    return `
      <article class="provider-record">
        <div class="provider-record__top">
          <span class="provider-record__step">Passo ${stepNumber}</span>
          <span class="provider-record__badge">${escapeHtml(type || "-")}</span>
        </div>

        <div class="provider-record__title">
          <h5>${escapeHtml(label)}</h5>
          <p>Crie este registro no painel DNS do provedor.</p>
        </div>

        <div class="provider-fields">
          <div class="provider-field">
            <label>Tipo</label>
            <code>${escapeHtml(type)}</code>
          </div>
          <div class="provider-field">
            <label>Nome</label>
            <code>${escapeHtml(hostDisplay)}</code>
          </div>
          <div class="provider-field provider-field--full">
            <label>${escapeHtml(provider.txtValueLabel)}</label>
            <code>${escapeHtml(value)}</code>
          </div>
        </div>

        <div class="provider-copy-row">
          <button type="button" class="btn btn-secondary btn-small" data-copy="${escapeHtml(hostCopy)}">
            Copiar nome
          </button>
          <button type="button" class="btn btn-secondary btn-small" data-copy="${escapeHtml(value)}">
            Copiar valor
          </button>
        </div>

        ${renderFoundValues(verification)}
        <div>${renderVerificationChip(verification)}</div>
      </article>
    `;
  }

  function renderProviderSummaryLine(record, provider) {
    const type = String(record?.type || "").trim().toUpperCase();
    const value = getRecordValue(record);
    const hostDisplay = providerHostDisplay(record?.host || "", provider);

    if (type === "MX") {
      const mx = parseMxValue(value);
      return `
        <div class="provider-summary-line">
          <strong>MX</strong> | nome <strong>${escapeHtml(hostDisplay)}</strong> | ${escapeHtml(provider.mxPriorityLabel.toLowerCase())} <strong>${escapeHtml(mx.priority)}</strong> | ${escapeHtml(provider.mxServerLabel.toLowerCase())} <strong>${escapeHtml(mx.server)}</strong>
        </div>
      `;
    }

    return `
      <div class="provider-summary-line">
        <strong>${escapeHtml(type)}</strong> | nome <strong>${escapeHtml(hostDisplay)}</strong> | valor <strong>${escapeHtml(value)}</strong>
      </div>
    `;
  }

  function renderSelectedDomainPanel() {
    const panel = $("selectedDomainPanel");
    const verifyBtn = $("verifyDnsBtn");
    const goMailboxesBtn = $("goMailboxesBtn");
    const openGuideBtn = $("openGuideModalBtn");

    if (!panel) return;

    if (verifyBtn) verifyBtn.disabled = !state.selectedDomainId;
    if (goMailboxesBtn) goMailboxesBtn.disabled = !state.selectedDomainId;
    if (openGuideBtn) openGuideBtn.disabled = !state.selectedDomainId;

    if (!state.selectedDomainSetup) {
      panel.innerHTML = `
        <div class="empty-note">
          Selecione um domínio na lista para ver o resumo e abrir o guia passo a passo.
        </div>
      `;
      return;
    }

    const payload = state.selectedDomainSetup;
    const domain = payload.domain || {};
    const generated = payload.generated || {};
    const warnings = filterClientWarnings(payload.warnings);
    const statusText = humanizeStatus(domain.status);

    panel.innerHTML = `
      <div class="selected-domain-grid">
        <div class="summary-box">
          <span>Domínio selecionado</span>
          <strong>${escapeHtml(domain.name || "-")}</strong>
        </div>

        <div class="summary-box">
          <span>Servidor de e-mail</span>
          <strong>${escapeHtml(generated.mail_host || "-")}</strong>
        </div>

        <div class="summary-box">
          <span>App / painel</span>
          <strong>${escapeHtml(generated.app_host || "-")}</strong>
        </div>

        <div class="summary-box">
          <span>Status interno</span>
          <strong>${escapeHtml(statusText)}${domain.is_primary ? " • Principal" : ""}</strong>
        </div>
      </div>

      <div class="notice-stack">
        ${warnings.map((warning) => `
          <div class="notice warning">${escapeHtml(warning)}</div>
        `).join("")}

        <div class="notice info">
          Abra o guia para ver o passo a passo completo de configuração no provedor DNS.
        </div>
      </div>

      <div class="guide-steps">
        <div class="guide-step">
          <div class="guide-step__number">1</div>
          <div>
            <h4>Escolha o provedor DNS</h4>
            <p>No guia você seleciona o painel usado pelo cliente, como Registro.br, Hostinger, Cloudflare e outros.</p>
          </div>
        </div>

        <div class="guide-step">
          <div class="guide-step__number">2</div>
          <div>
            <h4>Copie os registros</h4>
            <p>O modal mostra nome, tipo e valor de cada registro em ordem, para preencher sem confusão.</p>
          </div>
        </div>

        <div class="guide-step">
          <div class="guide-step__number">3</div>
          <div>
            <h4>Valide no sistema</h4>
            <p>Depois de salvar tudo no DNS, clique em <strong>Verificar DNS</strong> para conferir o que já propagou.</p>
          </div>
        </div>
      </div>
    `;
  }

  function renderGuideModalContent() {
    const content = $("guideModalContent");
    const title = $("guideModalTitle");
    const subtitle = $("guideModalSubtitle");

    if (!content || !state.selectedDomainSetup) {
      if (content) {
        content.innerHTML = `<div class="empty-note">Selecione um domínio para abrir o guia.</div>`;
      }
      return;
    }

    const payload = state.selectedDomainSetup;
    const domain = payload.domain || {};
    const generated = payload.generated || {};
    const warnings = filterClientWarnings(payload.warnings);
    const records = getVisibleRecords(payload.records);

    if (title) title.textContent = "Guia de DNS e ativação";
    if (subtitle) subtitle.textContent = `Passo a passo para configurar ${domain.name || "o domínio"} no provedor DNS.`;

    content.innerHTML = `
      <div class="guide-summary">
        <div class="summary-box">
          <span>Domínio</span>
          <strong>${escapeHtml(domain.name || "-")}</strong>
        </div>
        <div class="summary-box">
          <span>Host do app</span>
          <strong>${escapeHtml(generated.app_host || "-")}</strong>
        </div>
        <div class="summary-box">
          <span>Host do mail</span>
          <strong>${escapeHtml(generated.mail_host || "-")}</strong>
        </div>
      </div>

      <div class="guide-steps">
        <div class="guide-step">
          <div class="guide-step__number">1</div>
          <div>
            <h4>Abra o painel DNS do cliente</h4>
            <p>Primeiro escolha abaixo onde o DNS do domínio está hospedado. O sistema vai adaptar o passo a passo para esse painel.</p>
          </div>
        </div>

        <div class="guide-step">
          <div class="guide-step__number">2</div>
          <div>
            <h4>Crie os registros na ordem mostrada</h4>
            <p>Adicione cada registro usando exatamente o nome e o valor exibidos no guia. Copie e cole para evitar erro.</p>
          </div>
        </div>

        <div class="guide-step">
          <div class="guide-step__number">3</div>
          <div>
            <h4>Aguarde a propagação</h4>
            <p>Depois de salvar no provedor, pode levar alguns minutos ou mais para refletir. Isso varia conforme o DNS.</p>
          </div>
        </div>

        <div class="guide-step">
          <div class="guide-step__number">4</div>
          <div>
            <h4>Volte e clique em Verificar DNS</h4>
            <p>Quando terminar a configuração, feche o guia e use o botão <strong>Verificar DNS</strong> para checar os registros.</p>
          </div>
        </div>
      </div>

      <div class="notice-stack">
        <div class="notice info">
          O cliente <strong>não precisa criar subdomínio próprio</strong> como mail.cliente.com ou painel.cliente.com. Use apenas os registros exibidos pelo AureMail.
        </div>

        ${warnings.map((warning) => `
          <div class="notice warning">${escapeHtml(warning)}</div>
        `).join("")}
      </div>

      <div class="provider-picker">
        <div class="provider-picker__head">
          <h4>Escolha o provedor DNS</h4>
          <p>Clique no provedor usado pelo cliente para abrir o passo a passo exato desse painel.</p>
        </div>

        <div class="provider-grid">
          ${PROVIDERS.map((provider) => `
            <button
              type="button"
              class="provider-btn ${state.selectedProviderId === provider.id ? "active" : ""}"
              data-provider-id="${provider.id}"
            >
              ${escapeHtml(provider.label)}
            </button>
          `).join("")}
        </div>
      </div>

      ${renderProviderGuide(records)}
    `;
  }

  async function copyText(text) {
    const value = String(text ?? "");
    const normalized = value.trim();

    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }

      showToast(normalized ? "Valor copiado com sucesso." : "Campo de nome vazio copiado.");
    } catch (_) {
      setPageMessage("Não consegui copiar automaticamente. Copie manualmente.", "error");
    }
  }

  async function handleCreate(event) {
    event.preventDefault();
    clearFormMessage();
    clearPageMessage();

    const name = normalizeDomainInput($("domainName")?.value);
    const status = $("domainStatus")?.value || "pending";
    const isPrimary = Boolean($("domainPrimary")?.checked);

    if (!name) {
      setFormMessage("Informe o domínio.", "error");
      return;
    }

    try {
      const result = await api("/api/dominios", {
        method: "POST",
        body: { name, status, is_primary: isPrimary },
      });

      resetCreateForm();
      state.editingId = null;
      state.selectedDomainId = result?.item?.id || null;
      state.selectedProviderId = null;

      await loadDomains();
      setFormMessage(result?.message || "Domínio cadastrado com sucesso.", "success");
      showToast(result?.message || "Domínio cadastrado com sucesso.", "success");

      setTimeout(() => {
        clearFormMessage();
        closeDomainModal();
      }, 300);
    } catch (error) {
      setFormMessage(error.message || "Erro ao cadastrar domínio.", "error");
    }
  }

  async function handleVerifyDns() {
    if (!state.selectedDomainId) return;

    clearPageMessage();

    try {
      state.selectedDomainVerification = await api(`/api/dominios/${state.selectedDomainId}/verify-dns`, {
        method: "POST",
      });

      renderSelectedDomainPanel();
      renderGuideModalContent();

      if (state.selectedDomainVerification?.all_required_ok) {
        setPageMessage("Todos os registros obrigatórios foram encontrados corretamente.", "success");
      } else {
        setPageMessage("Alguns registros ainda não bateram. Confira o DNS e ajuste no provedor.", "info");
      }
    } catch (error) {
      setPageMessage(error.message || "Erro ao verificar DNS.", "error");
    }
  }

  async function handleListClick(event) {
    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) return;

    const action = actionButton.getAttribute("data-action");
    const domainId = Number(actionButton.getAttribute("data-id"));
    if (!domainId) return;

    if (action === "select") {
      state.selectedDomainId = domainId;
      state.editingId = null;
      state.selectedProviderId = null;
      await loadSelectedDomainSetup();
      renderDomains();
      setPageMessage("Domínio selecionado.", "info");
      return;
    }

    if (action === "edit") {
      state.editingId = domainId;
      renderDomains();
      return;
    }

    if (action === "cancel-edit") {
      state.editingId = null;
      renderDomains();
      return;
    }

    if (action === "make-primary") {
      try {
        clearPageMessage();
        const result = await api(`/api/dominios/${domainId}/primary`, { method: "POST" });
        state.selectedDomainId = domainId;
        state.selectedProviderId = null;
        await loadDomains();
        setPageMessage(result?.message || "Domínio principal atualizado.", "success");
      } catch (error) {
        setPageMessage(error.message || "Erro ao definir domínio principal.", "error");
      }
      return;
    }

    if (action === "delete") {
      const confirmed = window.confirm("Deseja realmente excluir este domínio?");
      if (!confirmed) return;

      try {
        clearPageMessage();
        const result = await api(`/api/dominios/${domainId}`, { method: "DELETE" });

        if (state.editingId === domainId) state.editingId = null;

        if (state.selectedDomainId === domainId) {
          state.selectedDomainId = null;
          state.selectedDomainSetup = null;
          state.selectedDomainVerification = null;
          state.selectedProviderId = null;
        }

        await loadDomains();
        setPageMessage(result?.message || "Domínio removido com sucesso.", "success");
      } catch (error) {
        setPageMessage(error.message || "Erro ao excluir domínio.", "error");
      }
    }
  }

  async function handleEditSubmit(event) {
    const form = event.target.closest(".domain-edit-form");
    if (!form) return;

    event.preventDefault();
    clearPageMessage();

    const domainId = Number(form.getAttribute("data-domain-id"));
    if (!domainId) return;

    const name = normalizeDomainInput(form.elements.name?.value);
    const status = form.elements.status?.value || "pending";
    const isPrimary = Boolean(form.elements.is_primary?.checked);

    if (!name) {
      setPageMessage("Informe o domínio.", "error");
      return;
    }

    try {
      const result = await api(`/api/dominios/${domainId}`, {
        method: "PATCH",
        body: { name, status, is_primary: isPrimary },
      });

      state.editingId = null;
      state.selectedDomainId = domainId;
      state.selectedProviderId = null;
      await loadDomains();
      setPageMessage(result?.message || "Domínio atualizado com sucesso.", "success");
    } catch (error) {
      setPageMessage(error.message || "Erro ao atualizar domínio.", "error");
    }
  }

  async function init() {
    try {
      await mountSidebar();
      await loadMe();
      await loadDomains();
    } catch (error) {
      setPageMessage(error.message || "Erro ao carregar a página.", "error");
    }

    $("domainForm")?.addEventListener("submit", handleCreate);

    $("refreshDomainsBtn")?.addEventListener("click", async () => {
      clearPageMessage();
      try {
        await loadDomains(true);
      } catch (error) {
        setPageMessage(error.message || "Erro ao atualizar lista.", "error");
      }
    });

    $("goPanelBtn")?.addEventListener("click", () => {
      window.location.href = "/app";
    });

    $("goMailboxesBtn")?.addEventListener("click", () => {
      if (!state.selectedDomainId) return;
      window.location.href = `/caixas-email?dominio_id=${encodeURIComponent(state.selectedDomainId)}`;
    });

    $("verifyDnsBtn")?.addEventListener("click", handleVerifyDns);
    $("openGuideModalBtn")?.addEventListener("click", openGuideModal);

    $("openCreateDomainModalBtn")?.addEventListener("click", openDomainModal);
    $("openCreateDomainModalBtnInline")?.addEventListener("click", openDomainModal);
    $("closeDomainModalBtn")?.addEventListener("click", closeDomainModal);
    $("cancelDomainModalBtn")?.addEventListener("click", closeDomainModal);
    $("domainModalOverlay")?.addEventListener("click", closeDomainModal);

    $("closeGuideModalBtn")?.addEventListener("click", closeGuideModal);
    $("guideModalOverlay")?.addEventListener("click", closeGuideModal);

    $("domainList")?.addEventListener("click", handleListClick);
    $("domainList")?.addEventListener("submit", handleEditSubmit);

    $("guideModalContent")?.addEventListener("click", async (event) => {
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) {
        await copyText(copyButton.getAttribute("data-copy"));
        return;
      }

      const providerButton = event.target.closest("[data-provider-id]");
      if (providerButton) {
        const providerId = providerButton.getAttribute("data-provider-id");
        state.selectedProviderId = state.selectedProviderId === providerId ? null : providerId;
        renderGuideModalContent();
      }
    });

    document.addEventListener("click", (event) => {
      const helpButton = event.target.closest("[data-help-topic]");
      if (!helpButton) return;
      openHelp(helpButton.getAttribute("data-help-topic"));
    });

    $("helpOverlay")?.addEventListener("click", closeHelp);
    $("closeHelpBtn")?.addEventListener("click", closeHelp);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeHelp();
        closeDomainModal();
        closeGuideModal();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
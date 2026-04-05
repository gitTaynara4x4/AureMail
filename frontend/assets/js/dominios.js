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
      aValueLabel: "Endereço IPv4",
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
      rootHint: "Na Hostinger, a raiz do domínio normalmente usa @. Em alguns fluxos, também pode aceitar vazio.",
      aValueLabel: "Aponta para",
      txtValueLabel: "Conteúdo",
      mxPriorityLabel: "Prioridade",
      mxServerLabel: "Aponta para",
      extraNote: "Na Hostinger, se existir TTL padrão e você não quiser mexer, pode deixar o padrão.",
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
      aValueLabel: "Content",
      txtValueLabel: "Content",
      mxPriorityLabel: "Priority",
      mxServerLabel: "Mail server",
      extraNote: "Para o host de e-mail (mail), deixe Proxy status como DNS only.",
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
      aValueLabel: "Valor",
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
      aValueLabel: "Destino",
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
      aValueLabel: "Aponta para",
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
      aValueLabel: "Aponta para",
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
      accessTitle: "How to open in Namecheap",
      accessSteps: [
        "Open the domain panel.",
        "Go to Advanced DNS or DNS records.",
        "Add the records manually.",
      ],
      rootHint: "Na Namecheap, a raiz do domínio normalmente usa @.",
      aValueLabel: "Value",
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
      aValueLabel: "Valor",
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
            <li>Os registros como A, MX, SPF, DMARC e DKIM ainda podem estar faltando.</li>
            <li>É o status mais comum no começo.</li>
          </ul>
        </div>

        <div class="help-block">
          <h4>Ativo</h4>
          <p>
            Use quando o domínio já está pronto para uso no ambiente de e-mail.
          </p>
          <ul>
            <li>DNS principal já foi configurado.</li>
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
      .replace(/^\.+|\.+$/g, "");
  }

  function humanizeStatus(status) {
    const normalized = String(status || "").trim().toLowerCase();
    if (normalized === "active") return "Ativo";
    if (normalized === "inactive") return "Inativo";
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

  async function parseJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

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
      renderSelectedDomainPanel();
      return;
    }

    state.selectedDomainSetup = await api(`/api/dominios/${state.selectedDomainId}/dns-setup`);
    state.selectedDomainVerification = null;
    state.selectedProviderId = null;
    renderEnvSummary();
    renderSelectedDomainPanel();
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
          Nenhum domínio cadastrado ainda. Use o formulário ao lado para adicionar o primeiro.
        </div>
      `;
      return;
    }

    list.innerHTML = state.domains.map((item) => renderDomainItem(item)).join("");
  }

  function renderDomainItem(item) {
    const isEditing = state.editingId === item.id;
    const isSelected = Number(state.selectedDomainId) === Number(item.id);
    const statusClass = item.status === "active" ? "active" : (item.status === "pending" ? "pending" : "inactive");

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
                  <option value="pending" ${item.status === "pending" ? "selected" : ""}>Pendente</option>
                  <option value="active" ${item.status === "active" ? "selected" : ""}>Ativo</option>
                  <option value="inactive" ${item.status === "inactive" ? "selected" : ""}>Inativo</option>
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
              DNS / Guia
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

  function providerHostValue(host, provider) {
    const normalized = String(host || "").trim();

    if (!normalized || normalized === "@") {
      return provider?.rootMode === "blank" ? "(deixe vazio)" : "@";
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

  function isDkimPending(record) {
    const value = getRecordValue(record).toUpperCase();
    return record?.key === "dkim" || value.includes("AUREMAIL_DKIM_PUBLIC_KEY") || value.includes("GERAR CHAVE DKIM");
  }

  function renderProviderButtons() {
    return `
      <div class="provider-picker">
        <div class="provider-picker__head">
          <h4>Escolha onde seu DNS está hospedado</h4>
          <p>
            Clique no provedor usado pelo cliente. O AureMail mostra só o guia daquele painel.
          </p>
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
    `;
  }

  function renderProviderGuide(records, generated) {
    const provider = getProvider();

    if (!provider) {
      return `
        <div class="provider-intro-empty">
          Escolha um provedor acima para abrir apenas o guia daquele painel.
        </div>
      `;
    }

    return `
      <div class="provider-guide">
        <div class="provider-guide__head">
          <h4>${escapeHtml(provider.label)}</h4>
          <p>${provider.type === "exact" ? "Guia mais detalhado" : "Guia inicial/genérico"} para esse provedor.</p>
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

          ${records.map((record) => renderProviderRecord(record, provider, generated)).join("")}

          <div class="provider-summary">
            ${records.map((record) => renderProviderSummaryLine(record, provider)).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderProviderRecord(record, provider, generated) {
    const type = String(record?.type || "").trim().toUpperCase();
    const value = getRecordValue(record);
    const hostValue = providerHostValue(record?.host || "", provider);
    const label = record?.label || record?.key || "Registro";

    if (isDkimPending(record)) {
      return `
        <article class="provider-record is-later">
          <div class="provider-record__title">
            <strong>${escapeHtml(label)}</strong>
            <span class="provider-record__badge">depois</span>
          </div>

          <div class="provider-fields">
            <div class="provider-field">
              <label>Tipo</label>
              <code>TXT</code>
            </div>
            <div class="provider-field">
              <label>Nome</label>
              <code>${escapeHtml(hostValue)}</code>
            </div>
            <div class="provider-field">
              <label>${escapeHtml(provider.txtValueLabel)}</label>
              <code>Preencher depois com a chave pública DKIM</code>
            </div>
          </div>

          <div class="provider-field-note">
            Não criar agora. Primeiro gere a chave DKIM no servidor de e-mail real.
          </div>
        </article>
      `;
    }

    if (type === "MX") {
      const mx = parseMxValue(value);

      return `
        <article class="provider-record">
          <div class="provider-record__title">
            <strong>${escapeHtml(label)}</strong>
            <span class="provider-record__badge">MX</span>
          </div>

          <div class="provider-fields">
            <div class="provider-field">
              <label>Tipo</label>
              <code>MX</code>
            </div>
            <div class="provider-field">
              <label>Nome</label>
              <code>${escapeHtml(hostValue)}</code>
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
        </article>
      `;
    }

    if (type === "A") {
      const cloudflareExtra = provider.id === "cloudflare"
        ? `
          <div class="provider-field">
            <label>Proxy status</label>
            <code>${record.host === "mail" ? "DNS only" : "DNS only (recomendado no primeiro setup)"}</code>
          </div>
        `
        : "";

      return `
        <article class="provider-record">
          <div class="provider-record__title">
            <strong>${escapeHtml(label)}</strong>
            <span class="provider-record__badge">A</span>
          </div>

          <div class="provider-fields">
            <div class="provider-field">
              <label>Tipo</label>
              <code>A</code>
            </div>
            <div class="provider-field">
              <label>Nome</label>
              <code>${escapeHtml(hostValue)}</code>
            </div>
            <div class="provider-field">
              <label>${escapeHtml(provider.aValueLabel)}</label>
              <code>${escapeHtml(value)}</code>
            </div>
            ${cloudflareExtra}
          </div>
        </article>
      `;
    }

    if (type === "TXT") {
      return `
        <article class="provider-record">
          <div class="provider-record__title">
            <strong>${escapeHtml(label)}</strong>
            <span class="provider-record__badge">TXT</span>
          </div>

          <div class="provider-fields">
            <div class="provider-field">
              <label>Tipo</label>
              <code>TXT</code>
            </div>
            <div class="provider-field">
              <label>Nome</label>
              <code>${escapeHtml(hostValue)}</code>
            </div>
            <div class="provider-field">
              <label>${escapeHtml(provider.txtValueLabel)}</label>
              <code>${escapeHtml(value)}</code>
            </div>
          </div>
        </article>
      `;
    }

    return `
      <article class="provider-record">
        <div class="provider-record__title">
          <strong>${escapeHtml(label)}</strong>
          <span class="provider-record__badge">${escapeHtml(type || "-")}</span>
        </div>

        <div class="provider-fields">
          <div class="provider-field">
            <label>Nome</label>
            <code>${escapeHtml(hostValue)}</code>
          </div>
          <div class="provider-field">
            <label>Valor</label>
            <code>${escapeHtml(value)}</code>
          </div>
        </div>
      </article>
    `;
  }

  function renderProviderSummaryLine(record, provider) {
    const type = String(record?.type || "").trim().toUpperCase();
    const value = getRecordValue(record);
    const hostValue = providerHostValue(record?.host || "", provider);

    if (isDkimPending(record)) {
      return `
        <div class="provider-summary-line">
          <strong>TXT</strong> | nome <strong>${escapeHtml(hostValue)}</strong> | valor <strong>preencher depois com a chave DKIM</strong>
        </div>
      `;
    }

    if (type === "MX") {
      const mx = parseMxValue(value);
      return `
        <div class="provider-summary-line">
          <strong>MX</strong> | nome <strong>${escapeHtml(hostValue)}</strong> | ${escapeHtml(provider.mxPriorityLabel.toLowerCase())} <strong>${escapeHtml(mx.priority)}</strong> | ${escapeHtml(provider.mxServerLabel.toLowerCase())} <strong>${escapeHtml(mx.server)}</strong>
        </div>
      `;
    }

    return `
      <div class="provider-summary-line">
        <strong>${escapeHtml(type)}</strong> | nome <strong>${escapeHtml(hostValue)}</strong> | valor <strong>${escapeHtml(value)}</strong>
      </div>
    `;
  }

  function renderSelectedDomainPanel() {
    const panel = $("selectedDomainPanel");
    const verifyBtn = $("verifyDnsBtn");
    const goMailboxesBtn = $("goMailboxesBtn");

    if (!panel) return;

    verifyBtn.disabled = !state.selectedDomainId;
    goMailboxesBtn.disabled = !state.selectedDomainId;

    if (!state.selectedDomainSetup) {
      panel.innerHTML = `
        <div class="empty-note">
          Selecione um domínio na lista para ver o guia de DNS.
        </div>
      `;
      return;
    }

    const payload = state.selectedDomainSetup;
    const domain = payload.domain || {};
    const generated = payload.generated || {};
    const records = Array.isArray(payload.records) ? payload.records : [];
    const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
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
          O cliente digita apenas o domínio. O AureMail gera os hosts, os registros
          e o texto que ele precisa copiar no provedor DNS.
        </div>
      </div>

      <div class="details-layout">
        <div class="records-card">
          <div class="sub-card-head">
            <div>
              <h4>Registros gerados pelo AureMail</h4>
              <p>Base técnica dos registros. O guia do provedor abre só quando você clicar nele.</p>
            </div>
          </div>

          <div class="records-table-wrap">
            <table class="records-table">
              <thead>
                <tr>
                  <th>Registro</th>
                  <th>Tipo</th>
                  <th>Host</th>
                  <th>Valor</th>
                  <th>TTL</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${records.map((record) => {
                  const verification = verificationEntryFor(record.key);

                  return `
                    <tr>
                      <td>
                        <div class="record-name">
                          <strong>${escapeHtml(record.label || record.key)}</strong>
                          <span>${escapeHtml(record.description || "")}</span>
                        </div>
                      </td>
                      <td>${escapeHtml(record.type || "-")}</td>
                      <td>
                        <div class="record-name">
                          <strong>${escapeHtml(record.host || "-")}</strong>
                          <span>${escapeHtml(record.fqdn || "")}</span>
                        </div>
                      </td>
                      <td>
                        <div class="record-value">
                          <div class="record-code">${escapeHtml(record.display_value || "-")}</div>
                          <button type="button" class="copy-btn" data-copy="${escapeHtml(record.copy_value || "")}">
                            Copiar
                          </button>
                        </div>
                        ${renderFoundValues(verification)}
                      </td>
                      <td>${escapeHtml(record.ttl || "-")}</td>
                      <td>${renderVerificationChip(verification)}</td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>

          ${renderProviderButtons()}
          ${renderProviderGuide(records, generated)}
        </div>

        <div class="instructions-card">
          <div class="sub-card-head">
            <div>
              <h4>Como o cliente preenche</h4>
              <p>Texto simples para orientar sem confundir.</p>
            </div>
          </div>

          <div class="instructions-body">
            <div class="instructions-group">
              <h5>Passo a passo</h5>
              <ol class="instructions-steps">
                ${steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
              </ol>
            </div>

            <div class="instructions-group">
              <h5>Resumo rápido</h5>
              <p>
                <strong>Domínio:</strong> ${escapeHtml(domain.name || "-")}<br />
                <strong>Host do app:</strong> ${escapeHtml(generated.app_host || "-")}<br />
                <strong>Host do mail:</strong> ${escapeHtml(generated.mail_host || "-")}<br />
                <strong>Relatório DMARC:</strong> ${escapeHtml(generated.dmarc_report_email || "-")}
              </p>
            </div>

            <div class="instructions-group">
              <h5>Importante</h5>
              <ul class="instructions-steps">
                <li>Escolha o provedor DNS acima para ver só o passo a passo daquele painel.</li>
                <li>O DKIM só deve ser criado depois de gerar a chave pública no servidor de e-mail.</li>
                <li>Depois de criar tudo no DNS, clique em <strong>Verificar DNS</strong>.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  async function copyText(text) {
    const value = String(text || "").trim();
    if (!value) {
      setPageMessage("Nada para copiar nesse campo ainda.", "error");
      return;
    }

    try {
      await navigator.clipboard.writeText(value);
      setPageMessage("Valor copiado com sucesso.", "success");
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
    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      await copyText(copyButton.getAttribute("data-copy"));
      return;
    }

    const providerButton = event.target.closest("[data-provider-id]");
    if (providerButton) {
      const providerId = providerButton.getAttribute("data-provider-id");
      state.selectedProviderId = state.selectedProviderId === providerId ? null : providerId;
      renderSelectedDomainPanel();
      return;
    }

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
      setPageMessage("Guia de DNS carregado para o domínio selecionado.", "info");
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

    $("domainList")?.addEventListener("click", handleListClick);
    $("domainList")?.addEventListener("submit", handleEditSubmit);

    $("selectedDomainPanel")?.addEventListener("click", async (event) => {
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) {
        await copyText(copyButton.getAttribute("data-copy"));
        return;
      }

      const providerButton = event.target.closest("[data-provider-id]");
      if (providerButton) {
        const providerId = providerButton.getAttribute("data-provider-id");
        state.selectedProviderId = state.selectedProviderId === providerId ? null : providerId;
        renderSelectedDomainPanel();
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
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
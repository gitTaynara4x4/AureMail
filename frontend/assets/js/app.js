(() => {
  const elements = {
    refreshBtn: document.getElementById("refreshBtn"),
    openMailBtn: document.getElementById("openMailBtn"),
    goDomainsBtn: document.getElementById("goDomainsBtn"),
    goMailboxesBtn: document.getElementById("goMailboxesBtn"),

    companyName: document.getElementById("companyName"),
    companyDocument: document.getElementById("companyDocument"),
    companyStatus: document.getElementById("companyStatus"),

    userName: document.getElementById("userName"),
    userEmail: document.getElementById("userEmail"),
    userRole: document.getElementById("userRole"),

    mainDomain: document.getElementById("mainDomain"),
    nextStep: document.getElementById("nextStep"),
    statusChip: document.getElementById("statusChip"),
    sidebarMount: document.getElementById("sidebarMount")
  };

  function normalizeStatus(value) {
    return String(value || "").trim().toLowerCase();
  }

  function humanizeCompanyStatus(status) {
    const normalized = normalizeStatus(status);

    if (normalized === "active") return "Ativa";
    if (normalized === "pending") return "Pendente";
    if (normalized === "inactive") return "Inativa";
    if (normalized === "suspended") return "Suspensa";

    return normalized
      ? normalized.charAt(0).toUpperCase() + normalized.slice(1)
      : "Não informado";
  }

  function getUserRole(user, mailbox) {
    if (user?.is_owner || mailbox?.is_admin) return "Proprietário da empresa";
    return "Usuário da plataforma";
  }

  function setText(element, value, fallback = "Não informado") {
    if (!element) return;
    element.textContent = value || fallback;
  }

  function showToast(message, tone = "default") {
    const toast = document.createElement("div");
    toast.textContent = message;

    const isDark = document.documentElement.getAttribute("data-theme") === "dark";

    const colors = {
      default: isDark
        ? { bg: "#18181b", text: "#f5f5f5", border: "#27272a" }
        : { bg: "#111827", text: "#ffffff", border: "transparent" },

      success: isDark
        ? { bg: "#0f1f17", text: "#86efac", border: "#1f3a2b" }
        : { bg: "#065f46", text: "#ffffff", border: "transparent" },

      danger: isDark
        ? { bg: "#241313", text: "#fca5a5", border: "#3b1d1d" }
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

  async function mountSidebar() {
    const mount = elements.sidebarMount;
    if (!mount) return;

    try {
      const response = await fetch("/assets/partials/sidebar.html", {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "text/html" }
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
    } catch (error) {
      console.error("Erro ao montar sidebar:", error);
    }
  }

  function render(data) {
    const company = data?.company || {};
    const user = data?.user || {};
    const mailbox = data?.mailbox || {};

    const status = normalizeStatus(company.status);
    const domain = mailbox.domain || "Nenhum domínio cadastrado";
    const nextStep = mailbox.domain
      ? "Criar caixas de e-mail do domínio principal"
      : "Cadastrar o primeiro domínio da empresa";

    setText(elements.companyName, company.name, "Empresa");
    setText(elements.companyDocument, company.cnpj_cpf, "CPF/CNPJ não disponível");
    setText(elements.companyStatus, humanizeCompanyStatus(company.status), "Não informado");

    setText(elements.userName, user.name || mailbox.display_name, "Usuário");
    setText(elements.userEmail, user.email || mailbox.email, "E-mail não disponível");
    setText(elements.userRole, getUserRole(user, mailbox), "Usuário da plataforma");

    setText(elements.mainDomain, domain, "Nenhum domínio cadastrado");
    setText(elements.nextStep, nextStep, "Continuar configuração do ambiente");

    if (elements.statusChip) {
      if (status === "active") {
        elements.statusChip.className = "status-chip active";
        elements.statusChip.textContent = "Ambiente ativo";
      } else if (status === "pending") {
        elements.statusChip.className = "status-chip pending";
        elements.statusChip.textContent = "Ambiente pendente";
      } else {
        elements.statusChip.className = "status-chip inactive";
        elements.statusChip.textContent = "Ambiente com atenção";
      }
    }

    if (window.AureMailSidebar?.apply) {
      window.AureMailSidebar.apply(data);
    }
  }

  async function loadData(showFeedback = false) {
    const originalHTML = elements.refreshBtn?.innerHTML;

    try {
      if (elements.refreshBtn) {
        elements.refreshBtn.disabled = true;
        elements.refreshBtn.textContent = "Atualizando...";
      }

      const response = await fetch("/api/me", {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" }
      });

      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }

      if (!response.ok) {
        throw new Error("Falha ao carregar sessão");
      }

      const data = await response.json();
      render(data);

      if (showFeedback) {
        showToast("Painel atualizado.", "success");
      }
    } catch (error) {
      console.error("Erro ao carregar dados do painel:", error);
      showToast("Erro ao carregar o painel.", "danger");
    } finally {
      if (elements.refreshBtn) {
        elements.refreshBtn.disabled = false;
        elements.refreshBtn.innerHTML = originalHTML || "Atualizar";
      }
    }
  }

  function attachEvents() {
    elements.refreshBtn?.addEventListener("click", () => loadData(true));

    elements.openMailBtn?.addEventListener("click", () => {
      window.location.href = "/mail";
    });

    elements.goDomainsBtn?.addEventListener("click", () => {
      window.location.href = "/dominios";
    });

    elements.goMailboxesBtn?.addEventListener("click", () => {
      window.location.href = "/caixas-email";
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    await mountSidebar();
    attachEvents();
    await loadData(false);
  });
})();
(function () {
  const state = {
    me: null,
  };

  function $(id) { return document.getElementById(id); }

  async function api(url) {
    const response = await fetch(url, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" }
    });

    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("Sessão expirada.");
    }
    
    if (!response.ok) return null;
    return await response.json();
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
      Array.from(oldScript.attributes).forEach((attr) => { newScript.setAttribute(attr.name, attr.value); });
      newScript.textContent = oldScript.textContent;
      oldScript.replaceWith(newScript);
    });
  }

  async function loadMe() {
    state.me = await api("/api/me");
    
    // Atualiza a sidebar se ela existir
    if (window.AureMailSidebar?.apply && state.me) { 
      window.AureMailSidebar.apply(state.me); 
    }

    // Preenche os dados de perfil na tela de configurações
    if (state.me && state.me.user) {
      const nameInput = $("profileName");
      const emailInput = $("profileEmail");
      
      if (nameInput) nameInput.value = state.me.user.name || state.me.mailbox?.display_name || "Usuário";
      if (emailInput) emailInput.value = state.me.user.email || state.me.mailbox?.email || "";
    }
  }

  // --- LÓGICA DO DARK MODE ---
  function initTheme() {
    const toggle = $("darkModeToggle");
    if (!toggle) return;

    // 1. Verifica se já existe uma preferência salva no navegador
    const currentTheme = localStorage.getItem("auremail-theme");

    // 2. Se for dark, aplica a classe no HTML e liga o switch
    if (currentTheme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      toggle.checked = true;
    }

    // 3. Ouve o clique do usuário no botão
    toggle.addEventListener("change", function(e) {
      if (e.target.checked) {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("auremail-theme", "dark"); // Salva no navegador
      } else {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("auremail-theme", "light"); // Salva no navegador
      }
    });
  }

  async function init() {
    initTheme(); // Executa o tema antes de carregar dados para não piscar
    await mountSidebar();
    await loadMe();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
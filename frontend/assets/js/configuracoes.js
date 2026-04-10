(function () {
  const elements = {
    sidebarMount: document.getElementById("sidebarMount"),
    darkModeToggle: document.getElementById("darkModeToggle"),
    profileName: document.getElementById("profileName"),
    profileEmail: document.getElementById("profileEmail"),
  };

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

    try {
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
    } catch (error) {
      console.error("Erro ao carregar sidebar:", error);
    }
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

  function applyTheme(mode) {
    if (mode === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem("auremail-theme", "dark");
      if (elements.darkModeToggle) elements.darkModeToggle.checked = true;
      return;
    }

    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("auremail-theme", "light");
    if (elements.darkModeToggle) elements.darkModeToggle.checked = false;
  }

  function initThemeToggle() {
    const currentTheme = localStorage.getItem("auremail-theme");
    if (elements.darkModeToggle) {
      elements.darkModeToggle.checked = currentTheme === "dark";
      elements.darkModeToggle.addEventListener("change", (event) => {
        applyTheme(event.target.checked ? "dark" : "light");
      });
    }
  }

  function getBestNameFromMe(data) {
    return (
      data?.user?.name ||
      data?.mailbox?.display_name ||
      data?.name ||
      "Não informado"
    );
  }

  function getBestEmailFromMe(data) {
    return (
      data?.user?.email ||
      data?.mailbox?.email ||
      data?.email ||
      "Não informado"
    );
  }

  async function loadProfile() {
    try {
      const me = await api("/api/me");

      if (window.AureMailSidebar?.apply) {
        window.AureMailSidebar.apply(me);
      }

      if (elements.profileName) {
        elements.profileName.value = getBestNameFromMe(me);
      }

      if (elements.profileEmail) {
        elements.profileEmail.value = getBestEmailFromMe(me);
      }
    } catch (error) {
      console.error("Erro ao carregar perfil:", error);

      if (elements.profileName) {
        elements.profileName.value = "Não foi possível carregar";
      }

      if (elements.profileEmail) {
        elements.profileEmail.value = "Não foi possível carregar";
      }
    }
  }

  async function init() {
    initThemeToggle();
    await mountSidebar();
    await loadProfile();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
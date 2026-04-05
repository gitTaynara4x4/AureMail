(() => {
  const STORAGE_KEYS = {
    localSession: "auremail_session",
    tempSession: "auremail_temp_session"
  };

  const LAST_CREATED_OWNER_EMAIL_KEY = "auremail_last_created_owner_email";

  const form = document.getElementById("loginForm");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const rememberInput = document.getElementById("remember");
  const togglePasswordBtn = document.getElementById("togglePassword");
  const loginBtn = document.getElementById("loginBtn");
  const formMessage = document.getElementById("formMessage");
  const emailError = document.getElementById("emailError");
  const passwordError = document.getElementById("passwordError");

  function clearStoredSession() {
    try {
      localStorage.removeItem(STORAGE_KEYS.localSession);
      sessionStorage.removeItem(STORAGE_KEYS.tempSession);
    } catch (error) {
      console.error("Erro ao limpar sessão local:", error);
    }
  }

  function setStoredSession(sessionData, remember) {
    try {
      clearStoredSession();
      if (remember) {
        localStorage.setItem(STORAGE_KEYS.localSession, JSON.stringify(sessionData));
      } else {
        sessionStorage.setItem(STORAGE_KEYS.tempSession, JSON.stringify(sessionData));
      }
    } catch (error) {
      console.error("Erro ao salvar sessão local:", error);
    }
  }

  function humanizeNameFromEmail(email) {
    const localPart = (email || "").split("@")[0] || "usuario";
    return localPart
      .replace(/[._-]+/g, " ")
      .split(" ")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
      .join(" ");
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  function clearErrors() {
    emailError.textContent = "";
    passwordError.textContent = "";
    formMessage.textContent = "";
    formMessage.style.color = "var(--text-muted)";
    emailInput.style.borderColor = "";
    passwordInput.style.borderColor = "";
  }

  function showFieldError(input, element, message) {
    element.textContent = message;
    input.style.borderColor = "var(--danger)";
  }

  function setLoading(isLoading) {
    loginBtn.disabled = isLoading;
    loginBtn.textContent = isLoading ? "Validando acesso..." : "Entrar na plataforma";
    loginBtn.style.opacity = isLoading ? "0.82" : "1";
  }

  function redirectToApp() {
    window.location.href = "/app";
  }

  function setMessage(message, color = "var(--text-main)") {
    formMessage.textContent = message;
    formMessage.style.color = color;
  }

  function preloadLastCreatedEmail() {
    try {
      const lastEmail = localStorage.getItem(LAST_CREATED_OWNER_EMAIL_KEY);
      if (lastEmail && emailInput && !emailInput.value) {
        emailInput.value = lastEmail;
      }
    } catch (error) {
      console.error("Erro ao preencher último e-mail criado:", error);
    }
  }

  async function checkServerSession() {
    try {
      const response = await fetch("/api/auth/check", {
        method: "GET",
        credentials: "include",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) return false;
      const data = await response.json();
      return !!data?.authenticated;
    } catch (error) {
      console.error("Erro ao validar sessão no servidor:", error);
      return false;
    }
  }

  async function maybeRedirectIfLogged() {
    const hasServerSession = await checkServerSession();
    if (hasServerSession) {
      redirectToApp();
      return;
    }
    clearStoredSession();
  }

  if (togglePasswordBtn && passwordInput) {
    const eyeIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const eyeOffIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/></svg>`;
    
    togglePasswordBtn.addEventListener("click", () => {
      const isPassword = passwordInput.type === "password";
      passwordInput.type = isPassword ? "text" : "password";
      togglePasswordBtn.innerHTML = isPassword ? eyeOffIcon : eyeIcon;
    });
  }

  if (emailInput) {
    emailInput.addEventListener("input", () => {
      emailError.textContent = "";
      emailInput.style.borderColor = "";
      formMessage.textContent = "";
    });
  }

  if (passwordInput) {
    passwordInput.addEventListener("input", () => {
      passwordError.textContent = "";
      passwordInput.style.borderColor = "";
      formMessage.textContent = "";
    });
  }

  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearErrors();

      const email = (emailInput.value || "").trim().toLowerCase();
      const password = passwordInput.value || "";
      const remember = !!rememberInput.checked;

      let hasError = false;

      if (!email) {
        showFieldError(emailInput, emailError, "Informe seu e-mail.");
        hasError = true;
      } else if (!isValidEmail(email)) {
        showFieldError(emailInput, emailError, "Digite um e-mail válido.");
        hasError = true;
      }

      if (!password) {
        showFieldError(passwordInput, passwordError, "Informe sua senha.");
        hasError = true;
      } else if (password.length < 4) {
        showFieldError(passwordInput, passwordError, "A senha deve ter pelo menos 4 caracteres.");
        hasError = true;
      }

      if (hasError) {
        setMessage("Revise os campos destacados e tente novamente.", "var(--danger)");
        return;
      }

      setLoading(true);
      setMessage("Validando acesso...", "var(--text-muted)");

      try {
        const response = await fetch("/api/login", {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ email, password, remember })
        });

        let data = null;
        try { data = await response.json(); } catch (_) { data = null; }

        if (!response.ok) {
          const detail = data?.detail || data?.message || "Não foi possível realizar o login.";
          clearStoredSession();
          setMessage(detail, "var(--danger)");
          setLoading(false);
          return;
        }

        const sessionData = {
          email: data?.email || email,
          displayName: data?.display_name || humanizeNameFromEmail(email),
          domain: data?.domain || "",
          companyName: data?.company_name || "",
          remember,
          loggedAt: new Date().toISOString()
        };

        setStoredSession(sessionData, remember);
        setMessage(data?.message || "Acesso autorizado. Redirecionando...", "var(--success)");

        setTimeout(() => { redirectToApp(); }, 500);
      } catch (error) {
        console.error("Erro ao fazer login:", error);
        setMessage("Erro de conexão com o servidor.", "var(--danger)");
        setLoading(false);
      }
    });
  }

  preloadLastCreatedEmail();
  maybeRedirectIfLogged();
})();
(() => {
  const form = document.getElementById("webmailLoginForm");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const rememberInput = document.getElementById("remember");
  const loginBtn = document.getElementById("loginBtn");
  const formMessage = document.getElementById("formMessage");
  const emailError = document.getElementById("emailError");
  const passwordError = document.getElementById("passwordError");
  const togglePasswordBtn = document.getElementById("togglePassword");
  const togglePasswordText = document.getElementById("togglePasswordText");

  function normalizeEmail(value) {
    return String(value || "").trim().toLowerCase();
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  function clearErrors() {
    emailError.textContent = "";
    passwordError.textContent = "";
    formMessage.textContent = "";
    formMessage.className = "form-message";
    emailInput.style.borderColor = "";
    passwordInput.style.borderColor = "";
  }

  function showFieldError(input, element, message) {
    element.textContent = message;
    input.style.borderColor = "var(--danger, #dc2626)";
  }

  function setMessage(message, tone = "") {
    formMessage.textContent = message || "";
    formMessage.className = `form-message ${tone}`.trim();
  }

  function setLoading(isLoading) {
    loginBtn.disabled = isLoading;
    loginBtn.textContent = isLoading ? "Entrando..." : "Entrar no webmail";
  }

  async function parseJson(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const message =
        payload?.detail ||
        payload?.message ||
        `Erro ${response.status}`;
      throw new Error(message);
    }

    return payload;
  }

  async function checkWebmailSession() {
    try {
      const response = await fetch("/api/webmail-auth/me", {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });

      if (!response.ok) return;
      window.location.href = "/mail";
    } catch (_) {}
  }

  async function submitLogin(event) {
    event.preventDefault();
    clearErrors();

    const email = normalizeEmail(emailInput.value);
    const password = String(passwordInput.value || "");
    const remember = Boolean(rememberInput.checked);

    let hasError = false;

    if (!email) {
      showFieldError(emailInput, emailError, "Informe o e-mail da caixa.");
      hasError = true;
    } else if (!isValidEmail(email)) {
      showFieldError(emailInput, emailError, "Digite um e-mail válido.");
      hasError = true;
    }

    if (!password) {
      showFieldError(passwordInput, passwordError, "Informe a senha.");
      hasError = true;
    }

    if (hasError) {
      setMessage("Revise os campos destacados.", "error");
      return;
    }

    setLoading(true);
    setMessage("Validando acesso ao webmail...", "info");

    try {
      const response = await fetch("/api/webmail-auth/login", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
          remember,
        }),
      });

      const data = await parseJson(response);
      setMessage(data?.message || "Login realizado com sucesso.", "success");

      setTimeout(() => {
        window.location.href = "/mail";
      }, 500);
    } catch (error) {
      setMessage(error.message || "Não foi possível entrar no webmail.", "error");
      setLoading(false);
    }
  }

  emailInput?.addEventListener("input", () => {
    emailInput.value = normalizeEmail(emailInput.value);
    emailError.textContent = "";
    emailInput.style.borderColor = "";
    formMessage.textContent = "";
  });

  passwordInput?.addEventListener("input", () => {
    passwordError.textContent = "";
    passwordInput.style.borderColor = "";
    formMessage.textContent = "";
  });

  togglePasswordBtn?.addEventListener("click", () => {
    const isPassword = passwordInput.type === "password";
    passwordInput.type = isPassword ? "text" : "password";
    togglePasswordText.textContent = isPassword ? "Ocultar" : "Mostrar";
  });

  form?.addEventListener("submit", submitLogin);

  checkWebmailSession();
})();
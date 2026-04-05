(() => {
  const LAST_CREATED_OWNER_EMAIL_KEY = "auremail_last_created_owner_email";

  const form = document.getElementById("createCompanyForm");
  const companyNameInput = document.getElementById("companyName");
  const cnpjCpfInput = document.getElementById("cnpjCpf");
  const ownerNameInput = document.getElementById("ownerName");
  const ownerEmailInput = document.getElementById("ownerEmail");
  const passwordInput = document.getElementById("password");
  const confirmPasswordInput = document.getElementById("confirmPassword");
  const togglePasswordBtn = document.getElementById("togglePassword");
  const toggleConfirmPasswordBtn = document.getElementById("toggleConfirmPassword");
  const createCompanyBtn = document.getElementById("createCompanyBtn");
  const formMessage = document.getElementById("formMessage");
  const ownerEmailPreview = document.getElementById("ownerEmailPreview");

  const errorElements = {
    companyName: document.getElementById("companyNameError"),
    cnpjCpf: document.getElementById("cnpjCpfError"),
    ownerName: document.getElementById("ownerNameError"),
    ownerEmail: document.getElementById("ownerEmailError"),
    password: document.getElementById("passwordError"),
    confirmPassword: document.getElementById("confirmPasswordError")
  };

  function normalizeEmail(value) { return String(value || "").trim().toLowerCase(); }
  function normalizeDocument(value) { return String(value || "").replace(/\D/g, ""); }

  function maskDocument(value) {
    const digits = normalizeDocument(value);
    if (digits.length <= 11) {
      return digits
        .replace(/^(\d{3})(\d)/, "$1.$2")
        .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1-$2")
        .slice(0, 14);
    }
    return digits
      .replace(/^(\d{2})(\d)/, "$1.$2")
      .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
      .replace(/\.(\d{3})(\d)/, ".$1/$2")
      .replace(/(\d{4})(\d)/, "$1-$2")
      .slice(0, 18);
  }

  function isRepeatedDigits(value) { return /^(\d)\1+$/.test(value); }

  function isValidCpf(value) {
    const cpf = normalizeDocument(value);
    if (cpf.length !== 11 || isRepeatedDigits(cpf)) return false;

    let sum = 0;
    for (let i = 0; i < 9; i++) { sum += Number(cpf[i]) * (10 - i); }
    let digit = (sum * 10) % 11;
    if (digit === 10) digit = 0;
    if (digit !== Number(cpf[9])) return false;

    sum = 0;
    for (let i = 0; i < 10; i++) { sum += Number(cpf[i]) * (11 - i); }
    digit = (sum * 10) % 11;
    if (digit === 10) digit = 0;

    return digit === Number(cpf[10]);
  }

  function isValidCnpj(value) {
    const cnpj = normalizeDocument(value);
    if (cnpj.length !== 14 || isRepeatedDigits(cnpj)) return false;

    const weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const weights2 = [6, ...weights1];

    let sum = 0;
    for (let i = 0; i < 12; i++) { sum += Number(cnpj[i]) * weights1[i]; }
    let remainder = sum % 11;
    let digit1 = remainder < 2 ? 0 : 11 - remainder;
    if (digit1 !== Number(cnpj[12])) return false;

    sum = 0;
    for (let i = 0; i < 13; i++) { sum += Number(cnpj[i]) * weights2[i]; }
    remainder = sum % 11;
    let digit2 = remainder < 2 ? 0 : 11 - remainder;

    return digit2 === Number(cnpj[13]);
  }

  function isValidDocument(value) {
    const doc = normalizeDocument(value);
    if (doc.length === 11) return isValidCpf(doc);
    if (doc.length === 14) return isValidCnpj(doc);
    return false;
  }

  function isValidEmail(email) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email); }

  function clearErrors() {
    Object.values(errorElements).forEach((element) => { if (element) element.textContent = ""; });
    [companyNameInput, cnpjCpfInput, ownerNameInput, ownerEmailInput, passwordInput, confirmPasswordInput].forEach((input) => {
      if (input) input.style.borderColor = "";
    });
    formMessage.textContent = "";
    formMessage.style.color = "var(--text-muted)";
  }

  function showFieldError(input, errorElement, message) {
    if (errorElement) errorElement.textContent = message;
    if (input) input.style.borderColor = "var(--danger)";
  }

  function setMessage(message, color = "var(--text-muted)") {
    formMessage.textContent = message;
    formMessage.style.color = color;
  }

  function setLoading(isLoading) {
    createCompanyBtn.disabled = isLoading;
    createCompanyBtn.textContent = isLoading ? "Processando..." : "Finalizar cadastro";
  }

  function updatePreview() {
    const email = normalizeEmail(ownerEmailInput.value) || "voce@email.com";
    ownerEmailPreview.textContent = email;
  }

  function attachInputCleaner(input, errorKey) {
    if (!input) return;
    input.addEventListener("input", () => {
      if (errorElements[errorKey]) errorElements[errorKey].textContent = "";
      input.style.borderColor = "";
      formMessage.textContent = "";
    });
  }

  attachInputCleaner(companyNameInput, "companyName");
  attachInputCleaner(cnpjCpfInput, "cnpjCpf");
  attachInputCleaner(ownerNameInput, "ownerName");
  attachInputCleaner(ownerEmailInput, "ownerEmail");
  attachInputCleaner(passwordInput, "password");
  attachInputCleaner(confirmPasswordInput, "confirmPassword");

  if (cnpjCpfInput) {
    cnpjCpfInput.addEventListener("input", () => { cnpjCpfInput.value = maskDocument(cnpjCpfInput.value); });
  }

  if (ownerEmailInput) {
    ownerEmailInput.addEventListener("input", () => {
      ownerEmailInput.value = normalizeEmail(ownerEmailInput.value);
      updatePreview();
    });
  }

  // Lógica dos botões de mostrar/ocultar senha com SVGs
  const eyeIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
  const eyeOffIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/></svg>`;

  if (togglePasswordBtn) {
    togglePasswordBtn.addEventListener("click", () => {
      const isPassword = passwordInput.type === "password";
      passwordInput.type = isPassword ? "text" : "password";
      togglePasswordBtn.innerHTML = isPassword ? eyeOffIcon : eyeIcon;
    });
  }

  if (toggleConfirmPasswordBtn) {
    toggleConfirmPasswordBtn.addEventListener("click", () => {
      const isPassword = confirmPasswordInput.type === "password";
      confirmPasswordInput.type = isPassword ? "text" : "password";
      toggleConfirmPasswordBtn.innerHTML = isPassword ? eyeOffIcon : eyeIcon;
    });
  }

  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearErrors();

    const companyName = (companyNameInput.value || "").trim();
    const cnpjCpf = normalizeDocument(cnpjCpfInput.value || "");
    const ownerName = (ownerNameInput.value || "").trim();
    const ownerEmail = normalizeEmail(ownerEmailInput.value || "");
    const password = passwordInput.value || "";
    const confirmPassword = confirmPasswordInput.value || "";

    let hasError = false;

    if (!companyName) { showFieldError(companyNameInput, errorElements.companyName, "Informe o nome da empresa."); hasError = true; }
    
    if (!cnpjCpf) { showFieldError(cnpjCpfInput, errorElements.cnpjCpf, "Informe o CPF ou CNPJ."); hasError = true; } 
    else if (!isValidDocument(cnpjCpf)) { showFieldError(cnpjCpfInput, errorElements.cnpjCpf, "Digite um CPF ou CNPJ válido."); hasError = true; }

    if (!ownerName) { showFieldError(ownerNameInput, errorElements.ownerName, "Informe seu nome."); hasError = true; }

    if (!ownerEmail) { showFieldError(ownerEmailInput, errorElements.ownerEmail, "Informe seu e-mail."); hasError = true; } 
    else if (!isValidEmail(ownerEmail)) { showFieldError(ownerEmailInput, errorElements.ownerEmail, "Digite um e-mail válido."); hasError = true; }

    if (!password) { showFieldError(passwordInput, errorElements.password, "Informe a senha."); hasError = true; } 
    else if (password.length < 6) { showFieldError(passwordInput, errorElements.password, "A senha deve ter pelo menos 6 caracteres."); hasError = true; }

    if (!confirmPassword) { showFieldError(confirmPasswordInput, errorElements.confirmPassword, "Confirme a senha."); hasError = true; } 
    else if (confirmPassword !== password) { showFieldError(confirmPasswordInput, errorElements.confirmPassword, "As senhas não coincidem."); hasError = true; }

    if (hasError) {
      setMessage("Revise os campos destacados e tente novamente.", "var(--danger)");
      return;
    }

    setLoading(true);
    setMessage("Criando empresa e sua conta de acesso...", "var(--text-main)");

    try {
      const response = await fetch("/api/empresas/criar", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({
          company_name: companyName,
          cnpj_cpf: cnpjCpf,
          owner_name: ownerName,
          owner_email: ownerEmail,
          password,
          confirm_password: confirmPassword
        })
      });

      let data = null;
      try { data = await response.json(); } catch (_) { data = null; }

      if (!response.ok) {
        const detail = data?.detail || data?.message || "Não foi possível criar a empresa.";
        setMessage(detail, "var(--danger)");
        setLoading(false);
        return;
      }

      try {
        localStorage.setItem(LAST_CREATED_OWNER_EMAIL_KEY, data?.owner_email || ownerEmail);
      } catch (error) {
        console.error("Erro ao salvar último e-mail criado:", error);
      }

      setMessage(data?.message || "Empresa criada com sucesso. Redirecionando...", "var(--success)");
      setTimeout(() => { window.location.href = "/login"; }, 900);

    } catch (error) {
      console.error("Erro ao criar empresa:", error);
      setMessage("Erro de conexão com o servidor.", "var(--danger)");
      setLoading(false);
    }
  });

  updatePreview();
})();
const apiBaseInput = document.getElementById("apiBase");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const togglePasswordBtn = document.getElementById("togglePasswordBtn");
const hintEl = document.getElementById("hint");
const loginBtn = document.getElementById("loginBtn");

const XC_DEFAULT_API_BASE = "http://127.0.0.1:8000";

function showHint(text, isError) {
  hintEl.textContent = text;
  hintEl.classList.toggle("error", !!isError);
}

function getApiBase() {
  const raw =
    (apiBaseInput && apiBaseInput.value.trim()) ||
    localStorage.getItem("xc_api_base") ||
    XC_DEFAULT_API_BASE;
  return raw.replace(/\/$/, "");
}

if (apiBaseInput && localStorage.getItem("xc_api_base")) {
  apiBaseInput.value = localStorage.getItem("xc_api_base");
}

if (passwordInput && togglePasswordBtn) {
  togglePasswordBtn.addEventListener("click", () => {
    const revealed = passwordInput.type === "password";
    passwordInput.type = revealed ? "text" : "password";
    togglePasswordBtn.classList.toggle("auth-password-toggle--revealed", revealed);
    togglePasswordBtn.setAttribute("aria-label", revealed ? "隐藏密码" : "显示密码");
    togglePasswordBtn.setAttribute("aria-pressed", revealed ? "true" : "false");
  });
}

loginBtn.addEventListener("click", async () => {
  try {
    const base = getApiBase();
    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();
    const response = await fetch(`${base}/auth/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await readResponseJson(response);
    if (!response.ok) {
      const msg = data._notJson ? data._raw || "登录失败" : formatApiDetail(data.detail) || "登录失败";
      throw new Error(msg);
    }
    localStorage.setItem("xc_api_base", base);
    localStorage.setItem("xc_admin_token", data.access_token);
    showHint("登录成功，正在进入 RAG 页面…", false);
    setTimeout(() => {
      window.location.href = "./rag.html";
    }, 300);
  } catch (e) {
    showHint(String(e.message || e), true);
  }
});

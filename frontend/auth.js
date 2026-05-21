// 登录与注册页面逻辑：负责普通用户注册、登录、API 地址持久化和 JWT 写入 localStorage。

const apiBaseInput = document.getElementById("apiBase");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const togglePasswordBtn = document.getElementById("togglePasswordBtn");
const hintEl = document.getElementById("hint");
const registerBtn = document.getElementById("registerBtn");
const loginBtn = document.getElementById("loginBtn");

const XC_DEFAULT_API_BASE = "http://127.0.0.1:8000";

function showHint(text, isError = false) {
  hintEl.textContent = text;
  hintEl.classList.toggle("error", isError);
}

function getApiBase() {
  const raw =
    (apiBaseInput && apiBaseInput.value.trim()) ||
    localStorage.getItem("xc_api_base") ||
    XC_DEFAULT_API_BASE;
  return raw.replace(/\/$/, "");
}

async function postJson(path, body) {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readResponseJson(response);
  if (!response.ok) {
    const msg = data._notJson
      ? data._raw || "请求失败"
      : formatApiDetail(data.detail) || "请求失败";
    throw new Error(msg);
  }
  return data;
}

function saveBaseAndToken(base, token) {
  localStorage.setItem("xc_api_base", base);
  localStorage.setItem("xc_token", token);
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

(() => {
  const session = new URLSearchParams(window.location.search).get("session");
  if (session === "expired" && hintEl) {
    showHint("登录状态已失效（例如长时间未使用或更换了服务端密钥），请重新登录。", true);
  }
})();

if (registerBtn) {
  registerBtn.addEventListener("click", async () => {
    try {
      const username = usernameInput.value.trim();
      const password = passwordInput.value.trim();
      const data = await postJson("/auth/register", { username, password });
      saveBaseAndToken(getApiBase(), data.access_token);
      showHint("注册成功，正在跳转...", false);
      setTimeout(() => {
        window.location.href = "./index.html";
      }, 350);
    } catch (error) {
      showHint(`注册失败: ${error.message}`, true);
    }
  });
}

if (loginBtn) {
  loginBtn.addEventListener("click", async () => {
    try {
      const username = usernameInput.value.trim();
      const password = passwordInput.value.trim();
      const data = await postJson("/auth/login", { username, password });
      saveBaseAndToken(getApiBase(), data.access_token);
      showHint("登录成功，正在跳转...", false);
      setTimeout(() => {
        window.location.href = "./index.html";
      }, 350);
    } catch (error) {
      showHint(`登录失败: ${error.message}`, true);
    }
  });
}

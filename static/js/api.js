// Shared API helpers used across all pages.

const API_BASE = "";

function getToken() {
  return localStorage.getItem("token");
}

function setToken(token) {
  localStorage.setItem("token", token);
}

function clearToken() {
  localStorage.removeItem("token");
}

function isLoggedIn() {
  return !!getToken();
}

function logout() {
  clearToken();
  window.location.href = "index.html";
}

// Wraps fetch(), attaching the JWT Authorization header when present
// and throwing an Error with the API's detail message on failure.
async function apiFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});

  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(API_BASE + path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (data && data.detail) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch (e) {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

// Renders the navbar auth links based on login state.
function renderAuthNav() {
  const authNav = document.getElementById("auth-nav");
  if (!authNav) return;

  if (isLoggedIn()) {
    authNav.innerHTML = `<a class="nav-link" href="#" id="logout-link">Logout</a>`;
    document.getElementById("logout-link").addEventListener("click", (e) => {
      e.preventDefault();
      logout();
    });
  } else {
    authNav.innerHTML = `
      <a class="nav-link" href="login.html">Login</a>
      <a class="nav-link" href="register.html">Register</a>
    `;
  }
}

function showAlert(containerId, message, type = "danger") {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
}

document.addEventListener("DOMContentLoaded", renderAuthNav);

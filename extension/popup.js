// Live API health check for the popup, so a judge can see the backend is reachable before using
// the right-click action.
const API = "https://veridex-api-ubvc.onrender.com";
const statusEl = document.getElementById("status");

fetch(`${API}/health`)
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
  .then(() => {
    statusEl.textContent = "API online";
    statusEl.style.color = "#34d399";
  })
  .catch(() => {
    statusEl.textContent = "API unreachable";
    statusEl.style.color = "#fbbf24";
  });

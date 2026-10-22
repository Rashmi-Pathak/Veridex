// Veridex browser extension (MV3 service worker).
//
// Right-click any image -> "Recover provenance with Veridex" -> the worker fetches the image bytes,
// POSTs them to Veridex's public Soft Binding Resolution API (/matches/byContent), and, on a match,
// pulls the recovered manifest (/manifests/{id}) and renders a provenance card on the page. If the
// image is not in this Veridex instance's registry it says so honestly (a single instance only
// recovers what it has ingested).

const API = "https://veridex-api-ubvc.onrender.com";
const SITE = "https://veridex-web-phi.vercel.app";
const MENU_ID = "veridex-recover";
const MAX_IMAGE_BYTES = 20 * 1024 * 1024; // cap the user-triggered fetch + upload

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Recover provenance with Veridex",
    contexts: ["image"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || !info.srcUrl || !tab?.id) return;
  await inject(tab.id, { state: "loading" });
  try {
    const result = await recover(info.srcUrl);
    await inject(tab.id, result);
  } catch (e) {
    await inject(tab.id, { state: "error", message: String(e && e.message ? e.message : e) });
  }
});

async function recover(srcUrl) {
  if (!/^https?:|^data:image\//i.test(srcUrl)) throw new Error("unsupported image URL");
  const imgResp = await fetch(srcUrl);
  if (!imgResp.ok) throw new Error(`could not fetch the image (${imgResp.status})`);
  const declared = Number(imgResp.headers.get("content-length") || 0);
  if (declared && declared > MAX_IMAGE_BYTES) throw new Error("image is too large");
  const blob = await imgResp.blob();
  if (blob.size > MAX_IMAGE_BYTES) throw new Error("image is too large");

  const fd = new FormData();
  fd.append("file", blob, "image");
  const matchResp = await fetch(`${API}/matches/byContent`, { method: "POST", body: fd });
  if (!matchResp.ok) throw new Error(`Veridex API returned ${matchResp.status}`);
  const matches = (await matchResp.json()).matches || [];
  if (matches.length === 0) return { state: "not-found" };

  const top = matches[0];
  let provenance = null;
  try {
    const mResp = await fetch(`${API}/manifests/${encodeURIComponent(top.manifestId)}`);
    if (mResp.ok) provenance = await mResp.json();
  } catch (_e) {
    provenance = null;
  }
  return {
    state: "found",
    manifestId: top.manifestId,
    similarity: top.similarityScore ?? null,
    provenance,
  };
}

function inject(tabId, data) {
  return chrome.scripting
    .executeScript({ target: { tabId }, func: renderCard, args: [data, API, SITE] })
    .catch((e) => {
      // Restricted pages (chrome://, the Web Store) disallow injection; surface a diagnostic
      // rather than failing silently.
      console.warn("Veridex: could not render the result card:", chrome.runtime.lastError || e);
    });
}

// Runs in the page (no extension APIs available here). Builds a fixed provenance card using only
// createElement + textContent: every dynamic value (manifest id, model, provider, error message)
// is set via textContent, so there is no innerHTML and no HTML-injection surface on the host page.
function renderCard(data, api, site) {
  const ID = "rooted-overlay-card";
  document.getElementById(ID)?.remove();

  const mono = "font-family:ui-monospace,SFMono-Regular,monospace";
  const el = (tag, css, text) => {
    const n = document.createElement(tag);
    if (css) n.style.cssText = css;
    if (text != null) n.textContent = String(text);
    return n;
  };
  const row = (k, v) => {
    const r = el("div", "display:flex;gap:8px;margin-top:2px");
    r.appendChild(el("span", "width:74px;color:#8a90a2;flex:none", k));
    r.appendChild(el("span", "word-break:break-all;color:#cfd3df", v));
    return r;
  };

  const card = el("div");
  card.id = ID;
  card.style.cssText = [
    "position:fixed",
    "top:16px",
    "right:16px",
    "z-index:2147483647",
    "width:320px",
    "padding:14px 16px",
    "border-radius:12px",
    "border:1px solid rgba(255,255,255,0.15)",
    "background:#0b1020",
    "color:#e6e8ee",
    "font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif",
    "box-shadow:0 8px 30px rgba(0,0,0,0.45)",
  ].join(";");

  const header = el(
    "div",
    "display:flex;align-items:center;justify-content:space-between;margin-bottom:8px",
  );
  header.appendChild(
    el(
      "span",
      "font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#8a90a2",
      "Veridex provenance",
    ),
  );
  const close = el("span", "cursor:pointer;color:#8a90a2;font-size:16px;line-height:1", "×");
  close.addEventListener("click", () => card.remove());
  header.appendChild(close);
  card.appendChild(header);

  if (data.state === "loading") {
    card.appendChild(el("div", "color:#9aa0b4;" + mono, "Recovering provenance..."));
  } else if (data.state === "error") {
    card.appendChild(el("div", "color:#fbbf24", "Could not recover: " + data.message));
  } else if (data.state === "not-found") {
    card.appendChild(el("div", "color:#fbbf24", "No provenance found in this Veridex registry."));
    card.appendChild(
      el(
        "div",
        "margin-top:6px;color:#8a90a2;font-size:11px",
        "A single instance only recovers media it has ingested.",
      ),
    );
  } else {
    card.appendChild(el("div", "color:#34d399;font-weight:600;" + mono, "RECOVERED"));
    const box = el("div", "margin-top:8px;font-size:12px;" + mono);
    box.appendChild(row("manifest", String(data.manifestId).slice(0, 34)));
    if (data.similarity != null) box.appendChild(row("similarity", data.similarity + " / 100"));
    const sp = (data.provenance && data.provenance.systemProvenance) || {};
    if (sp.model) box.appendChild(row("model", sp.model));
    if (sp.provider) box.appendChild(row("provider", sp.provider));
    if (sp.generator) box.appendChild(row("generator", sp.generator));
    card.appendChild(box);
    const link = el(
      "a",
      "display:inline-block;margin-top:10px;color:#60a5fa;text-decoration:none;font-size:12px",
      "View on Veridex →",
    );
    link.href = site;
    link.target = "_blank";
    link.rel = "noopener";
    card.appendChild(link);
  }

  document.documentElement.appendChild(card);
}

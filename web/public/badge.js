/* Rooted verify badge: a live provenance seal any site can embed.
 *
 * Usage on any page:
 *   <script src="https://veridex-web-phi.vercel.app/badge.js"
 *           data-manifest="urn:c2pa:demo-0000-0000-0000-000000000001" async></script>
 *
 * The script reads its data-manifest, fetches the live provenance from Rooted's CORS-enabled
 * /badge/<id> endpoint (which reads the real registry and Merkle proof), and renders a compact
 * seal inside a shadow root so the host page's CSS never touches it and the badge's styles never
 * leak out. The seal links to the full receipt permalink. Everything shown is live: VERIFIED comes
 * from the real transparency proof, and an unknown or unreachable registry shows an honest state,
 * never a fake pass.
 */
(function () {
  "use strict";

  var current = document.currentScript;
  if (!current) return;
  var manifestId = current.getAttribute("data-manifest");
  if (!manifestId) return;

  // The origin the badge script was served from is where the /badge endpoint and receipt live.
  var origin = new URL(current.src, window.location.href).origin;

  var host = document.createElement("span");
  host.setAttribute("data-veridex-badge", manifestId);
  current.parentNode.insertBefore(host, current.nextSibling);
  var root = host.attachShadow({ mode: "open" });

  var C = {
    bg: "#0b1210",
    border: "rgba(255,255,255,0.16)",
    text: "#e6e9e7",
    dim: "rgba(230,233,231,0.6)",
    emerald: "#34d399",
    rose: "#fb7185",
    amber: "#fbbf24",
  };

  function el(tag, style, text) {
    var node = document.createElement(tag);
    if (style) node.setAttribute("style", style);
    if (text != null) node.textContent = text;
    return node;
  }

  var base =
    "display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:9px;" +
    "border:1px solid " +
    C.border +
    ";background:" +
    C.bg +
    ";color:" +
    C.text +
    ";font:500 13px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;text-decoration:none;" +
    "box-shadow:0 1px 3px rgba(0,0,0,0.4)";

  function render(state, detail) {
    // replaceChildren (not innerHTML) so nothing is ever parsed as HTML; every value below is set
    // through textContent or an encoded attribute, so host-page content cannot inject markup.
    root.replaceChildren();
    var link = el("a", base);
    link.setAttribute("href", origin + "/r/" + encodeURIComponent(manifestId));
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener");

    var dotColor =
      state === "verified" ? C.emerald : state === "loading" ? C.dim : state === "clash" ? C.rose : C.amber;
    var dot = el(
      "span",
      "width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:" +
        dotColor +
        (state === "verified" ? ";box-shadow:0 0 8px " + C.emerald : ""),
    );

    var labelText =
      state === "verified"
        ? "Provenance verified"
        : state === "loading"
          ? "Checking provenance"
          : state === "notfound"
            ? "No provenance record"
            : "Provenance unavailable";
    var label = el("span", "color:" + C.text, labelText);

    var mark = el("span", "color:" + C.emerald + ";font-weight:700", "Veridex");

    link.appendChild(dot);
    link.appendChild(label);
    if (detail) link.appendChild(el("span", "color:" + C.dim, detail));
    link.appendChild(el("span", "color:" + C.dim, "·"));
    link.appendChild(mark);
    root.appendChild(link);
  }

  render("loading");

  fetch(origin + "/badge/" + encodeURIComponent(manifestId))
    .then(function (r) {
      return r.ok ? r.json() : Promise.reject(new Error(String(r.status)));
    })
    .then(function (d) {
      if (d.status === "notfound") return render("notfound");
      if (d.status !== "found") return render("unknown");
      if (!d.verified) return render("unknown", "proof unverified");
      var detail =
        typeof d.leafIndex === "number" && typeof d.treeSize === "number"
          ? "leaf " + d.leafIndex + " of " + d.treeSize
          : d.model || null;
      render("verified", detail);
    })
    .catch(function () {
      render("unknown");
    });
})();

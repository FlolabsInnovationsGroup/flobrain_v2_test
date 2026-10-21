/* FloBrain website chat. Paste: <script src="https://YOUR-FLOBRAIN/v2/widget.js" data-site="SITE_KEY" async></script>
   Optional: data-lang="ar|en|tr|fr|pt", data-color="#7c5cff", data-label="Chat with us", data-position="left|right".
   It adds a button and, on first click, an iframe with the chat. No cookies, no tracking. */
(function () {
  "use strict";
  const script = document.currentScript;
  if (!script || window.__flobrainChat) return;
  const site = script.getAttribute("data-site") || "";
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(site)) return;
  window.__flobrainChat = true;

  const origin = new URL(script.src, location.href).origin;
  const lang = (script.getAttribute("data-lang") || document.documentElement.lang || "").slice(0, 2).toLowerCase();
  let color = script.getAttribute("data-color") || "#7c5cff";
  if (!/^#[0-9a-fA-F]{3,8}$/.test(color)) color = "#7c5cff";
  const label = script.getAttribute("data-label") || (lang === "ar" ? "تحدث معنا" : "Chat with us");
  let side = script.getAttribute("data-position") || (lang === "ar" ? "left" : "right");
  if (side !== "left") side = "right";

  const button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-expanded", "false");
  button.innerHTML =
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  const b = button.style;
  b.position = "fixed";
  b.bottom = "20px";
  b[side] = "20px";
  b.width = b.height = "56px";
  b.borderRadius = "50%";
  b.border = "0";
  b.background = color;
  b.color = "#fff";
  b.cursor = "pointer";
  b.display = "flex";
  b.alignItems = "center";
  b.justifyContent = "center";
  b.boxShadow = "0 8px 24px rgba(0,0,0,.25)";
  b.zIndex = "2147483646";

  let frame = null;
  let open = false;

  function place() {
    if (!frame) return;
    const f = frame.style;
    const small = window.innerWidth < 480;
    f.position = "fixed";
    f.border = "0";
    f.zIndex = "2147483647";
    f.background = "#0b0a12";
    f.boxShadow = "0 12px 40px rgba(0,0,0,.35)";
    f.borderRadius = small ? "0" : "16px";
    f.top = small ? "0" : "auto";
    f.bottom = small ? "0" : "88px";
    f.left = small ? "0" : side === "left" ? "20px" : "auto";
    f.right = small ? "0" : side === "right" ? "20px" : "auto";
    f.width = small ? "100vw" : "380px";
    f.height = small ? "100dvh" : "min(600px, calc(100vh - 110px))";
  }

  function toggle(next) {
    open = typeof next === "boolean" ? next : !open;
    if (open && !frame) {
      frame = document.createElement("iframe");
      frame.title = label;
      frame.src =
        origin + "/p/chat/" + encodeURIComponent(site) + "?embed=" + encodeURIComponent(location.origin) + (lang ? "&lang=" + encodeURIComponent(lang) : "");
      frame.setAttribute("referrerpolicy", "origin");
      document.body.appendChild(frame);
      place();
    }
    if (frame) frame.style.display = open ? "block" : "none";
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) button.focus();
  }

  button.addEventListener("click", function () {
    toggle();
  });
  window.addEventListener("resize", place);
  window.addEventListener("keydown", function (e) {
    if (open && e.key === "Escape") toggle(false);
  });
  window.addEventListener("message", function (e) {
    if (e.origin === origin && e.data && e.data.type === "flobrain-chat-close") toggle(false);
  });

  function mount() {
    document.body.appendChild(button);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();

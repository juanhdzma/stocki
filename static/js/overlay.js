export function hideTooltip() {
  const el = document.getElementById("tooltip");
  if (el) el.style.display = "none";
}

export function positionTooltip(event, el) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const TW = el.offsetWidth  || 492;
  const TH = el.offsetHeight || 400;
  // For table cells, anchor to the cell's right edge (not the cursor) so the tooltip always sits just
  // to the right of that cell no matter where inside it the mouse is. Charts keep cursor-following.
  const ct = event.currentTarget;
  const rect = ct && ct.tagName === "TD" ? ct.getBoundingClientRect() : null;
  let left = rect ? rect.right + 12 : event.clientX + 18;
  if (left + TW > vw - 8) left = vw - TW - 8;  // clamp to stay on screen, never flip to the left
  let top  = rect ? rect.top - 8 : event.clientY - 30;
  if (top < 60) top = 60;
  if (top + TH > vh - 8) top = Math.max(60, vh - TH - 8);
  el.style.left = left + "px";
  el.style.top  = top + "px";
}

export function showOverlay(event, html) {
  const el = document.getElementById("tooltip");
  el.style.width = "";
  el.innerHTML = html;
  el.style.display = "block";
  positionTooltip(event, el);
}

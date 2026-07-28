export function hideTooltip() {
  const el = document.getElementById("tooltip");
  if (el) el.style.display = "none";
}

export function positionTooltip(event, el) {
  const vh = window.innerHeight;
  const TW = el.offsetWidth  || 492;
  const TH = el.offsetHeight || 400;
  let left = event.clientX - TW - 18;  // always open to the LEFT of the cursor (the old right-edge flip, everywhere)
  if (left < 8) left = 8;
  let top  = event.clientY - 30;
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

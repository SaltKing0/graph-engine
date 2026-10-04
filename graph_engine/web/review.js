// GraphEngine Review — inbox work + same_as linking, keyboard-first.
//
// Security (Audit #11/#12/#14): alle dynamischen Werte (ids, kinds, Text)
// are strictly escaped; interaction runs via data attributes +
// Event-Delegation statt inline onclick-Attributen mit String-Interpolation.
// Ein manipuliertes Brain-Repo (geklontes Remote mit feindlichen ids/kinds)
// kann keinen Code mehr in die Seite injizieren.
const $ = id => document.getElementById(id);

let nodes = {}, pending = [], selectedId = null;
let pickA = null, pickB = null;

// Audit #47: die Selection war positional (Index in pending) und sprang nach
// jedem Refresh auf eine andere Edge. Jetzt wird die Edge-ID gemerkt; der
// Index wird nur noch als Fallback beim ersten Rendern hergeleitet.
function currentIndex() {
  const i = pending.findIndex(e => e.id === selectedId);
  return i >= 0 ? i : 0;
}

function short(id, n = 70) {
  const t = (nodes[id] || { text: id }).text.replace(/\n/g, " ");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

// Strict escaping for element content AND attribute context (audit #14:
// the old version escaped only & and < — insufficient for attributes).
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

function flash(msg, ok = true) {
  const f = $("flash");
  f.textContent = msg;
  f.style.borderColor = ok ? "var(--green)" : "var(--red)";
  f.style.color = ok ? "var(--green)" : "var(--red)";
  f.style.opacity = 1;
  setTimeout(() => f.style.opacity = 0, 1800);
}

// Audit #30: a dead API previously left the page at "0 pending" forever —
// refresh() now surfaces the failure and offers a retry.
async function refresh() {
  let g;
  try {
    const r = await fetch("/api/graph");
    if (!r.ok) throw new Error(`API ${r.status}`);
    g = await r.json();
  } catch (err) {
    $("count").textContent = "API unreachable";
    $("cards").innerHTML =
      `<div style="color:var(--red);font-size:13px;">` +
      `Failed to load graph (${esc(String(err.message || err))}). ` +
      `<button class="ok" id="retryBtn">retry</button></div>`;
    const btn = document.getElementById("retryBtn");
    if (btn) btn.addEventListener("click", refresh);
    return;
  }
  nodes = {};
  g.nodes.forEach(n => nodes[n.id] = n);
  pending = g.edges.filter(e => e.pending && !(e.invalidated ?? Boolean(e.valid_to)));
  if (selectedId == null && pending.length) selectedId = pending[0].id;
  if (selectedId != null && !pending.some(e => e.id === selectedId)) {
    selectedId = pending.length ? pending[0].id : null;
  }
  $("count").textContent = `${pending.length} pending`;
  renderCards();
}

// Audit #30: in-flight lock — key-repeat or double-click spammed resolve POSTs
// (each POST commits; the spam created noisy history and raced the refresh).
let resolving = false;

// ---------- Inbox ----------
function renderCards() {
  const box = $("cards");
  if (!pending.length) {
    box.innerHTML = `<div style="color:var(--dim);font-size:13px;">No open suggestions. 🎉</div>`;
    return;
  }
  const sel = currentIndex();
  box.innerHTML = pending.map((e, i) => `
    <div class="card ${i === sel ? "active" : ""}" data-i="${i}">
      <span class="kind" data-kind="${esc(e.kind)}">${esc(e.kind === "fact" ? e.predicate || "fact" : e.kind)}</span>
      <div class="side-label">A</div>
      <div class="nodebox pickable" data-pick="${esc(e.source)}">
        <span class="id">${esc(e.source)}</span><br>${esc(short(e.source))}</div>
      <div class="side-label">B</div>
      <div class="nodebox pickable" data-pick="${esc(e.target)}">
        <span class="id">${esc(e.target)}</span><br>${esc(short(e.target))}</div>
      ${e.kind === "fact" ? (e.evidence || []).slice(0, 3).map(item => `<p>${esc(item.text.slice(0, 240))}</p>`).join("") : ""}
      <div class="actions">
        <button class="ok" data-resolve="${esc(e.id)}" data-accept="1">✓ accept ⏎</button>
        <button class="no" data-resolve="${esc(e.id)}" data-accept="0">✗ reject esc</button>
      </div>
    </div>`).join("");
  const active = box.querySelector(".card.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

// Event-Delegation: kein inline onclick mit interpolierten ids mehr.
document.addEventListener("click", ev => {
  const resolveBtn = ev.target.closest("[data-resolve]");
  if (resolveBtn) {
    resolve(resolveBtn.dataset.resolve, resolveBtn.dataset.accept === "1");
    return;
  }
  const pickable = ev.target.closest("[data-pick]");
  if (pickable) pickable.blur();
});

document.addEventListener("click", ev => {
  const box = ev.target.closest(".nodebox.pickable[data-pick]");
  if (box) pick(box.dataset.pick);
});

async function resolve(id, accept) {
  if (resolving) return;
  resolving = true;
  try {
    const r = await fetch(`/api/edge/${encodeURIComponent(id)}/${accept ? "accept" : "reject"}`, { method: "POST" });
    if (!r.ok) return flash("Failed to resolve", false);
    flash(accept ? "Edge accepted" : "Edge rejected");
    await refresh();
    // Audit #50: after accepting, focus landed on the next card's first button
    // (the pickable nodebox) — keyboard users expect the Accept button.
    const active = document.querySelector(".card.active button.ok");
    if (active) active.focus();
  } catch (err) {
    flash("Network error: " + String(err.message || err), false);
  } finally {
    resolving = false;
  }
}

// ---------- same_as-Picker ----------
function pick(id) {
  if (pickA === id || pickB === id) return; // never link a node to itself
  if (!pickA) pickA = id;
  else if (!pickB) pickB = id;
  else { pickA = id; pickB = null; } // third click restarts the pick
  renderPick();
}

window.pickFromCard = (id, el) => { pick(id); el.blur(); };

function renderPick() {
  const a = $("slotA"), b = $("slotB"), btn = $("linkbtn");
  a.textContent = "A: " + (pickA ? short(pickA, 40) : "empty");
  b.textContent = "B: " + (pickB ? short(pickB, 40) : "empty");
  a.classList.toggle("filled", !!pickA);
  b.classList.toggle("filled", !!pickB);
  btn.disabled = !(pickA && pickB);
  btn.textContent = pickA && pickB
    ? `${short(pickA, 12)} ⇄ ${short(pickB, 12)} ⏎` : "link ⏎";
}

async function link() {
  if (!(pickA && pickB)) return;
  const r = await fetch("/api/edge", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: pickA, target: pickB, kind: "same_as" }),
  });
  if (!r.ok) { const e = await r.json().catch(() => ({})); return flash(e.error || "Link failed", false); }
  flash("same_as linked");
  pickA = pickB = null;
  renderPick();
  await refresh();
}

// Search
$("search").addEventListener("input", () => {
  const q = $("search").value.trim().toLowerCase();
  const hits = $("hits");
  if (!q) return hits.innerHTML = "";
  const found = Object.values(nodes)
    .filter(n => n.text.toLowerCase().includes(q)).slice(0, 8);
  hits.innerHTML = found.map(n =>
    `<div class="hit ${n.id === pickA ? "pickedA" : ""} ${n.id === pickB ? "pickedB" : ""}"
          data-pick="${esc(n.id)}"><span class="id">${esc(n.id.slice(0, 8))}</span>${esc(short(n.id, 55))}</div>`).join("");
});

window.searchPick = id => { pick(id); $("search").value = ""; $("hits").innerHTML = ""; };

$("linkbtn").addEventListener("click", link);

// ---------- Keyboard ----------
document.addEventListener("keydown", e => {
  const inField = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  // Audit #30: key-repeat fired Enter/Escape once per auto-repeat tick —
  // one held key spammed resolve POSTs. Auto-repeats are ignored.
  if (e.repeat && (e.key === "Enter" || e.key === "Escape")) return;
  // Audit #50: Ctrl/Meta/Alt chords must not trigger shortcuts (Ctrl+S hijacked).
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "s": if (!inField) { e.preventDefault(); $("search").focus(); } break;
    case "x": if (!inField && (pickA || pickB)) { pickA = pickB = null; renderPick(); } break;
    case "j": if (!inField && pending.length) { selectedId = pending[Math.min(currentIndex() + 1, pending.length - 1)].id; renderCards(); } break;
    case "k": if (!inField && pending.length) { selectedId = pending[Math.max(currentIndex() - 1, 0)].id; renderCards(); } break;
    case "Enter":
      if (inField) break;
      if (pickA && pickB) link();
      else if (pending[currentIndex()]) resolve(pending[currentIndex()].id, true);
      break;
    case "Escape":
      if (inField) { document.activeElement.blur(); }
      else if (pending[currentIndex()]) resolve(pending[currentIndex()].id, false);
      break;
  }
});

refresh();

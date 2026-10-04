// GraphEngine: explore ideas, review connections, and undo saved decisions.
(() => {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const colors = { "similar": "#6ed5a0", "contradicts": "#ff9393", "extends": "#83b9ff", "same_as": "#bc8cff", "supersedes": "#f0883e", "continues": "#58a6ff" };
  const labels = { "similar": "Similar", "contradicts": "Contradiction", "extends": "Extension", "same_as": "Same idea", "supersedes": "Supersedes", "continues": "Continues" };
  const edgeLabel = edge => edge.kind === "fact" ? edge.predicate || "Fact" : labels[edge.kind] || edge.kind;
  const esc = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Audit #50: slice by code points — UTF-16 indexing split surrogate pairs (emoji).
const short = (text, length = 36) => {
  const chars = Array.from(text);
  return chars.length > length ? `${chars.slice(0, length - 1).join("")}…` : text;
};
  const idOf = value => typeof value === "object" ? value.id : value;
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let nodes = [], edges = [], links = [], pending = [];
  let selectedEdge = null, selectedNode = null, detailId = null, undoId = null;
  let loaded = false, saving = false, resolving = false, refreshVersion = 0;
  let noticeTimer, reconnectTimer, socket, width = 1, height = 1;
  let initialFit = true, graph3D = null, use3D = false;
  const sprites = new Map();
  const nodeById = id => nodes.find(node => node.id === id);
  const textOf = id => nodeById(id)?.text || "Idea unavailable";

  function notify(message, error = false) {
    clearTimeout(noticeTimer);
    $("#notice").textContent = message;
    $("#notice").classList.toggle("error", error);
    noticeTimer = setTimeout(() => { $("#notice").textContent = ""; }, error ? 8000 : 4000);
  }

  // Keep the rest of the page understandable if the graph library cannot load.
  if (!window.d3) {
    $("#graph-empty h2").textContent = "The graph could not be loaded";
    $("#graph-empty p").textContent = "Check your connection and reload the page.";
    $("#stats").textContent = "Graph unavailable";
    $("#connection").textContent = "Load failed";
    $("#empty-action").hidden = false;
    $("#empty-action").textContent = "Reload";
    $("#empty-action").onclick = () => location.reload();
    $("#ingest-button").disabled = true;
    $("#bar").addEventListener("submit", event => event.preventDefault());
    return;
  }

  const svg = d3.select("#graph");
  const viewport = svg.append("g");
  const linkLayer = viewport.append("g").attr("aria-hidden", "true");
  const nodeLayer = viewport.append("g");
  const zoom = d3.zoom().scaleExtent([0.12, 4]).on("zoom", event => {
    viewport.attr("transform", event.transform);
    $("#tooltip").hidden = true;
  });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", event => { if (event.target === svg.node()) clearSelection(); });
  const simulation = d3.forceSimulation()
    .force("link", d3.forceLink().id(node => node.id).distance(190))
    .force("charge", d3.forceManyBody().strength(-550))
    .force("collide", d3.forceCollide(65))
    .force("center", d3.forceCenter())
    .on("tick", tick)
    .on("end", () => { if (initialFit && nodes.length) { fitNodes(nodes); initialFit = false; } });

  function tick() {
    linkLayer.selectAll("line")
      .attr("x1", edge => edge.source.x).attr("y1", edge => edge.source.y)
      .attr("x2", edge => edge.target.x).attr("y2", edge => edge.target.y);
    nodeLayer.selectAll("g.node").attr("transform", node => `translate(${node.x},${node.y})`);
  }

  function drawGraph() {
    linkLayer.selectAll("line").data(links, edge => edge.id).join("line")
      .attr("stroke", edge => colors[edge.kind] || "#a0afc1")
      .attr("stroke-dasharray", edge => edge.pending ? "5 6" : null);
    const groups = nodeLayer.selectAll("g.node").data(nodes, node => node.id).join(enter => {
      const group = enter.append("g").attr("class", "node").attr("tabindex", 0).attr("role", "button")
        .on("click", (event, node) => { event.stopPropagation(); showDetail(node.id); })
        .on("keydown", (event, node) => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); showDetail(node.id); }
        })
        .on("pointerenter", (event, node) => {
          if (event.pointerType === "touch") return;
          const tooltip = $("#tooltip");
          tooltip.textContent = short(node.text, 240);
          tooltip.hidden = false;
          const rect = $("#canvas").getBoundingClientRect();
          tooltip.style.left = `${Math.max(8, Math.min(event.clientX - rect.left + 16, rect.width - tooltip.offsetWidth - 8))}px`;
          tooltip.style.top = `${Math.max(8, Math.min(event.clientY - rect.top + 16, rect.height - tooltip.offsetHeight - 8))}px`;
        })
        .on("pointerleave", () => { $("#tooltip").hidden = true; })
        .call(d3.drag()
          .on("start", (event, node) => { initialFit = false; if (!event.active) simulation.alphaTarget(.2).restart(); node.fx = node.x; node.fy = node.y; })
          .on("drag", (event, node) => { node.fx = event.x; node.fy = event.y; })
          .on("end", (event, node) => { if (!event.active) simulation.alphaTarget(0); node.fx = null; node.fy = null; }));
      group.append("circle").attr("class", "halo").attr("r", 20);
      group.append("circle").attr("class", "dot").attr("r", 9);
      group.append("text").attr("text-anchor", "middle").attr("y", -29);
      group.append("title");
      return group;
    });
    groups.attr("aria-label", node => `Open idea: ${node.text}`);
    groups.select("text").text(node => short(node.text.replace(/\s+/g, " ")));
    groups.select("title").text(node => node.text);
    if (graph3D) update3D();
    highlight();
    tick();
  }

  function highlight() {
    const selected = pending.find(edge => edge.id === selectedEdge) || edges.find(edge => edge.id === selectedEdge);
    const ids = new Set(selected ? [selected.source, selected.target] : selectedNode ? [selectedNode] : []);
    const searching = $("#search").value.trim().toLowerCase();
    if (graph3D) {
      graph3D.nodeColor(node => (ids.size ? !ids.has(node.id) : searching && !node.text.toLowerCase().includes(searching)) ? "#303b49" : ids.has(node.id) ? "#83b9ff" : "#eaf0f7");
      for (const [id, sprite] of sprites) {
        sprite.material.opacity = (ids.size ? !ids.has(id) : searching && !sprite.text.toLowerCase().includes(searching)) ? .2 : 1;
      }
      graph3D.linkColor(edge => ids.size && !(selected ? edge.id === selectedEdge : ids.has(idOf(edge.source)) || ids.has(idOf(edge.target))) ? "#202a36" : colors[edge.kind] || "#a0afc1");
      graph3D.linkWidth(edge => edge.id === selectedEdge ? 2.5 : edge.pending ? .4 : 1);
    }
    nodeLayer.selectAll(".node")
      .classed("selected", node => ids.has(node.id))
      .classed("dimmed", node => ids.size ? !ids.has(node.id) : searching ? !node.text.toLowerCase().includes(searching) : false);
    linkLayer.selectAll("line")
      .attr("stroke-width", edge => edge.id === selectedEdge ? 3 : 1.5)
      .attr("opacity", edge => ids.size ? (selected ? edge.id === selectedEdge : ids.has(idOf(edge.source)) || ids.has(idOf(edge.target))) ? 1 : .08 : edge.pending ? .5 : .75);
  }

  function fitNodes(targets) {
    if (!targets.length || width < 2 || height < 2) return;
    if (use3D && graph3D) {
      const ids = new Set(targets.map(node => node.id));
      graph3D.zoomToFit(motion.matches ? 0 : 280, 60, node => ids.has(node.id));
      return;
    }
    const x0 = d3.min(targets, node => node.x) - 130, x1 = d3.max(targets, node => node.x) + 130;
    const y0 = d3.min(targets, node => node.y) - 65, y1 = d3.max(targets, node => node.y) + 65;
    const scale = Math.max(.12, Math.min(1.5, width / (x1 - x0), height / (y1 - y0)) * .85);
    const transform = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    svg.interrupt().transition().duration(motion.matches ? 0 : 280).call(zoom.transform, transform);
  }

  new ResizeObserver(entries => {
    const rect = entries[0].contentRect;
    if (!rect.width || !rect.height) return;
    width = rect.width; height = rect.height;
    if (graph3D) graph3D.width(width).height(height);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    simulation.force("center").x(width / 2).y(height / 2);
    simulation.alpha(.2).restart();
    // Audit #45: auto-fit only until the user pans/zooms themselves — otherwise
    // every resize oscillation (mobile URL bar) clobbers the user's view.
    if (loaded && initialFit) {
      const edge = pending.find(item => item.id === selectedEdge) || edges.find(item => item.id === selectedEdge);
      const targets = edge ? nodes.filter(node => node.id === edge.source || node.id === edge.target) : selectedNode ? nodes.filter(node => node.id === selectedNode) : nodes;
      fitNodes(targets);
    }
  }).observe($("#canvas"));

  function setView(view) {
    document.body.dataset.view = view;
    document.querySelectorAll("#mobile-tabs button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
  }
  document.querySelectorAll("#mobile-tabs button").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#zoom-in").onclick = () => { initialFit = false; if (use3D) zoom3D(1 / 1.3); else svg.call(zoom.scaleBy, 1.3); };
  $("#zoom-out").onclick = () => { initialFit = false; if (use3D) zoom3D(1.3); else svg.call(zoom.scaleBy, 1 / 1.3); };
  $("#fit").onclick = () => { clearSelection(); fitNodes(nodes); };
  svg.on("wheel.intent pointerdown.intent", () => { initialFit = false; });

  // Keep the upstream WebGL view, with independent simulation objects so the
  // 2D and 3D force engines never overwrite one another's positions.
  function label3D(node) {
    if (sprites.has(node.id)) return sprites.get(node.id).object;
    const canvas = document.createElement("canvas");
    canvas.width = 640; canvas.height = 96;
    const context = canvas.getContext("2d");
    context.font = "32px system-ui, sans-serif";
    context.textAlign = "center"; context.textBaseline = "middle";
    context.fillStyle = "#eaf0f7";
    context.fillText(short(node.text, 30), 320, 48, 620);
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map:texture, transparent:true, depthWrite:false });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(65, 10, 1); sprite.position.y = 12;
    const object = new THREE.Group(); object.add(sprite);
    sprites.set(node.id, { object, texture, material, text:node.text });
    return object;
  }

  function update3D() {
    const existing = new Map(graph3D.graphData().nodes.map(node => [node.id, node]));
    const degree = new Map();
    edges.forEach(edge => [edge.source, edge.target].forEach(id => degree.set(id, (degree.get(id) || 0) + 1)));
    for (const [id, sprite] of sprites) {
      if (nodeById(id)?.text !== sprite.text) {
        sprite.texture.dispose(); sprite.material.dispose(); sprites.delete(id);
      }
    }
    const data = nodes.map(node => Object.assign(existing.get(node.id) || {}, { id:node.id, text:node.text, val:1 + Math.log2(1 + (degree.get(node.id) || 0)) }));
    graph3D.graphData({ nodes:data, links:edges.map(edge => ({ ...edge })) });
    graph3D.nodeThreeObject(label3D);
  }

  function zoom3D(factor) {
    const camera = graph3D.camera().position;
    const target = graph3D.controls().target;
    graph3D.cameraPosition({
      x:target.x + (camera.x - target.x) * factor,
      y:target.y + (camera.y - target.y) * factor,
      z:target.z + (camera.z - target.z) * factor,
    }, target, motion.matches ? 0 : 200);
  }

  $("#graph-mode").onclick = () => {
    try {
      if (!graph3D) {
        if (!window.ForceGraph3D || !window.THREE) throw new Error("3D unavailable");
        graph3D = ForceGraph3D()($("#graph3d"))
          .width(width).height(height).backgroundColor("#0d1117")
          .nodeRelSize(5).nodeLabel(node => esc(node.text))
          .nodeThreeObjectExtend(true).nodeThreeObject(label3D)
          .linkOpacity(.65).linkLabel(edge => esc(`${edgeLabel(edge)}${edge.pending ? " · Suggestion" : ""}`))
          .onNodeClick(node => showDetail(node.id)).onBackgroundClick(clearSelection)
          .warmupTicks(80).cooldownTicks(100);
        update3D();
      }
      use3D = !use3D;
      $("#graph3d").hidden = !use3D; $("#graph").hidden = use3D;
      $("#graph-mode").setAttribute("aria-pressed", String(use3D));
      if (use3D) graph3D.resumeAnimation(); else graph3D.pauseAnimation();
      highlight(); fitNodes(nodes);
    } catch {
      graph3D?.pauseAnimation(); graph3D = null; use3D = false;
      $("#graph3d").hidden = true; $("#graph").hidden = false;
      $("#graph-mode").setAttribute("aria-pressed", "false");
      notify("3D is unavailable here. You can keep using the graph in 2D.");
    }
  };

  function clearSelection() {
    selectedEdge = null; selectedNode = null;
    document.querySelectorAll(".card").forEach(card => card.classList.remove("active"));
    highlight();
  }

  function selectEdge(id, reveal = false) {
    selectedEdge = id; selectedNode = null; initialFit = false;
    const edge = pending.find(item => item.id === id) || edges.find(item => item.id === id);
    if (!edge) return;
    document.querySelectorAll(".card").forEach(card => card.classList.toggle("active", card.dataset.id === id));
    if (reveal) setView("graph");
    highlight();
    requestAnimationFrame(() => fitNodes(nodes.filter(node => node.id === edge.source || node.id === edge.target)));
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
      const error = new Error(response.status === 404 || response.status === 409 ? "This suggestion was already changed. Please pick it again." : "Saving failed. Please try again.");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  // Audit #46: one action triggered two full /api/graph fetches (explicit +
  // the actor's own WS broadcast). A 100ms trailing debounce collapses both into one.
  let refreshTimer = null;
  function scheduleRefresh(delay = 100) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, delay);
  }

  async function refresh() {
    clearTimeout(refreshTimer);
    const version = ++refreshVersion;
    try {
      const graph = await request("/api/graph");
      if (version !== refreshVersion) return;
      const existing = new Map(nodes.map(node => [node.id, node]));
      nodes = graph.nodes.map(node => Object.assign(existing.get(node.id) || {}, node));
      const ids = new Set(nodes.map(node => node.id));
      const eligible = graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target) && !edge.rejected);
      edges = eligible.filter(edge => edge.current ?? !edge.valid_to);
      links = edges.map(edge => ({ ...edge }));
      // Historical and scheduled facts still need review, even off the live graph.
      pending = eligible.filter(edge => edge.pending && !(edge.invalidated ?? Boolean(edge.valid_to)));
      if (!pending.some(edge => edge.id === selectedEdge)) selectedEdge = null;
      if (!ids.has(selectedNode)) selectedNode = null;
      // Clear old links before replacing nodes, so deleted endpoints cannot leak into the simulation.
      simulation.force("link").links([]);
      simulation.nodes(nodes);
      simulation.force("link").links(links);
      loaded = true;
      $("#stats").textContent = `${nodes.length} ${nodes.length === 1 ? "idea" : "ideas"} · ${edges.filter(edge => !edge.pending).length} connections`;
      $("#pending-count").textContent = pending.length;
      $("#mobile-count").textContent = pending.length ? `(${pending.length})` : "";
      $("#graph-empty").hidden = nodes.length > 0;
      $("#graph-empty h2").textContent = "Every connection starts with an idea";
      $("#graph-empty p").textContent = "Capture your first thought. More ideas will surface connection suggestions.";
      $("#empty-action").hidden = false;
      $("#empty-action").textContent = "Add your first idea";
      $("#empty-action").onclick = () => $("#text").focus();
      renderCards(); drawGraph();
      simulation.alpha(.6).restart();
      if (initialFit && nodes.length) { simulation.tick(80); tick(); fitNodes(nodes); initialFit = false; }
      if (detailId) renderDetail(detailId);
      if (document.activeElement === $("#search")) renderSearch();
    } catch (error) {
      if (version !== refreshVersion) return;
      if (!loaded) {
        $("#stats").textContent = "Ideas not loaded";
        $("#graph-empty h2").textContent = "Your ideas could not be loaded";
        $("#graph-empty p").textContent = "Check the connection and try again.";
        $("#empty-action").hidden = false;
        $("#empty-action").textContent = "Try again";
        $("#empty-action").onclick = refresh;
        $("#cards").innerHTML = '<div class="empty-inbox"><p>Suggestions are available once the connection is restored.</p></div>';
        // Audit #50: the badge kept saying "Connecting …" forever when the very
        // first load failed (WS had not flipped it yet).
        $("#connection").dataset.state = "offline";
        $("#connection").textContent = "Load failed";
      }
      notify("The graph could not be refreshed. Please try again.", true);
    } finally {
      $("#cards").setAttribute("aria-busy", "false");
    }
  }

  function renderCards() {
    const cards = $("#cards");
    const active = document.activeElement;
    const focusedId = active?.closest(".card")?.dataset.id;
    const focusedAction = active?.dataset.action;
    if (!pending.length) {
      cards.innerHTML = `<div class="empty-inbox"><h3>${nodes.length ? "All reviewed" : "Room for new connections"}</h3><p>${nodes.length ? "There are no open suggestions right now. Add more ideas to discover new connections." : "Once your ideas form connections, you can review them here."}</p></div>`;
      return;
    }
    cards.innerHTML = pending.map(edge => `
      <article class="card ${edge.id === selectedEdge ? "active" : ""}" data-id="${esc(edge.id)}">
        <div class="card-heading"><span class="kind" data-kind="${esc(edge.kind)}">${esc(edgeLabel(edge))}</span><button class="select-pair quiet" data-action="select">Show in graph</button></div>
        <button class="idea-preview" data-action="source" aria-label="Read first idea in full"><span class="excerpt">${esc(textOf(edge.source))}</span><span class="read">Read idea ↗</span></button>
        <button class="idea-preview" data-action="target" aria-label="Read second idea in full"><span class="excerpt">${esc(textOf(edge.target))}</span><span class="read">Read idea ↗</span></button>
        ${edge.kind === "fact" ? (edge.evidence || []).slice(0, 3).map(item => `<p class="fact-evidence">${esc(short(item.text, 240))}</p>`).join("") : ""}
        <div class="actions"><button class="ok" data-action="accept" ${resolving ? "disabled" : ""}>&#10003; Accept</button><button class="quiet" data-action="reject" ${resolving ? "disabled" : ""}>Dismiss</button></div>
      </article>`).join("");
    if (focusedId && focusedAction) {
      const card = [...cards.children].find(item => item.dataset.id === focusedId);
      card?.querySelector(`[data-action="${focusedAction}"]`)?.focus({ preventScroll:true });
    }
  }

  $("#cards").addEventListener("click", event => {
    const card = event.target.closest(".card");
    if (!card) return;
    const edge = pending.find(item => item.id === card.dataset.id);
    if (!edge) return;
    const action = event.target.closest("button")?.dataset.action;
    if (action === "accept" || action === "reject") resolveEdge(edge.id, action);
    else if (action === "source" || action === "target") { selectEdge(edge.id); showDetail(edge[action]); }
    else selectEdge(edge.id, action === "select");
  });

  function setResolving(value) {
    resolving = value;
    document.querySelectorAll('[data-action="accept"], [data-action="reject"], #undo').forEach(button => { button.disabled = value; });
  }

  async function resolveEdge(id, action) {
    if (resolving) return;
    const index = pending.findIndex(edge => edge.id === id);
    const focusInCard = Boolean(document.activeElement.closest(".card"));
    setResolving(true);
    try {
      await request(`/api/edge/${encodeURIComponent(id)}/${action}`, { method:"POST" });
      undoId = id;
      $("#decision").hidden = false;
      $("#decision-message").textContent = action === "accept" ? "Connection accepted." : "Suggestion dismissed.";
      await refresh();
      setResolving(false);
      const next = pending[Math.min(index, pending.length - 1)];
      if (next) {
        selectEdge(next.id);
        if (focusInCard) [...$("#cards").children].find(card => card.dataset.id === next.id)?.querySelector("button")?.focus();
      } else if (focusInCard) $("#undo").focus();
    } catch (error) {
      notify(error instanceof TypeError ? "No connection. Your decision was not confirmed." : error.message, true);
      await refresh();
    } finally { setResolving(false); }
  }

  $("#undo").onclick = async () => {
    if (!undoId || resolving) return;
    setResolving(true);
    try {
      const id = undoId;
      await request(`/api/edge/${encodeURIComponent(id)}/undo`, { method:"POST" });
      undoId = null;
      $("#decision").hidden = true;
      await refresh();
      selectEdge(id);
      [...$("#cards").children].find(card => card.dataset.id === id)?.querySelector("button")?.focus();
      notify("Decision undone.");
    } catch (error) {
      notify(error instanceof TypeError ? "No connection. The undo was not confirmed." : error.message, true);
    } finally { setResolving(false); }
  };
  $("#dismiss-decision").onclick = () => { $("#decision").hidden = true; undoId = null; };

  $("#bar").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $("#text");
    const text = input.value.trim();
    if (!text || saving) return;
    saving = true;
    $("#ingest-button").disabled = true;
    $("#ingest-button").textContent = "Saving …";
    try {
      const result = await request("/api/ingest", { method:"POST", headers:{ "Content-Type":"application/json" }, body:JSON.stringify({ text, source:$("#source").value }) });
      if (input.value.trim() === text) input.value = "";
      await refresh();
      selectedEdge = null; selectedNode = result.node.id;
      setView("graph"); highlight(); fitNodes(nodes.filter(node => node.id === selectedNode));
      notify(result.duplicate ? "Duplicate detected and merged into the existing idea." : "Idea saved.");
    } catch (error) {
      notify(error instanceof TypeError ? "No connection. Your text is preserved. Check the graph before retrying." : error.message, true);
    } finally {
      saving = false;
      $("#ingest-button").disabled = false;
      $("#ingest-button").textContent = "Add idea";
    }
  });
  $("#text").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("#bar").requestSubmit(); }
  });

  function renderDetail(id) {
    const node = nodeById(id);
    if (!node) { $("#detail").close(); return; }
    $("#detail-text").textContent = node.text;
    const date = new Date(node.created);
    $("#detail-meta").textContent = [node.entity_type, ...(node.aliases || []), node.source, Number.isNaN(date.getTime()) ? null : date.toLocaleDateString("en-US"), ...(node.tags || []).map(tag => `#${tag}`)].filter(Boolean).join(" · ");
    const relations = edges.filter(edge => edge.source === id || edge.target === id);
    $("#detail-relations").innerHTML = `<h3>Connections (${relations.length})</h3>${relations.map(edge => {
      const target = edge.source === id ? edge.target : edge.source;
      return `<button class="relation quiet" data-node="${esc(target)}"><span>${esc(edgeLabel(edge))}${edge.pending ? " · Suggestion" : " · Accepted"}</span>${esc(short(textOf(target), 160))}</button>`;
    }).join("") || '<p style="color:var(--dim)">No connections yet.</p>'}`;
  }
  function showDetail(id) {
    if (!nodeById(id)) return;
    detailId = id;
    $("#tooltip").hidden = true;
    renderDetail(id);
    if (!$("#detail").open) $("#detail").showModal();
    $("#detail").scrollTop = 0;
  }
  $("#detail-relations").onclick = event => {
    const button = event.target.closest("button[data-node]");
    if (button) { showDetail(button.dataset.node); $("#close-detail").focus(); }
  };
  $("#close-detail").onclick = () => $("#detail").close();
  $("#detail").addEventListener("close", () => { detailId = null; });
  $("#detail").addEventListener("click", event => {
    const rect = $("#detail").getBoundingClientRect();
    if (event.target === $("#detail") && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) $("#detail").close();
  });

  function closeSearch() { $("#search-results").hidden = true; $("#search").setAttribute("aria-expanded", "false"); }
  function renderSearch() {
    const query = $("#search").value.trim().toLowerCase();
    highlight();
    if (!query) { closeSearch(); return; }
    const matches = nodes.filter(node => node.text.toLowerCase().includes(query)).slice(0, 12);
    $("#search-results").innerHTML = matches.map(node => `<li><button data-node="${esc(node.id)}">${esc(short(node.text, 100))}</button></li>`).join("") || '<li class="no-results">No matching idea found.</li>';
    $("#search-results").hidden = false;
    $("#search").setAttribute("aria-expanded", "true");
  }
  $("#search").addEventListener("input", () => { clearSelection(); renderSearch(); });
  $("#search").addEventListener("focus", renderSearch);
  $("#search").addEventListener("keydown", event => {
    if (event.key === "ArrowDown") { event.preventDefault(); $("#search-results button")?.focus(); }
    if (event.key === "Enter") { event.preventDefault(); $("#search-results button")?.click(); }
  });
  $("#search-results").addEventListener("keydown", event => {
    const buttons = [...document.querySelectorAll("#search-results button")];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      buttons[Math.max(0, Math.min(buttons.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))]?.focus();
    }
  });
  $("#search-results").addEventListener("click", event => {
    const button = event.target.closest("button[data-node]");
    if (!button) return;
    selectedEdge = null; selectedNode = button.dataset.node; initialFit = false;
    $("#search").value = ""; closeSearch(); highlight();
    fitNodes(nodes.filter(node => node.id === selectedNode));
    $("#search").focus(); showDetail(selectedNode);
  });
  document.addEventListener("pointerdown", event => { if (!event.target.closest(".search")) closeSearch(); });
  document.addEventListener("focusin", event => { if (!event.target.closest(".search")) closeSearch(); });

  window.addEventListener("keydown", event => {
    if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey || $("#detail").open) return;
    if (event.key === "Escape") {
      closeSearch(); $("#search").value = ""; clearSelection();
      if (document.activeElement.matches("input,textarea")) document.activeElement.blur();
      return;
    }
    if (event.target.closest("input,textarea,select,[contenteditable='true']")) return;
    // Native controls retain Enter/Space; shortcuts must never trigger a second action.
    if (event.target.closest("button,[role='button']") && ["Enter", " "].includes(event.key)) return;
    if (event.key.toLowerCase() === "i") { event.preventDefault(); $("#text").focus(); }
    else if (event.key === "/") { event.preventDefault(); setView("graph"); $("#search").focus(); }
    else if (["j", "k"].includes(event.key.toLowerCase()) && pending.length) {
      event.preventDefault();
      const index = pending.findIndex(edge => edge.id === selectedEdge);
      const next = index < 0 ? (event.key.toLowerCase() === "j" ? 0 : pending.length - 1) : Math.max(0, Math.min(pending.length - 1, index + (event.key.toLowerCase() === "j" ? 1 : -1)));
      selectEdge(pending[next].id);
      document.querySelector(".card.active")?.scrollIntoView({ block:"nearest" });
    } else if (event.key === "Enter" && selectedEdge) { event.preventDefault(); if (!event.repeat) resolveEdge(selectedEdge, "accept"); }
    else if (event.key === " ") {
      const id = selectedNode || pending.find(edge => edge.id === selectedEdge)?.target;
      if (id) { event.preventDefault(); showDetail(id); }
    }
  });

  // Audit #44: a half-open connection (laptop sleep, NAT timeout) kept showing
  // "Live connected" while updates silently stopped. Ping every 25 s; if no
  // reply arrives, the connection is considered dead and the reconnect (now
  // exponential backoff + jitter instead of a fixed 5 s) takes over.
  let attempts = 0, heartbeatTimer = null, awaitingPong = false;
  function stopHeartbeat() { clearInterval(heartbeatTimer); }
  // Stale check: send() on a half-open connection does not throw immediately —
  // the server never answers, but the state machine stays OPEN. If 10 s after
  // the ping neither a message nor a close arrived, close hard; onclose
  // handles the backoff reconnect.
  function startHeartbeatWithStaleCheck() {
    stopHeartbeat();
    heartbeatTimer = setInterval(() => {
      if (socket?.readyState !== WebSocket.OPEN) return;
      awaitingPong = true;
      try { socket.send("ping"); } catch { socket.close(); return; }
      setTimeout(() => {
        if (awaitingPong && socket?.readyState === WebSocket.OPEN) socket.close(); // stale → onclose reconnects
      }, 10000);
    }, 25000);
  }

  function connect() {
    clearTimeout(reconnectTimer);
    stopHeartbeat();
    socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    socket.onopen = () => {
      attempts = 0;
      $("#connection").dataset.state = "live";
      $("#connection").textContent = "Live connected";
      startHeartbeatWithStaleCheck();
      refresh();
    };
    socket.onmessage = event => {
      awaitingPong = false;
      try { if (["ingested", "edge_resolved", "edge_restored", "edge_linked"].includes(JSON.parse(event.data).type)) scheduleRefresh(); } catch { /* Ignore unknown live messages. */ }
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      stopHeartbeat();
      $("#connection").dataset.state = "offline";
      $("#connection").textContent = "Live connection lost";
      // Exponential backoff with jitter: 1s, 2s, 4s … max 60s — a downed server
      // is no longer hammered on a fixed 5s cadence.
      const delay = Math.min(60000, 1000 * 2 ** attempts) * (0.75 + Math.random() * 0.5);
      attempts += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
  }
  refresh(); connect();
})();

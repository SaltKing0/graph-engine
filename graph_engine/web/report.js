"use strict";
/* BRAIN_REPORT viewer: fetches /api/report and renders the digest read-only.
   The copy button hands the raw markdown to the clipboard (for pasting into
   issues/PRs). No mutation endpoints are called from this page. */
(function () {
  const out = document.getElementById("out");
  const meta = document.getElementById("meta");
  const err = document.getElementById("error");

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function render(md) {
    // minimal, safe rendering: escape everything, then bold/highlight by marker
    const lines = md.split("\n").map((line) => {
      if (line.startsWith("# ")) return '<span class="head">' + esc(line) + "</span>";
      if (line.startsWith("## ")) return '<span class="head">' + esc(line) + "</span>";
      if (/⚠|WARN/.test(line)) return '<span class="warn">' + esc(line) + "</span>";
      if (/nothing queued|no pending|inert|omitted/.test(line))
        return '<span class="dim">' + esc(line) + "</span>";
      return esc(line);
    });
    out.innerHTML = lines.join("\n");
  }

  fetch("/api/report")
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((data) => {
      meta.textContent = "· " + data.generated_at + " · " + data.nodes + " nodes / "
        + data.edges + " live edges";
      render(data.markdown);
    })
    .catch((e) => {
      out.hidden = true;
      err.hidden = false;
      err.textContent = "failed to load report: " + e.message;
    });

  document.getElementById("copy").addEventListener("click", () => {
    navigator.clipboard.writeText(out.textContent).then(() => {
      const b = document.getElementById("copy");
      b.textContent = "Copied!";
      setTimeout(() => { b.textContent = "Copy markdown"; }, 1200);
    });
  });
})();

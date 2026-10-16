// All source text is inert DOM text. No Markdown/HTML or source URLs execute.
(() => {
  if (new URLSearchParams(location.search).get('mode') !== 'decisions') return;
  const byId = id => document.getElementById(id);
  byId('main').hidden = true;
  byId('decision-review').hidden = false;
  byId('count').textContent = 'decision impact';
  const queue = byId('dm-queue'), detail = byId('dm-detail');
  let entries = [], selected = null, snapshot = null, comparison = null;
  let serial = 0, busy = false;
  const refKey = ref => `${ref.id}@${ref.version_id}`;
  const refOf = record => ({id: record.id, version_id: record.version_id});
  const reasonText = reason => ({basis_changed:'Evidence or assumptions changed', support_withdrawn:'Supporting evidence was withdrawn',
    comparable_opposition:'Opposing evidence applies to comparable conditions', revisit_check_result:'A revisit check has a result',
    comparability_unknown:'Scope comparison is unresolved', scope_changed:'Applicable conditions changed'}[reason] || reason);
  function excerptText(excerpt) {
    let text = excerpt.text;
    try { const value = JSON.parse(text); text = typeof value === 'string' ? value : JSON.stringify(value, null, 2); } catch (_) { /* Bounded excerpts can end mid-JSON. */ }
    return text + (excerpt.truncated ? ' [excerpt truncated]' : '');
  }
  function el(tag, text, parent, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    if (parent) parent.append(node);
    return node;
  }
  function button(text, parent, fn) {
    const node = el('button', text, parent);
    node.type = 'button';
    node.addEventListener('click', fn);
    return node;
  }
  function message(error) {
    if (error.status === 401) return 'Authentication required. Use the authenticated server session, then refresh.';
    if (error.status === 403) return 'Forbidden or missing source: this evidence is unavailable under current permissions.';
    if (error.status === 409) return 'Stale review: evidence or judgments changed. Refresh and review the current evidence.';
    return error.message || 'Unable to load evidence. Refresh to retry.';
  }
  async function request(path, body) {
    const response = await fetch(`/api/decision-memory/${path}`, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(value.error || `Request failed (${response.status})`),
      {status: response.status, published: value.published_locally});
    return value;
  }
  function clearDetail(text) {
    snapshot = null;
    detail.replaceChildren();
    el('p', text, detail);
    detail.setAttribute('aria-busy', 'false');
  }
  function entryKey(entry) {
    return entry.kind === 'finding' ? refKey(entry.reference) : entry.candidate.candidate_id;
  }
  function renderQueue() {
    queue.replaceChildren();
    for (const entry of entries) {
      const c = entry.candidate;
      const state = entry.item?.state;
      const label = state ? `Reviewed judgment: ${state.finding_disposition}; workflow: ${state.finding_workflow || 'none'}` : 'Proposed judgment · unreviewed';
      const li = el('li', undefined, queue);
      const b = button(`${c.decision.action}\n${c.reasons.map(reasonText).join(', ')}\n${label}\n${c.delta.recorded_at}`, li, () => select(entry));
      b.setAttribute('aria-current', String(entryKey(entry) === selected));
      b.disabled = busy;
    }
  }
  async function refresh(keepSelection = true) {
    const ticket = ++serial;
    const previous = keepSelection ? selected : null;
    selected = null;
    entries = [];
    queue.replaceChildren();
    clearDetail('Loading current evidence…');
    byId('dm-message').textContent = 'Loading decision review queue…';
    try {
      const result = await request('read/review-queue', {
        history: byId('dm-history').checked, ...(comparison ? {comparison} : {})
      });
      if (ticket !== serial) return;
      entries = result.items;
      if (result.comparison) {
        // Resolve moving branch names once. Reviewing pins these exact commits.
        comparison = {...comparison, before: result.comparison.before.revision, after: result.comparison.after.revision};
      }
      byId('dm-message').textContent = `${entries.length} ${byId('dm-history').checked ? 'review entries' : 'pending candidates / findings'}. ` +
        (result.truncated ? `Partial / truncated view (queue limit ${result.limit}). Narrow the revision comparison; absence here does not establish a settled decision.` :
          entries.length ? 'Select an entry to inspect its evidence.' : 'No accessible pending findings. Compare revisions to look for new evidence.');
      if (result.comparison?.warnings.length) el('p', result.comparison.warnings.join('; '), byId('dm-message'));
      renderQueue();
      const entry = entries.find(e => entryKey(e) === previous);
      if (entry) await select(entry);
      else clearDetail('Select a finding, or compare two revisions to generate candidates.');
    } catch (error) {
      if (ticket !== serial) return;
      byId('dm-message').textContent = message(error);
      clearDetail('Evidence unavailable. Refresh to retry.');
    }
  }
  async function select(entry) {
    if (busy) return;
    const ticket = ++serial;
    selected = entryKey(entry);
    renderQueue();
    clearDetail('Loading decision detail…');
    detail.setAttribute('aria-busy', 'true');
    try {
      const result = await request('read/review-detail', entry.kind === 'finding' ? {reference: entry.reference} :
        {comparison: entry.comparison, candidate_id: entry.candidate.candidate_id});
      if (ticket !== serial) return;
      snapshot = result;
      renderDetail(entry, result);
    } catch (error) {
      if (ticket !== serial) return;
      clearDetail(message(error));
      if ([401,403].includes(error.status)) { entries = []; renderQueue(); }
      if (error.status === 409) await refresh(false);
    } finally {
      if (ticket === serial) detail.setAttribute('aria-busy', 'false');
    }
  }
  function conditions(context, parent) {
    el('h4', 'Conditions', parent);
    if (!context) { el('p', 'Unresolved scope: conditions are missing.', parent); return; }
    if (context.profile) el('p', `Profile: ${refKey(context.profile)}`, parent, 'dm-ref');
    const list = el('ul', undefined, parent);
    for (const [name, dim] of Object.entries(context.dimensions)) {
      el('li', `${name}: ${typeof dim.value === 'object' ? JSON.stringify(dim.value) : dim.value ?? 'unknown'} (${dim.type})`, list);
    }
    if (context.notes) el('p', context.notes, parent);
  }
  function history(item, parent) {
    const box = el('details', undefined, parent);
    el('summary', `Review history (${item.events.length})`, box);
    for (const event of item.events) {
      el('p', `${event.axis}: ${event.from ?? 'none'} → ${event.to} · ${event.reviewer} · ${event.reviewed_at}`, box);
      el('blockquote', event.reason, box);
      el('p', `Event ${event.event_id}; previous ${event.previous_event_id || 'none'}`, box, 'dm-ref');
    }
    if (!item.events.length) el('p', 'No reviewed judgments recorded.', box);
  }
  function record(item, parent, preview, records) {
    const r = item.record, p = r.payload;
    const box = el('details', undefined, parent, 'dm-record');
    box.open = ['claim', 'evidence', 'decision'].includes(r.kind);
    const version = preview.heads[r.id] === r.version_id ? 'Current version' : 'Previous / pinned version';
    el('summary', `${version} · ${r.kind}${r.kind === 'relationship' ? ` · ${p.kind}` : ''}`, box);
    el('p', refKey(r), box, 'dm-ref');
    el('p', `${item.events.length ? 'Reviewed judgments' : 'Proposed / unreviewed'} · ${Object.entries(item.state).map(([k,v]) => `${k}: ${v ?? 'none'}`).join('; ')}`, box, 'dm-status');
    if (item.basis_changed) el('p', 'Basis changed / stale: this recorded judgment is not a current justification.', box, 'dm-status');
    if (item.hypothetical) el('p', 'Hypothetical evidence: cannot justify a real decision.', box);
    for (const field of ['text','interpretation','action','rationale','question','explanation','outcome']) {
      if (p[field]) el(field === 'text' || field === 'interpretation' ? 'blockquote' : 'p', `${field}: ${p[field]}`, box);
    }
    for (const relationship of records.filter(i => i.record.kind === 'relationship'
        && ['supports','opposes'].includes(i.record.payload.kind)
        && refKey(i.record.payload.source) === refKey(r))) {
      const rel = relationship.record.payload;
      const claim = records.find(i => refKey(i.record) === refKey(rel.target));
      el('p', `${rel.kind === 'opposes' ? 'Opposing' : 'Supporting'} passage for: ${claim?.record.payload.text || refKey(rel.target)} · relationship ${relationship.state.workflow}`, box, 'dm-status');
    }
    if (p.context !== undefined) conditions(p.context, box);
    if (p.limitations?.length) el('p', `Limitations: ${p.limitations.join('; ')}`, box);
    if (r.kind === 'relationship') el('p', `${refKey(p.source)} → ${refKey(p.target)}`, box, 'dm-ref');
    for (const source of p.sources || []) {
      el('p', `Source: ${refKey(source.ref)}`, box, 'dm-ref');
      if (source.passage) el('blockquote', source.passage.quote, box);
      else el('p', 'No selected passage; read the pinned source below.', box);
    }
    if (p.lineage_ids) el('p', `Recorded source lineage: ${p.lineage_ids.join(', ') || 'unspecified'}. Independence is not inferred.`, box);
    history(item, box);
  }
  function eventDraft(item, axis, to, reason, basis) {
    return {subject: refOf(item.record), axis, from: item.state[axis], to,
      previous_event_id: [...item.events].reverse().find(e => e.axis === axis)?.event_id || null,
      basis, reason, supersedes_event_id: null};
  }
  function reasonField(parent) {
    const label = el('label', 'Review reason (required)', parent);
    const field = el('textarea', undefined, label);
    field.required = true;
    field.maxLength = 20000;
    return field;
  }
  async function submit(path, payload, entry) {
    if (busy || !snapshot) return;
    busy = true;
    byId('dm-refresh').disabled = true;
    byId('dm-history').disabled = true;
    byId('dm-compare').querySelector('button').disabled = true;
    detail.querySelectorAll('button, textarea, select').forEach(n => n.disabled = true);
    renderQueue();
    try {
      const preview = snapshot.preview;
      await request(path, {...payload, idempotency_key: Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join(''),
        expected_generation: preview.generation, expected_heads: preview.heads});
      byId('dm-notice').textContent = 'Review recorded. Queue and history refreshed.';
    } catch (error) {
      byId('dm-notice').textContent = error.published ?
        'Published locally; sync is incomplete. Evidence has been refreshed. Check history before submitting another review.' :
        error.status === 409 ? 'Stale review: newer evidence or judgments were preserved. Review the refreshed evidence and enter a new reason.' : message(error);
    } finally {
      busy = false;
      byId('dm-refresh').disabled = false;
      byId('dm-history').disabled = false;
      byId('dm-compare').querySelector('button').disabled = false;
      await refresh(true);
    }
  }
  function renderDetail(entry, result) {
    detail.replaceChildren();
    const c = result.candidate;
    el('h3', c.decision.action, detail);
    el('p', c.decision.rationale, detail);
    el('p', `Decision: ${refKey(c.target)}`, detail, 'dm-ref');
    el('p', `${entry.kind === 'candidate' ? 'Proposed judgment · unreviewed' : `Reviewed finding · ${result.finding.state.finding_disposition} · ${result.finding.state.finding_workflow || 'no workflow'}`} · ${c.classification === 'proposed_preview' ? 'Proposed evidence path' : 'Candidate decision impact'}`, detail, 'dm-status');
    el('p', c.judgment, detail);
    el('p', `Reason for review: ${c.reasons.map(reasonText).join('; ')}`, detail);
    if (result.truncated) el('p', 'Partial / truncated evidence or paths. Inspect exact references before drawing conclusions.', detail, 'dm-status');
    el('h3', 'Changed evidence', detail);
    el('p', `${c.delta.kind} · ${c.delta.actor} · ${c.delta.recorded_at} · event ${c.delta.event_id || 'content revision'}`, detail);
    for (const change of c.delta.changes) {
      const label = {'payload.text':'Source / claim text', 'payload.context':'Conditions', 'payload.source_ref':'Source version identity',
        'payload.interpretation':'Evidence interpretation', 'payload.lineage_ids':'Source lineage', 'payload.sources':'Cited sources',
        'payload.action':'Decision action', 'payload.rationale':'Decision rationale'}[change.field] || change.field;
      const box = change.field === 'payload.source_ref' ? el('details', undefined, detail) : detail;
      el(box === detail ? 'h4' : 'summary', label, box);
      el('blockquote', `Previous: ${excerptText(change.before)}`, box);
      el('blockquote', `Current: ${excerptText(change.after)}`, box);
    }
    el('h3', 'Comparable versus unresolved scope', detail);
    if (!c.comparison.length) el('p', 'No scope comparison established for this path.', detail);
    for (const scope of c.comparison) {
      el('p', `${scope.status === 'comparable' ? 'Comparable scope' : 'Unresolved comparison'}: ${scope.status}. ${scope.reasons.join('; ')}`, detail, 'dm-status');
      el('pre', `Intersection: ${JSON.stringify(scope.intersection, null, 2)}`, detail);
    }
    el('h3', 'Dependency path to the decision', detail);
    for (const path of c.paths) {
      const list = el('ol', undefined, detail);
      const title = ref => {
        const record = result.records.find(i => refKey(i.record) === refKey(ref))?.record;
        if (!record) return 'Pinned record';
        const p = record.payload;
        return `${record.kind}: ${(p.text || p.interpretation || p.action || p.question || p.name || p.outcome || record.kind).slice(0, 120)}`;
      };
      for (const step of path) {
        const li = el('li', `${title(step.from_ref)} → ${step.kind} (${step.acceptance}) → ${title(step.to_ref)}`, list);
        const exact = el('details', undefined, li);
        el('summary', 'Exact path references', exact);
        el('p', `${refKey(step.from_ref)} → ${refKey(step.to_ref)} · ${step.direction} · revision ${step.revision}`, exact, 'dm-ref');
      }
    }
    el('h3', 'Supporting and opposing passages; previous/current claims', detail);
    el('p', `Remaining support links: ${c.support.remaining.length}; removed support links: ${c.support.removed.length}. Link counts do not establish truth or independence.`, detail);
    for (const item of result.records) record(item, detail, result.preview, result.records);
    if (result.finding) history(result.finding, detail);
    const actions = el('section', undefined, detail);
    actions.id = 'dm-review-actions';
    el('h3', 'Review actions', actions);
    el('p', 'Every action requires a reason and pins the exact content and event versions shown above.', actions);
    const preconditions = el('details', undefined, actions);
    el('summary', 'Exact submission preconditions', preconditions);
    el('p', `Generation: ${result.preview.generation}`, preconditions);
    const heads = el('ul', undefined, preconditions);
    for (const [name, version] of Object.entries(result.preview.heads)) el('li', `${name}: ${version}`, heads, 'dm-ref');
    if (entry.kind === 'candidate' || result.finding?.state.finding_disposition !== 'confirmed') {
      const form = el('form', undefined, actions);
      const label = el('label', 'Finding judgment', form);
      const choice = el('select', undefined, label); choice.setAttribute('aria-label', 'Finding judgment');
      for (const [value,text] of [['confirmed','Confirm: warrants decision review'],['dismissed','Dismiss candidate'],['inconclusive','Inconclusive']]) el('option', text, choice).value = value;
      const reason = reasonField(form);
      const b = el('button', 'Record finding judgment', form); b.type = 'submit';
      form.addEventListener('submit', ev => {
        ev.preventDefault(); if (!reason.value.trim()) return;
        if (entry.kind === 'candidate') submit('findings', {schema:'dm.finding-review/1', comparison:entry.comparison,
          candidate_id:c.candidate_id, disposition:choice.value, reason:reason.value.trim()}, entry);
        else submit('reviews', {schema:'dm.review/1', events:[eventDraft(result.finding, 'finding_disposition', choice.value,
          reason.value.trim(), [{type:'content_ref',ref:c.target}])]}, entry);
      });
    } else if (result.finding.state.finding_workflow !== 'resolved') {
      const form = el('form', undefined, actions);
      const reason = reasonField(form);
      if (result.finding.state.finding_workflow === 'open') {
        button('Acknowledge finding', form, () => {
          if (!reason.reportValidity() || !reason.value.trim()) return;
          submit('reviews', {schema:'dm.review/1', events:[eventDraft(result.finding, 'finding_workflow', 'acknowledged',
            reason.value.trim(), [{type:'content_ref',ref:c.target}])]}, entry);
        });
      }
      const decision = result.records.find(item => refKey(item.record) === refKey(c.target));
      if (decision) {
        const panel = el('section', undefined, form); panel.id = 'dm-decision-outcome';
        el('h4', 'Review decision: retain, investigate or revise', panel);
        el('p', 'Records a review outcome. Revising the decision content uses the explicit proposal contract (ig decision propose); the choice itself is not reversed here.', panel);
        const label = el('label', 'Decision review outcome', panel);
        const outcome = el('select', undefined, label); outcome.setAttribute('aria-label', 'Decision review outcome');
        for (const [value,text] of [['remains_justified','Remains justified'],['needs_investigation','Needs investigation'],['revise','Revise decision']]) el('option', text, outcome).value = value;
        const basisLabel = el('label', 'Evidence / claim basis for this outcome (select one or more)', panel);
        const basisChoice = el('select', undefined, basisLabel); basisChoice.multiple = true;
        basisChoice.setAttribute('aria-label', 'Evidence / claim basis for this outcome (select one or more)');
        for (const item of result.records.filter(i => ['claim','evidence','result','check'].includes(i.record.kind)
            && result.preview.heads[i.record.id] === i.record.version_id)) {
          const p = item.record.payload;
          el('option', `${item.record.kind}: ${p.text || p.interpretation || p.question || p.outcome}`, basisChoice).value = refKey(item.record);
        }
        button('Record decision outcome', panel, () => {
          if (!reason.reportValidity() || !reason.value.trim()) return;
          const chosen = [...basisChoice.selectedOptions].map(option => result.records.find(i => refKey(i.record) === option.value));
          if (!chosen.length) { basisChoice.setCustomValidity('Select an explicit basis.'); basisChoice.reportValidity(); return; }
          submit('reviews', {schema:'dm.review/1', events:[eventDraft(decision, 'decision_conclusion', outcome.value,
            reason.value.trim(), chosen.map(item => ({type:'content_ref',ref:refOf(item.record)})))]}, entry);
        });
        basisChoice.addEventListener('change', () => basisChoice.setCustomValidity(''));
        const last = [...decision.events].reverse().find(e => e.axis === 'decision_conclusion');
        if (last) {
          el('p', `Resolution will pin outcome ${last.to}, event ${last.event_id}. The authenticated reviewer owns the resolution.`, panel);
          const label = el('label', 'Follow-up check (required for investigation)', panel);
          const check = el('select', undefined, label); check.setAttribute('aria-label', 'Follow-up check (required for investigation)');
          el('option', 'Select an existing check', check).value = '';
          for (const item of result.records.filter(i => i.record.kind === 'check')) el('option', item.record.payload.question, check).value = refKey(item.record);
          button('Resolve finding with recorded outcome', panel, () => {
            if (!reason.reportValidity() || !reason.value.trim()) return;
            const basis = [{type:'event_ref', event_id:last.event_id}];
            if (last.to === 'needs_investigation') {
              if (!check.value) { check.setCustomValidity('Choose a follow-up check.'); check.reportValidity(); return; }
              const item = result.records.find(i => refKey(i.record) === check.value);
              basis.push({type:'content_ref', ref:refOf(item.record)});
            }
            submit('reviews', {schema:'dm.review/1',events:[eventDraft(result.finding, 'finding_workflow', 'resolved', reason.value.trim(), basis)]}, entry);
          });
          check.addEventListener('change', () => check.setCustomValidity(''));
        }
      }
      form.addEventListener('submit', ev => ev.preventDefault());
    }
    const brief = el('section', undefined, detail);
    el('h3', 'Revision-pinned decision brief', brief);
    button('Open decision brief', brief, async () => {
      const ticket = serial;
      try {
        const result = await request('read/brief', {reference:c.target, revision:'HEAD'});
        if (ticket !== serial) return;
        brief.replaceChildren();
        el('h3', `Decision brief · revision ${result.revision}`, brief);
        el('pre', result.markdown, brief);
      } catch (error) {
        if (ticket !== serial) return;
        if ([401,403].includes(error.status)) { entries = []; renderQueue(); clearDetail(message(error)); }
        else el('p', message(error), brief);
      }
    });
  }
  byId('dm-compare').addEventListener('submit', ev => {
    ev.preventDefault(); if (busy) return;
    comparison = {schema:'dm.compare/1',before:byId('dm-before').value.trim(),after:byId('dm-after').value.trim()};
    refresh(false);
  });
  byId('dm-refresh').addEventListener('click', () => refresh());
  byId('dm-history').addEventListener('change', () => refresh(false));
  refresh(false);
})();

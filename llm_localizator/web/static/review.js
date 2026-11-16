(function () {
  var page = document.getElementById("page");
  var root = document.getElementById("page-body");
  if (!page || page.dataset.page !== "review" || !root) return;

  function uiT(key, fallback) {
    return (window.uiT || function (k, f) { return f != null ? f : k; })(key, fallback);
  }

  function statusLabel(code) {
    var map = {
      open: uiT("rev_status_open", "Open"),
      in_progress: uiT("rev_status_in_review", "In review"),
      done: uiT("rev_status_closed", "Closed"),
      blocked: uiT("rev_status_blocked", "Blocked"),
    };
    return map[code] || code;
  }
  var FILTERS = ["open", "in_progress", "done", "blocked"];
  function typePairs() {
    return [
      ["low_score", uiT("rev_type_low_score", "Low score")],
      ["mistranslation", uiT("rev_type_mistranslation", "Mistranslation")],
      ["question", uiT("rev_type_question", "Question")],
      ["needs_context", uiT("rev_type_needs_context", "Context needed")],
      ["placeholder_mismatch", uiT("rev_type_placeholder", "Placeholder mismatch")],
      ["tone_style", uiT("rev_type_tone", "Tone / style")],
      ["other", uiT("rev_type_other", "Other")],
    ];
  }
  function typeLabel(code) {
    var found = "";
    typePairs().forEach(function (t) { if (t[0] === code) found = t[1]; });
    return found || code;
  }

  var state = {
    locale: "",
    locales: [],
    filter: "open",
    query: "",
    tickets: [],
    counts: {},
    selected: null,
    me: "",
    users: [],
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function project() {
    var select = document.getElementById("project-select");
    return select && select.value ? select.value : "";
  }

  function params(extra) {
    var q = new URLSearchParams();
    if (project()) q.set("project", project());
    Object.keys(extra || {}).forEach(function (key) {
      if (extra[key] != null && extra[key] !== "") q.set(key, extra[key]);
    });
    return q.toString();
  }

  var scope = (window.LLMApi && LLMApi.requestScope) ? LLMApi.requestScope() : null;

  function post(url, body) {
    body = Object.assign({ project: project() }, body || {});
    if (window.LLMApi && LLMApi.apiPost) return LLMApi.apiPost(url, body);
    return fetch(url, {
      method: "POST",
      headers: (window.LLMApi && LLMApi.authHeaders) ? LLMApi.authHeaders() : { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (response) { return response.json(); });
  }

  function typeBadge(ticket) {
    var reason = ticket.type || ticket.reason || "other";
    var known = false;
    typePairs().forEach(function (t) { if (t[0] === reason) known = true; });
    var cls = "rq-badge rq-badge--" + (known ? reason : "other");
    if (ticket.status === "done") cls = "rq-badge rq-badge--done";
    var text = ticket.status === "done" && reason !== "question"
      ? uiT("rev_resolved", "resolved")
      : typeLabel(reason);
    return el("span", cls, (reason === "low_score" && ticket.status !== "done" ? "⚠ " : "") + text);
  }

  function ago(iso) {
    var t = Date.parse(iso || "");
    if (isNaN(t)) return "";
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return uiT("time_just_now", "just now");
    if (s < 3600) {
      return uiT("time_m_ago", "{n}m ago").replace("{n}", String(Math.floor(s / 60)));
    }
    if (s < 86400) {
      return uiT("time_h_ago", "{n}h ago").replace("{n}", String(Math.floor(s / 3600)));
    }
    return uiT("time_d_ago", "{n}d ago").replace("{n}", String(Math.floor(s / 86400)));
  }

  function avatar(name, large) {
    var initials = (name || "?").split(/[.\s_-]+/).filter(Boolean).slice(0, 2)
      .map(function (p) { return p[0].toUpperCase(); }).join("") || "?";
    var node = el("span", "rq-avatar" + (large ? " rq-avatar--lg" : "")
      + (name && name === state.me ? " is-me" : ""), initials);
    node.title = name || "";
    return node;
  }

  function titleOf(ticket) {
    if (ticket.title) return ticket.title;
    var first = (ticket.comments || [])[0];
    if (first && first.body) return first.body.split("\n")[0].slice(0, 140);
    if (ticket.score != null && ticket.reason === "low_score") {
      return uiT("rev_title_low_score", "Score {score} — below the quality threshold")
        .replace("{score}", ticket.score.toFixed(2));
    }
    return typeLabel(ticket.reason);
  }

  function keyPath(ticket) {
    return (ticket.namespace ? ticket.namespace + "." : "") + ticket.key;
  }

  var layout = el("div", "split rq-split");
  var side = el("div", "rq-list");
  var detail = el("div", "rq-detail");
  layout.appendChild(side);
  layout.appendChild(detail);
  // Clear the shell's "Loading…" empty-state before mounting the queue.
  root.replaceChildren(layout);

  function assigneeOptions(current) {
    var names = {};
    state.users.forEach(function (u) { names[u] = true; });
    state.tickets.forEach(function (t) {
      if (t.assignee) names[t.assignee] = true;
      (t.comments || []).forEach(function (c) { if (c.author) names[c.author] = true; });
    });
    if (state.me) names[state.me] = true;
    if (current) names[current] = true;
    return Object.keys(names).sort();
  }

  function relatedOf(ticket) {
    if (!ticket) return [];
    return state.tickets.filter(function (t) {
      if (t.id === ticket.id) return false;
      return (t.key === ticket.key && t.namespace === ticket.namespace)
        || (t.reason && t.reason === ticket.reason);
    }).slice(0, 5);
  }

  function visibleTickets() {
    var q = state.query.toLowerCase();
    return state.tickets.filter(function (t) {
      if (!q) return true;
      return [t.key, t.namespace, t.reason, t.title, t.assignee, t.display_id]
        .some(function (v) { return (v || "").toLowerCase().indexOf(q) >= 0; });
    });
  }

  function refreshBadge() {
    if (window.LLMShell && window.LLMShell.refreshReviewBadge) window.LLMShell.refreshReviewBadge();
  }

  function loadTickets() {
    if (!state.locale) {
      state.tickets = [];
      paint();
      return Promise.resolve();
    }
    var token = scope ? scope.next() : null;
    var get = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/review/tickets", {
          project: project(),
          locale: state.locale,
          status: state.filter,
        }, token ? { signal: token.signal } : {})
      : fetch("/api/review/tickets?" + params({
          locale: state.locale,
          status: state.filter,
        })).then(function (r) { return r.json(); });
    return get.then(function (data) {
      if (scope && token && !scope.isCurrent(token)) return;
      state.tickets = data.tickets || [];
      state.counts = data.counts || {};
      var keep = state.selected && state.tickets.filter(function (t) {
        return t.id === state.selected.id;
      })[0];
      state.selected = keep || state.tickets[0] || null;
      paint();
      refreshBadge();
    }).catch(function (err) {
      if (err && err.name === "AbortError") return;
    });
  }

  function select(ticket) {
    state.selected = ticket;
    paintList();
    paintDetail();
  }

  function paint() {
    side.replaceChildren();
    var head = el("div", "rq-list-head");
    var titleRow = el("div", "rq-title-row");
    var h1 = el("h2", "rq-title", uiT("nav_review", "Review queue"));
    if (window.LLMHelp) h1.appendChild(window.LLMHelp.helpBtn("review:general"));
    titleRow.appendChild(h1);
    var add = el("button", "btn btn-primary", uiT("rev_new_ticket", "+ New ticket"));
    add.type = "button";
    add.addEventListener("click", openCreate);
    titleRow.appendChild(add);
    head.appendChild(titleRow);

    var filters = el("div", "rq-filters");
    FILTERS.forEach(function (status) {
      var count = state.counts[status];
      var label = statusLabel(status) + (count != null ? " (" + count + ")" : "");
      var btn = el("button", "btn" + (state.filter === status ? " is-active" : ""), label);
      btn.type = "button";
      btn.addEventListener("click", function () {
        state.filter = status;
        state.selected = null;
        loadTickets();
      });
      filters.appendChild(btn);
    });
    head.appendChild(filters);

    var row = el("div", "rq-search-row");
    var locale = document.createElement("select");
    locale.setAttribute("aria-label", uiT("rev_aria_locale", "Locale"));
    state.locales.forEach(function (name) {
      var opt = el("option", "", name);
      opt.value = name;
      if (name === state.locale) opt.selected = true;
      locale.appendChild(opt);
    });
    locale.addEventListener("change", function () {
      state.locale = locale.value;
      state.selected = null;
      loadTickets();
    });
    var search = document.createElement("input");
    search.type = "search";
    search.placeholder = uiT("rev_search_ph", "search tickets…");
    search.value = state.query;
    search.addEventListener("input", function () {
      state.query = search.value;
      paintList();
    });
    row.appendChild(locale);
    row.appendChild(search);
    head.appendChild(row);
    side.appendChild(head);

    var list = el("div", "rq-cards");
    list.id = "ticket-list";
    side.appendChild(list);
    paintList();
    paintDetail();
  }

  function paintList() {
    var list = document.getElementById("ticket-list");
    if (!list) return;
    list.replaceChildren();
    var rows = visibleTickets();
    rows.forEach(function (ticket) {
      var active = state.selected && state.selected.id === ticket.id;
      var card = el("button", "rq-card" + (active ? " is-active" : "") + (ticket.status === "done" ? " is-done" : ""));
      card.type = "button";
      var top = el("div", "rq-card-top");
      var left = el("span", "rq-card-badges");
      left.appendChild(typeBadge(ticket));
      left.appendChild(el("span", "rq-id", "#" + ticket.display_id));
      top.appendChild(left);
      top.appendChild(el("span", "rq-time", ago(ticket.updated_at || ticket.created_at)));
      card.appendChild(top);
      card.appendChild(el("div", "rq-key", keyPath(ticket) + " · " + ticket.locale));
      card.appendChild(el("div", "rq-excerpt", titleOf(ticket)));
      var foot = el("div", "rq-card-foot");
      foot.appendChild(avatar(ticket.assignee || ticket.opened_by));
      foot.appendChild(el("span", "rq-muted", ticket.assignee || uiT("rev_unassigned", "unassigned")));
      var n = ticket.comment_count || 0;
      foot.appendChild(el(
        "span", "rq-count",
        n === 1
          ? uiT("rev_n_comment", "{n} comment").replace("{n}", String(n))
          : uiT("rev_n_comments", "{n} comments").replace("{n}", String(n)),
      ));
      card.appendChild(foot);
      card.addEventListener("click", function () { select(ticket); });
      list.appendChild(card);
    });
    if (!rows.length) {
      list.appendChild(el(
        "p", "empty-state",
        state.query
          ? uiT("rev_no_match", "No tickets match.")
          : uiT("rev_no_tickets", "No tickets here."),
      ));
    }
  }

  function panel(title) {
    var box = el("section", "rq-panel");
    if (title) box.appendChild(el("div", "rq-panel-title", title));
    return box;
  }

  function selectEl(options, value) {
    var node = document.createElement("select");
    options.forEach(function (o) {
      var opt = el("option", "", o[1]);
      opt.value = o[0];
      if (o[0] === value) opt.selected = true;
      node.appendChild(opt);
    });
    return node;
  }

  function applyStatus(ticket, status, assignee) {
    return post("/api/review/tickets/" + ticket.id + "/status", {
      locale: ticket.locale,
      status: status,
      assignee: assignee,
    }).then(function (result) {
      if (!result.ok) {
        window.alert(result.error || uiT("rev_update_failed", "Update failed"));
        return null;
      }
      state.selected = result.ticket;
      return loadTickets();
    });
  }

  function paintHeader(ticket) {
    var head = el("div", "rq-detail-head");
    var info = el("div", "rq-detail-info");
    var badges = el("div", "rq-card-badges");
    badges.appendChild(el("span", "rq-id", "#" + ticket.display_id));
    badges.appendChild(typeBadge(ticket));
    badges.appendChild(el("span", "rq-badge rq-badge--status", statusLabel(ticket.status) || ticket.status));
    if (window.LLMHelp) badges.appendChild(window.LLMHelp.helpBtn("review:ticket"));
    info.appendChild(badges);
    info.appendChild(el("h3", "rq-detail-title", titleOf(ticket)));
    var meta = el("div", "rq-muted");
    meta.appendChild(document.createTextNode(uiT("rev_opened_by", "Opened by") + " "));
    meta.appendChild(el("strong", "", ticket.opened_by || uiT("rev_system", "system")));
    meta.appendChild(document.createTextNode(
      " · " + ago(ticket.created_at) + " · " + uiT("rev_assigned_to", "assigned to") + " ",
    ));
    meta.appendChild(el("strong", "", ticket.assignee || uiT("rev_nobody", "nobody")));
    info.appendChild(meta);
    head.appendChild(info);

    var controls = el("div", "rq-controls");
    var names = assigneeOptions(ticket.assignee);
    var assign = selectEl(
      [["", uiT("rev_assign_to_ph", "Assign to…")]].concat(names.map(function (n) { return [n, n]; })),
      ticket.assignee || "",
    );
    assign.setAttribute("aria-label", uiT("rev_assign_to", "Assign to"));
    assign.addEventListener("change", function () {
      applyStatus(ticket, ticket.status, assign.value);
    });
    var status = selectEl(FILTERS.map(function (s) { return [s, statusLabel(s)]; }), ticket.status);
    status.setAttribute("aria-label", uiT("rev_status", "Status"));
    status.addEventListener("change", function () {
      applyStatus(ticket, status.value, null);
    });
    controls.appendChild(assign);
    controls.appendChild(status);
    if (ticket.status !== "done") {
      var close = el("button", "btn btn-primary", uiT("rev_close_ticket", "Close ticket"));
      close.type = "button";
      close.addEventListener("click", function () { applyStatus(ticket, "done", null); });
      controls.appendChild(close);
    }
    head.appendChild(controls);
    return head;
  }

  function paintContext(ticket) {
    var box = panel(uiT("rev_string_context", "String context"));
    var grid = el("div", "rq-ctx");
    var src = el("div", "rq-ctx-cell is-source");
    src.appendChild(el("div", "rq-ctx-label", uiT("ed_source_word", "Source")));
    src.appendChild(el("div", "rq-ctx-text", ticket.source || "—"));
    var cur = el("div", "rq-ctx-cell");
    cur.appendChild(el(
      "div", "rq-ctx-label",
      uiT("rev_translation_current", "Translation ({locale}) — current")
        .replace("{locale}", ticket.locale),
    ));
    var curText = el("div", "rq-ctx-text", ticket.current || "—");
    curText.setAttribute("dir", "auto");
    cur.appendChild(curText);
    grid.appendChild(src);
    grid.appendChild(cur);
    box.appendChild(grid);

    var meta = el("div", "rq-ctx-meta");
    var score = el("span", "rq-score");
    score.appendChild(document.createTextNode(uiT("rev_quality_score", "Quality score:") + " "));
    if (ticket.score == null) {
      score.appendChild(el("strong", "", "—"));
    } else {
      var level = ticket.score >= 0.8 ? "ok" : ticket.score >= 0.55 ? "warn" : "bad";
      score.appendChild(el("strong", "rq-score-" + level, ticket.score.toFixed(2)));
      var bar = el("span", "rq-bar");
      var fill = el("span", "rq-bar-fill rq-score-" + level);
      fill.style.width = Math.round(Math.max(0, Math.min(1, ticket.score)) * 100) + "%";
      bar.appendChild(fill);
      score.appendChild(bar);
    }
    meta.appendChild(score);
    if (ticket.scorer) {
      meta.appendChild(el(
        "span", "rq-muted",
        uiT("rev_scorer", "Scorer: {name}").replace("{name}", ticket.scorer),
      ));
    }
    var ns = el("span", "rq-muted", uiT("rev_key", "Key:") + " ");
    ns.appendChild(el("code", "", keyPath(ticket)));
    meta.appendChild(ns);
    var link = el("a", "rq-link", uiT("rev_open_editor", "Open in editor →"));
    link.href = "/app/editor?locale=" + encodeURIComponent(ticket.locale)
      + "&namespace=" + encodeURIComponent(ticket.namespace || "")
      + "&key=" + encodeURIComponent(ticket.key || "");
    meta.appendChild(link);
    box.appendChild(meta);
    if (ticket.signals && ticket.signals.length) {
      box.appendChild(el(
        "div", "rq-muted rq-signals",
        uiT("rev_signals", "Signals: {list}").replace("{list}", ticket.signals.join("; ")),
      ));
    }
    return box;
  }

  function eventText(ev) {
    if (ev.kind === "assignee") {
      return ev.to
        ? uiT("rev_assigned_event", "assigned this ticket to {who}").replace("{who}", ev.to)
        : uiT("rev_unassigned_event", "removed the assignee");
    }
    return uiT("rev_status_event", "changed status to {status}")
      .replace("{status}", statusLabel(ev.to) || ev.to);
  }

  function paintThread(ticket) {
    var box = panel(uiT("rev_discussion", "Discussion"));
    var thread = el("div", "rq-thread");

    var opened = (ticket.opened_by && ticket.opened_by !== "system")
      ? uiT("rev_opened_ticket", "opened this ticket")
      : uiT("rev_system_opened", "System opened this ticket");
    if (ticket.reason) opened += " · " + typeLabel(ticket.reason);
    var items = [{
      ts: ticket.created_at, system: true, actor: ticket.opened_by || "system",
      text: opened,
      detail: ticket.score != null && ticket.reason === "low_score"
        ? uiT("rev_low_score_detail", "Quality score {score} is below the threshold. Flagged for review.")
          .replace("{score}", ticket.score.toFixed(2))
        : "",
    }];
    (ticket.events || []).forEach(function (ev) {
      items.push({ ts: ev.ts, system: true, actor: ev.actor || "system", text: eventText(ev) });
    });
    (ticket.comments || []).forEach(function (c) {
      items.push({ ts: c.ts, actor: c.author, body: c.body });
    });
    items.sort(function (a, b) { return String(a.ts || "").localeCompare(String(b.ts || "")); });

    items.forEach(function (it) {
      if (it.system) {
        var row = el("div", "rq-event");
        row.appendChild(el("span", "rq-avatar rq-avatar--sys", "⚙"));
        var body = el("div", "");
        var line = el("div", "rq-muted");
        line.appendChild(el("strong", "", it.actor));
        line.appendChild(document.createTextNode(" " + it.text + " · " + ago(it.ts)));
        body.appendChild(line);
        if (it.detail) body.appendChild(el("div", "rq-event-detail", it.detail));
        row.appendChild(body);
        thread.appendChild(row);
      } else {
        var c = el("div", "rq-comment");
        c.appendChild(avatar(it.actor, true));
        var cb = el("div", "rq-comment-body");
        var h = el("div", "rq-comment-head");
        h.appendChild(el("strong", "", it.actor || "?"));
        h.appendChild(el("span", "rq-muted", ago(it.ts)));
        cb.appendChild(h);
        var text = el("div", "rq-comment-text", it.body || "");
        text.setAttribute("dir", "auto");
        cb.appendChild(text);
        c.appendChild(cb);
        thread.appendChild(c);
      }
    });
    box.appendChild(thread);

    var form = el("div", "rq-compose");
    form.appendChild(avatar(state.me, true));
    var col = el("div", "rq-compose-col");
    var author = null;
    if (!state.me) {
      author = document.createElement("input");
      author.type = "text";
      author.placeholder = uiT("rev_your_name_ph", "your name");
      try { author.value = localStorage.getItem("ll.review.author") || ""; } catch (err) { author.value = ""; }
      col.appendChild(author);
    }
    var body = document.createElement("textarea");
    body.placeholder = uiT("rev_comment_ph", "Add a comment or decision…");
    col.appendChild(body);
    var actions = el("div", "rq-compose-actions");
    var postBtn = el("button", "btn btn-primary", uiT("rev_post_comment", "Post comment"));
    postBtn.type = "button";
    var resolveBtn = el("button", "btn", uiT("rev_post_resolve", "Post & resolve"));
    resolveBtn.type = "button";
    var improve = el("label", "rq-improve", "");
    var improveBox = document.createElement("input");
    improveBox.type = "checkbox";
    improve.appendChild(improveBox);
    improve.appendChild(document.createTextNode(
      " " + uiT("rev_also_improve", "Also improve via LLM after resolving"),
    ));

    function sendComment(resolve) {
      var who = author ? author.value.trim() : state.me;
      if (!who) { window.alert(uiT("rev_enter_name", "Enter your name first.")); return; }
      if (!body.value.trim()) { window.alert(uiT("rev_write_comment", "Write a comment first.")); return; }
      if (author) { try { localStorage.setItem("ll.review.author", who); } catch (err) { /* ignore */ } }
      post("/api/review/tickets/" + ticket.id + "/comment", {
        locale: ticket.locale,
        author: who,
        body: body.value,
        resolve: !!resolve,
      }).then(function (result) {
        if (!result.ok) {
          window.alert(result.error || uiT("rev_comment_failed", "Comment failed"));
          return;
        }
        state.selected = result.ticket;
        body.value = "";
        var chain = loadTickets();
        if (resolve && improveBox.checked) {
          chain = chain.then(function () {
            return post("/api/ops/improve", {
              locales: [ticket.locale],
              keys: [keyPath(ticket)],
              confirm: true,
            });
          });
        }
        return chain;
      });
    }
    postBtn.addEventListener("click", function () { sendComment(false); });
    resolveBtn.addEventListener("click", function () { sendComment(true); });
    actions.appendChild(postBtn);
    actions.appendChild(resolveBtn);
    actions.appendChild(el("span", "rq-spacer"));
    actions.appendChild(improve);
    col.appendChild(actions);
    form.appendChild(col);
    box.appendChild(form);
    return box;
  }

  function paintRelated(ticket) {
    var box = panel(uiT("rev_related", "Related tickets"));
    var related = relatedOf(ticket);
    if (!related.length) {
      box.appendChild(el("p", "empty-state", uiT("rev_no_related", "No related tickets.")));
      return box;
    }
    var list = el("div", "rq-related");
    related.forEach(function (item) {
      var row = el("button", "rq-related-row");
      row.type = "button";
      row.appendChild(el("span", "rq-id", "#" + item.display_id));
      row.appendChild(typeBadge(item));
      row.appendChild(el("span", "", keyPath(item) + " · " + item.locale
        + (item.score != null ? " — score " + item.score.toFixed(2) : "")));
      row.appendChild(el("span", "rq-arrow", "→"));
      row.addEventListener("click", function () { select(item); });
      list.appendChild(row);
    });
    box.appendChild(list);
    return box;
  }

  function paintDetail() {
    detail.replaceChildren();
    var ticket = state.selected;
    if (!ticket) {
      detail.appendChild(el("p", "empty-state", state.tickets.length
        ? uiT("rev_select_ticket", "Select a ticket.")
        : uiT("rev_no_ticket_selected", "No ticket selected.")));
      return;
    }
    detail.appendChild(paintHeader(ticket));
    var scroll = el("div", "rq-detail-scroll");
    scroll.appendChild(paintContext(ticket));
    scroll.appendChild(paintThread(ticket));
    scroll.appendChild(paintRelated(ticket));
    detail.appendChild(scroll);
  }

  function openCreate() {
    var modal = el("div", "modal");
    var form = el("div", "modal-body rq-modal");
    var h = el("h2", "rq-title", uiT("rev_new_title", "New review ticket"));
    if (window.LLMHelp) h.appendChild(window.LLMHelp.helpBtn("review:new"));
    form.appendChild(h);
    function field(name, input, cls) {
      var label = el("label", "field" + (cls ? " " + cls : ""));
      label.appendChild(el("span", "rq-label", name));
      label.appendChild(input);
      form.appendChild(label);
      return input;
    }
    var pair = el("div", "rq-pair");
    form.appendChild(pair);
    var key = document.createElement("input");
    key.placeholder = uiT("rev_key_ph", "e.g. errors.timeout");
    key.className = "mono";
    var locale = selectEl(state.locales.map(function (l) { return [l, l]; }), state.locale);
    [
      [uiT("rev_field_key", "Key"), key],
      [uiT("rev_field_locale", "Locale"), locale],
    ].forEach(function (pairItem) {
      var label = el("label", "field");
      label.appendChild(el("span", "rq-label", pairItem[0]));
      label.appendChild(pairItem[1]);
      pair.appendChild(label);
    });
    var type = field(uiT("set_col_type", "Type"), selectEl(typePairs(), "low_score"));
    var title = field(
      uiT("rev_field_title", "Title"),
      Object.assign(document.createElement("input"), {
        placeholder: uiT("rev_title_ph", "Short summary (optional)"),
      }),
    );
    var description = field(
      uiT("rev_field_description", "Description"),
      Object.assign(document.createElement("textarea"), {
        placeholder: uiT("rev_description_ph", "Describe the issue…"),
      }),
    );
    var assignee = field(
      uiT("rev_assign_to", "Assign to"),
      selectEl(
        [["", uiT("rev_unassigned_opt", "(unassigned)")]].concat(
          assigneeOptions("").map(function (n) { return [n, n]; }),
        ),
        "",
      ),
    );
    var author = null;
    if (!state.me) {
      author = field(
        uiT("rev_your_name", "Your name"),
        Object.assign(document.createElement("input"), {
          placeholder: uiT("rev_author_ph", "author"),
        }),
      );
      try { author.value = localStorage.getItem("ll.review.author") || ""; } catch (err) { author.value = ""; }
    }
    var error = el("p", "rq-error");
    form.appendChild(error);
    var actions = el("div", "rq-modal-actions");
    var cancel = el("button", "btn", uiT("wf_cancel", "Cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { modal.remove(); });
    var save = el("button", "btn btn-primary", uiT("rev_create_ticket", "Create ticket"));
    save.type = "button";
    save.addEventListener("click", function () {
      var raw = key.value.trim();
      if (!raw) { error.textContent = uiT("rev_key_required", "Key is required."); return; }
      var dot = raw.indexOf(".");
      // Namespace is the part before the first dot; bare keys have none.
      var ns = dot > 0 ? raw.slice(0, dot) : "";
      var k = dot > 0 ? raw.slice(dot + 1) : raw;
      var who = author ? author.value.trim() : state.me;
      if (description.value.trim() && !who) {
        error.textContent = uiT(
          "rev_name_required",
          "Your name is required with a description.",
        );
        return;
      }
      if (author && who) { try { localStorage.setItem("ll.review.author", who); } catch (err) { /* ignore */ } }
      post("/api/review/tickets", {
        locale: locale.value,
        namespace: ns,
        key: k,
        reason: type.value,
        title: title.value || null,
        assignee: assignee.value || null,
        description: description.value || null,
        author: who || null,
      }).then(function (result) {
        if (!result.ok) {
          error.textContent = result.error || uiT("rev_create_failed", "Create failed");
          return;
        }
        state.locale = locale.value;
        state.filter = "open";
        state.selected = result.ticket;
        modal.remove();
        return loadTickets();
      });
    });
    actions.appendChild(cancel);
    actions.appendChild(save);
    form.appendChild(actions);
    modal.appendChild(form);
    modal.addEventListener("click", function (ev) { if (ev.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    key.focus();
  }

  function bootstrap() {
    var getMe = (window.LLMApi && LLMApi.apiGet)
      ? LLMApi.apiGet("/api/auth/me", {})
      : fetch("/api/auth/me").then(function (r) { return r.json(); });
    return getMe.then(function (me) {
      state.me = (me && me.user && (me.user.username || me.user.name)) || "";
    }).catch(function () {}).then(function () {
      var getSettings = (window.LLMApi && LLMApi.apiGet)
        ? LLMApi.apiGet("/api/settings", { project: project() })
        : fetch("/api/settings?" + params()).then(function (r) { return r.json(); });
      return getSettings;
    }).then(function (data) {
      state.locales = data.targets || [];
      if (!state.locale || state.locales.indexOf(state.locale) < 0) {
        state.locale = state.locales[0] || "";
      }
      return post("/api/auth/users", {}).then(function (res) {
        state.users = (res && res.ok && res.users || [])
          .map(function (u) { return u.username; }).filter(Boolean);
      }).catch(function () {});
    }).then(loadTickets);
  }

  if (window.LLMApi && LLMApi.onProjectReady) {
    LLMApi.onProjectReady(function () { bootstrap(); });
  } else {
    var sel = document.getElementById("project-select");
    if (sel) sel.addEventListener("change", bootstrap);
    bootstrap();
  }
})();

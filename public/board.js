(() => {
  const board = document.getElementById("contest-board");
  const find = selector => board.querySelector(selector);
  const columns = [
    { key: "poster", label: "대표 이미지", width: 83, value: row => row.poster ? "이미지 있음" : "이미지 없음" },
    { key: "name", label: "공모전명", width: 171 },
    { key: "category", label: "분야", width: 104, extra: true },
    { key: "audience", label: "응모대상", width: 89, extra: true },
    { key: "organizer", label: "주최/주관", width: 118, extra: true },
    { key: "sponsor", label: "후원/협찬", width: 93, extra: true },
    { key: "deadline", label: "접수기간", width: 156, value: row => row.end || "미기재", order: row => row.end },
    { key: "total", label: "총 상금", width: 91, order: row => row.totalAmount },
    { key: "first", label: "1등 상금", width: 91, extra: true, order: row => row.firstAmount },
    { key: "homepage", label: "홈페이지", width: 87, extra: true, value: row => row.homepage ? "링크 있음" : "링크 없음" },
    { key: "source", label: "사이트출처", width: 159, values: sourceNames,
      value: row => sourceNames(row).sort(collator.compare).join(", ") }
  ];
  let rows = [];
  let collecting = false;
  const table = find("table");
  const head = find("thead tr");
  const body = find("tbody");
  const menu = find(".contest-menu");
  const options = find(".contest-options");
  const search = find(".contest-search input");
  const sourceFilter = find(".contest-source-filter select");
  const columnsToggle = find(".contest-columns-toggle");
  const mobileSort = find(".contest-mobile-sort");
  const reset = find(".contest-reset");
  const count = find(".contest-count");
  const collection = find(".contest-collection");
  const sources = find(".contest-sources");
  const filters = new Map();
  const collator = new Intl.Collator("ko", { numeric: true });
  let sort = { key: "deadline", direction: "asc" };
  let open = null;
  const create = (tag, className, content) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content) element.textContent = content;
    return element;
  };
  const displayValue = (column, row) => (column.value ? column.value(row) : row[column.key]) || "미기재";
  const filterValues = (column, row) => column.values ? column.values(row) : [displayValue(column, row)];
  function sourceLinks(row) {
    return row.sourceLinks ?? (row.source && row.sourceUrl ? [{ source: row.source, url: row.sourceUrl }] : []);
  }
  function sourceNames(row) {
    const names = [...new Set(sourceLinks(row).map(link => link.source))];
    return names.length ? names : [row.source || "미기재"];
  }
  const shortDate = date => date ? date.slice(5).replace("-", ".") : "—";
  function setColumn(element, column) {
    element.dataset.key = column.key;
    if (column.extra) element.dataset.extra = "";
  }
  const colgroup = create("colgroup");
  const headers = new Map();
  for (const column of columns) {
    const sizing = create("col");
    setColumn(sizing, column);
    sizing.style.setProperty("--column-width", column.width + "px");
    colgroup.append(sizing);
    const th = create("th");
    setColumn(th, column);
    th.setAttribute("role", "columnheader");
    th.scope = "col";
    const button = create("button", "contest-column");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    const mark = create("span", null, "⌄");
    mark.setAttribute("aria-hidden", "true");
    button.append(create("span", null, column.label), mark);
    button.addEventListener("click", () => showMenu(column, button));
    th.append(button);
    head.append(th);
    headers.set(column.key, { th, button, mark });
  }
  table.prepend(colgroup);
  const setHeaderState = () => {
    for (const [key, header] of headers) {
      const activeSort = sort.key === key;
      const activeFilter = filters.has(key);
      header.button.dataset.active = String(activeSort || activeFilter);
      header.button.setAttribute("aria-expanded", String(open?.column.key === key));
      header.mark.textContent = activeSort ? (sort.direction === "asc" ? "↑" : "↓") : activeFilter ? "●" : "⌄";
      if (activeSort) header.th.setAttribute("aria-sort", sort.direction === "asc" ? "ascending" : "descending");
      else header.th.removeAttribute("aria-sort");
    }
  };
  const cellControl = (column, row) => {
    const hasPoster = column.key === "poster" && Boolean(row.poster);
    const opensSource = hasPoster && Boolean(row.sourceUrl);
    const control = create(opensSource ? "a" : "button", "contest-cell");
    if (opensSource) {
      control.classList.add("contest-poster-link");
      control.href = row.sourceUrl;
      control.target = "_blank";
      control.rel = "noopener noreferrer";
      control.setAttribute("aria-label", row.name + " 공고 원문 열기");
    } else {
      control.type = "button";
      control.addEventListener("click", () => showMenu(column, control));
    }
    if (hasPoster) {
      const poster = create("img", "contest-poster");
      poster.src = row.poster;
      poster.alt = row.name + " 포스터";
      poster.loading = "lazy";
      poster.decoding = "async";
      poster.addEventListener("error", () => { poster.replaceWith(document.createTextNode("—")); }, { once: true });
      control.append(poster);
    } else if (column.key === "deadline" && row.end) {
      const period = create("span", "contest-date");
      const end = create("time", null, shortDate(row.end) + " 마감");
      end.dateTime = row.end;
      const day = create("span", "contest-day", row.day);
      day.dataset.soon = String(row.days >= 0 && row.days <= 3);
      const range = create("small", "contest-date-short", shortDate(row.start) + " ~ " + shortDate(row.end));
      const fullRange = create("small", "contest-date-full", (row.start || "—") + " ~ " + row.end);
      period.append(end, day, range, fullRange);
      control.append(period);
    } else {
      if (column.key === "name") control.classList.add("contest-title");
      const value = row[column.key];
      if (column.key === "total" && value) control.append(create("span", "contest-prize-label", "총 상금 "));
      control.append(create("span", "contest-value", value || "—"));
      if (column.key === "total" && row.first) {
        control.append(create("small", "contest-first-inline", "1등 " + row.first));
      }
      if (value) control.title = value;
      else if (column.key !== "total" || !row.first) control.setAttribute("aria-label", column.label + " 미기재");
    }
    return control;
  };
  function linkControl(column, row) {
    const originals = column.key === "source" ? sourceLinks(row) : [];
    const homepage = column.key === "homepage" ? row.homepage : null;
    if (!originals.length && !homepage) return cellControl(column, row);

    const controls = create("div", "contest-link");
    const links = create("div", "contest-link-list");
    const totals = new Map();
    const numbered = new Map();
    for (const original of originals) {
      totals.set(original.source, (totals.get(original.source) || 0) + 1);
    }
    for (const original of homepage ? [{ url: homepage }] : originals) {
      const site = original.source;
      const number = (numbered.get(site) || 0) + 1;
      numbered.set(site, number);
      const label = homepage ? "열기" : totals.get(site) > 1 ? site + " " + number : site;
      const link = create("a", null, label + " ↗");
      link.href = original.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", homepage ? "공식 홈페이지 열기" : label + " 공고 원문 열기");
      links.append(link);
    }
    const trigger = create("button", null, "⌄");
    trigger.type = "button";
    trigger.setAttribute("aria-label", column.label + " 정렬 및 필터");
    trigger.addEventListener("click", () => showMenu(column, trigger));
    controls.append(links, trigger);
    return controls;
  }
  const render = () => {
    const terms = search.value.trim().toLocaleLowerCase("ko").split(/\s+/).filter(Boolean);
    const column = columns.find(item => item.key === sort.key);
    const visible = rows.filter(row => {
      const haystack = columns.map(item => displayValue(item, row))
        .concat(row.start, row.end, row.day, row.homepage, sourceLinks(row).map(link => link.title))
        .join(" ").toLocaleLowerCase("ko");
      return terms.every(term => haystack.includes(term))
        && (!sourceFilter.value || sourceNames(row).includes(sourceFilter.value))
        && columns.every(item => !filters.has(item.key)
          || filterValues(item, row).some(value => filters.get(item.key).has(value)));
    });
    visible.sort((left, right) => {
      const a = column.order ? column.order(left) : displayValue(column, left);
      const b = column.order ? column.order(right) : displayValue(column, right);
      if (a == null || a === "미기재") return b == null || b === "미기재" ? 0 : 1;
      if (b == null || b === "미기재") return -1;
      const comparison = typeof a === "number" && typeof b === "number" ? a - b : collator.compare(a, b);
      return sort.direction === "asc" ? comparison : -comparison;
    });
    body.replaceChildren();
    if (visible.length === 0) {
      const tr = create("tr");
      tr.setAttribute("role", "row");
      const message = rows.length
        ? "조건에 맞는 공모전이 없습니다."
        : collecting ? "사이트에서 공고를 가져오는 중입니다." : "표시할 공고가 없습니다.";
      const td = create("td", "contest-empty", message);
      td.setAttribute("role", "cell");
      td.colSpan = columnsToggle.getAttribute("aria-pressed") === "true" ? columns.length : columns.filter(item => !item.extra).length;
      tr.append(td);
      body.append(tr);
    }
    for (const row of visible) {
      const tr = create("tr");
      tr.setAttribute("role", "row");
      for (const field of columns) {
        const td = create("td");
        td.setAttribute("role", "cell");
        setColumn(td, field);
        td.append(field.key === "source" || field.key === "homepage" ? linkControl(field, row) : cellControl(field, row));
        if (field.key === "name" && row.organizer) {
          td.append(create("small", "contest-organizer-inline", [...new Set(row.organizer.split(/\s*\/\s*/))].join(" / ")));
        }
        if (field.key === "total") {
          td.dataset.hasTotal = String(Boolean(row.total));
          td.dataset.hasPrize = String(Boolean(row.total || row.first));
        }
        tr.append(td);
      }
      body.append(tr);
    }
    const linkCount = visible.reduce((sum, row) => sum + sourceLinks(row).length, 0);
    count.textContent = "공모전 " + visible.length + "건 · 원문 " + linkCount + "개";
    reset.hidden = filters.size === 0 && !search.value && !sourceFilter.value;
    mobileSort.textContent = sort.key === "deadline" && sort.direction === "desc" ? "마감 먼 순" : "마감 가까운 순";
    setHeaderState();
  };
  function hideMenu(restoreFocus = false) {
    const previous = open;
    if (!previous) return;
    open = null;
    menu.hidden = true;
    setHeaderState();
    if (restoreFocus) {
      const target = previous.anchor.isConnected ? previous.anchor : headers.get(previous.column.key).button;
      target.focus();
    }
  }
  function showMenu(column, anchor) {
    if (open?.anchor === anchor) {
      hideMenu();
      return;
    }
    open = { column, anchor };
    find("#contest-menu-title").textContent = column.label;
    options.replaceChildren();
    const values = [...new Set(rows.flatMap(row => filterValues(column, row)))].sort(collator.compare);
    for (const value of values) {
      const label = create("label");
      const checkbox = create("input");
      checkbox.type = "checkbox";
      checkbox.value = value;
      checkbox.checked = !filters.has(column.key) || filters.get(column.key).has(value);
      label.append(checkbox, document.createTextNode(value));
      options.append(label);
    }
    for (const button of menu.querySelectorAll("[data-sort]")) {
      button.setAttribute("aria-pressed", String(sort.key === column.key && sort.direction === button.dataset.sort));
    }
    menu.hidden = false;
    const bounds = find(".contest-data").getBoundingClientRect();
    const position = anchor.getBoundingClientRect();
    const menuTop = position.bottom + menu.offsetHeight > window.innerHeight
      && position.top - bounds.top >= menu.offsetHeight ? position.top - menu.offsetHeight : position.bottom;
    menu.style.top = Math.max(0, menuTop - bounds.top) + "px";
    menu.style.left = Math.max(6, Math.min(position.left - bounds.left, bounds.width - menu.offsetWidth - 6)) + "px";
    setHeaderState();
    menu.querySelector("[data-sort]").focus();
  }
  find(".contest-apply").addEventListener("click", () => {
    const key = open.column.key;
    const selected = [...options.querySelectorAll("input:checked")].map(input => input.value);
    if (selected.length === options.children.length) filters.delete(key);
    else filters.set(key, new Set(selected));
    render();
    hideMenu(true);
  });
  for (const button of menu.querySelectorAll("[data-sort]")) {
    button.addEventListener("click", () => {
      sort = { key: open.column.key, direction: button.dataset.sort };
      render();
      hideMenu(true);
    });
  }
  find(".contest-close").addEventListener("click", () => hideMenu(true));
  board.addEventListener("keydown", event => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      hideMenu(true);
    }
  });
  board.addEventListener("click", event => {
    if (open && !menu.contains(event.target) && !open.anchor.contains(event.target)) hideMenu();
  });
  find(".contest-scroll").addEventListener("scroll", () => hideMenu());
  search.addEventListener("input", () => {
    hideMenu();
    render();
  });
  sourceFilter.addEventListener("change", () => {
    hideMenu();
    render();
  });
  columnsToggle.addEventListener("click", () => {
    hideMenu();
    const expanded = columnsToggle.getAttribute("aria-pressed") !== "true";
    columnsToggle.setAttribute("aria-pressed", String(expanded));
    columnsToggle.textContent = expanded ? "주요 열" : "전체 열";
    board.dataset.full = String(expanded);
    if (!expanded) find(".contest-scroll").scrollLeft = 0;
    render();
  });
  mobileSort.addEventListener("click", () => {
    hideMenu();
    sort = { key: "deadline", direction: sort.key === "deadline" && sort.direction === "asc" ? "desc" : "asc" };
    render();
  });
  reset.addEventListener("click", () => {
    hideMenu();
    search.value = "";
    sourceFilter.value = "";
    filters.clear();
    render();
    search.focus();
  });

  const refresh = find(".contest-refresh");
  const resultLabels = { pending: "대기", collecting: "수집 중", error: "수집 실패", partial: "일부 수집" };
  let timer;
  let requestId = 0;
  let resultsVersion;

  function nextBoardCheck(state) {
    if (state.running) return 1200;
    const nextMidnight = Date.parse(state.today + "T00:00:00+09:00") + 86_400_000;
    let nextChange = nextMidnight;
    for (const row of state.contests) {
      const closes = Date.parse(row.closesAt);
      if (Number.isFinite(closes)) nextChange = Math.min(nextChange, closes);
    }
    return Math.max(250, nextChange - Date.now());
  }

  function showBoard(state) {
    collecting = state.running;
    const version = JSON.stringify([
      state.today, state.contests, !state.contests.length && state.running, state.sources.map(site => site.name),
    ]);
    if (version !== resultsVersion) {
      resultsVersion = version;
      const today = Date.parse(state.today);
      rows = state.contests.map(row => {
        if (!row.end) return row;
        const days = (Date.parse(row.end) - today) / 86400000;
        const day = days === 0 ? "D-day" : days > 0 ? "D-" + days : "D+" + Math.abs(days);
        return { ...row, day, days };
      });
      const selected = sourceFilter.value;
      const available = [...new Set([
        ...state.sources.map(site => site.name), ...rows.flatMap(row => sourceLinks(row).map(link => link.source)),
      ])].sort(collator.compare);
      sourceFilter.replaceChildren(new Option("전체", ""), ...available.map(name => new Option(name, name)));
      sourceFilter.value = available.includes(selected) ? selected : "";
      render();
    }
    sources.replaceChildren();
    for (const site of state.sources) {
      const item = create("li", "contest-source");
      const link = create("a", null, site.name);
      link.href = site.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", site.name + " 공모전 목록 열기");
      const detail = site.state === "ok"
        ? site.count + "건"
        : resultLabels[site.state] + (site.count ? " · " + site.count + "건" : "");
      item.dataset.state = site.state;
      const status = create("span", "contest-source-state", detail);
      if (site.message) status.title = site.message;
      item.append(link, status);
      sources.append(item);
    }
    const unavailable = state.sources.filter(site => ["error", "partial"].includes(site.state));
    collection.hidden = !state.running && !unavailable.length;
    if (state.running) {
      const finished = state.sources.filter(site => site.state !== "collecting").length;
      collection.textContent = "공고 수집 중 · " + finished + " / " + state.sources.length + "곳 완료";
    } else {
      collection.textContent = unavailable.map(site => site.name + " · " + site.message).join(" / ");
    }
    refresh.disabled = state.running;
  }

  async function loadBoard(refreshRequested = false) {
    window.clearTimeout(timer);
    const current = ++requestId;
    if (refreshRequested) refresh.disabled = true;
    try {
      const response = refreshRequested
        ? await fetch("/api/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
        : await fetch("/api/contests");
      if (!response.ok) throw new Error("Unable to load contests");
      const state = await response.json();
      if (current !== requestId) return;
      showBoard(state);
      timer = window.setTimeout(loadBoard, nextBoardCheck(state));
    } catch {
      if (current !== requestId) return;
      refresh.disabled = false;
      collection.hidden = false;
      collection.textContent = "로컬 수집 서버에 연결할 수 없습니다. 서버를 확인한 뒤 새로고침하세요.";
      timer = window.setTimeout(loadBoard, 5000);
    }
  }

  refresh.addEventListener("click", () => loadBoard(true));
  render();
  loadBoard();
})();

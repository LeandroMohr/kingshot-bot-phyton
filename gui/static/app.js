"use strict";

const RUN_PAGE = "run";

const state = {
  sections: [],
  generalHowto: [],
  bots: [],
  defaultHost: "127.0.0.1",
  devices: [],        // [{host, port}] found by the scan or added manually
  accounts: [],
  accountId: localStorage.getItem("accountId"),
  page: localStorage.getItem("page") || RUN_PAGE,
  logPort: null,
  logCursor: 0,
};

// -- helpers ----------------------------------------------------------------
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, body) {
  const headers = { "X-Lang": lang };
  const options = body === undefined ? { headers } : {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || tr("error.http", { status: res.status }));
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, isError ? 5000 : 2000);
}

function formatInterval(seconds) {
  if (seconds >= 3600) return `${+(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}min`;
  return `${Math.round(seconds)}s`;
}

function formatTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

// Polling re-renders every 2s; replacing unchanged buttons would swallow clicks.
const lastRender = {};
function changed(key, value) {
  const signature = JSON.stringify(value);
  if (lastRender[key] === signature) return false;
  lastRender[key] = signature;
  return true;
}

// -- accounts -----------------------------------------------------------------
function currentAccount() {
  return state.accounts.find((a) => a.account_id === state.accountId) || null;
}

function prefsOf(account) {
  return (account && account.preferences) || {};
}

function disabledTasks() {
  const list = prefsOf(currentAccount()).disabled_tasks;
  return new Set(Array.isArray(list) ? list : []);
}

function renderAccountBar() {
  const select = document.getElementById("account-select");
  if (!state.accounts.length) {
    select.replaceChildren(el("option", { value: "" }, tr("account.none")));
    select.disabled = true;
  } else {
    select.disabled = false;
    select.replaceChildren(...state.accounts.map((a) => el("option", {
      value: a.account_id,
      selected: a.account_id === state.accountId,
    }, a.profile.name ? `${a.profile.name} (${a.account_id})` : a.account_id)));
  }
  const account = currentAccount();
  const profile = (account && account.profile) || {};
  const vip = prefsOf(account).vip_level;
  document.getElementById("account-info").textContent = [
    profile.kingdom && tr("account.kingdom", { value: profile.kingdom }),
    profile.power && tr("account.power", { value: profile.power }),
    profile.alliance && tr("account.alliance", { value: profile.alliance }),
    vip != null && `VIP ${vip}`,
  ].filter(Boolean).join(" · ");
}

async function loadAccounts(force = true) {
  const { accounts } = await api("/api/accounts");
  const signature = accounts.map((a) => [a.account_id, a.profile.name, a.preferences.vip_level]);
  if (!changed("accounts", signature) && !force) return;
  const hadAccount = !!currentAccount();
  state.accounts = accounts;
  if (!accounts.some((a) => a.account_id === state.accountId)) {
    state.accountId = accounts.length ? accounts[0].account_id : null;
  }
  renderAccountBar();
  if (!force) {
    renderMenu();
    if (!hadAccount) renderPage();
  }
}

function selectAccount(accountId) {
  state.accountId = accountId;
  localStorage.setItem("accountId", accountId);
  renderAccountBar();
  renderMenu();
  renderPage();
}

async function addAccount(event) {
  event.preventDefault();
  const input = document.getElementById("add-account-id");
  const accountId = input.value.trim();
  try {
    await api("/api/accounts/prefs", { account_id: accountId, preferences: {} });
    input.value = "";
    await loadAccounts();
    selectAccount(accountId);
    toast(tr("account.added"));
  } catch (err) {
    toast(err.message, true);
  }
}

async function savePrefs(changes) {
  const account = currentAccount();
  if (!account) return false;
  try {
    await api("/api/accounts/prefs", { account_id: account.account_id, preferences: changes });
    Object.assign(account.preferences, changes);
    toast(tr("saved"));
    return true;
  } catch (err) {
    toast(err.message, true);
    return false;
  }
}

// -- menu / pages -------------------------------------------------------------
function renderMenu() {
  const disabled = disabledTasks();
  const hasAccount = !!currentAccount();
  const items = [{ id: RUN_PAGE, title: tr("page.run"), count: null }].concat(state.sections.map((s) => ({
    id: s.id,
    title: s.title,
    count: hasAccount && s.tasks.length
      ? `${s.tasks.filter((t) => !disabled.has(t.task)).length}/${s.tasks.length}` : null,
  })));
  document.getElementById("menu").replaceChildren(...items.map((item) => el("button", {
    class: `menu-item ${item.id === state.page ? "active" : ""}`,
    onclick: () => showPage(item.id),
  }, [el("span", {}, item.title), item.count && el("span", { class: "count" }, item.count)])));
}

function showPage(id) {
  state.page = id;
  localStorage.setItem("page", id);
  renderMenu();
  renderPage();
}

function renderPage() {
  const section = state.sections.find((s) => s.id === state.page);
  if (!section) state.page = RUN_PAGE;
  const runPage = document.getElementById("page-run");
  const settingsPage = document.getElementById("page-settings");
  runPage.hidden = !!section;
  settingsPage.hidden = !section;
  document.getElementById("page-title").textContent = section ? section.title : tr("page.run");
  if (section) renderSection(settingsPage, section);
}

// -- how-to -------------------------------------------------------------------
function howtoBlocks(blocks) {
  return blocks.map((block) => {
    switch (block.type) {
      case "h": return el("h4", {}, block.text);
      case "steps": return el("ol", {}, block.items.map((item) => el("li", {}, item)));
      case "list": return el("ul", {}, block.items.map((item) => el("li", {}, item)));
      case "tip": return el("div", { class: "callout tip" }, [el("strong", {}, tr("howto.tip")), block.text]);
      case "warn": return el("div", { class: "callout warn" }, [el("strong", {}, tr("howto.warn")), block.text]);
      default: return el("p", {}, block.text);
    }
  });
}

function howto(title, blocks) {
  return el("details", { class: "howto" }, [
    el("summary", {}, title),
    el("div", { class: "howto-body" }, howtoBlocks(blocks)),
  ]);
}

// -- settings sections --------------------------------------------------------
// Every on/off option uses this switch; onToggle returns false to undo the flip.
function onOffSwitch(checked, onToggle, title) {
  const input = el("input", { type: "checkbox", checked, "aria-label": title });
  const text = el("span", { class: "switch-text" }, checked ? "ON" : "OFF");
  input.addEventListener("change", async () => {
    if (!await onToggle(input.checked)) input.checked = !input.checked;
    text.textContent = input.checked ? "ON" : "OFF";
  });
  return el("label", { class: "switch", title }, [input, el("span", { class: "slider" }), text]);
}

function fieldControl(field, prefs) {
  const value = prefs[field.key] ?? field.default;
  if (field.type === "bool") {
    return onOffSwitch(!!value, (on) => savePrefs({ [field.key]: on }), field.label);
  }
  if (field.type === "choice") {
    return el("select", {
      onchange: async (e) => {
        if (!await savePrefs({ [field.key]: e.target.value })) e.target.value = prefs[field.key] ?? field.default;
      },
    }, field.choices.map((c) => el("option", { value: c.value, selected: c.value === value }, c.label)));
  }
  return el("input", {
    type: "number",
    min: field.min,
    max: field.max,
    step: 1,
    value,
    onchange: async (e) => {
      const input = e.target;
      const number = Number(input.value);
      const previous = prefs[field.key] ?? field.default;
      if (!Number.isInteger(number) || number < field.min || number > field.max) {
        toast(tr("field.range", { label: field.label, min: field.min, max: field.max }), true);
        input.value = previous;
        return;
      }
      if (!await savePrefs({ [field.key]: number })) input.value = previous;
    },
  });
}

function fieldLabel(field, prefs) {
  const control = fieldControl(field, prefs);
  const range = field.type === "int" ? `${field.min}–${field.max}` : null;
  // The switch is already a <label>, so on/off fields can't be wrapped in another one.
  return el(field.type === "bool" ? "div" : "label", { class: "field" }, [
    el("span", {}, [field.label, range && el("small", { class: "muted" }, ` (${range})`)]),
    control,
    field.help && el("small", { class: "muted" }, field.help),
  ]);
}

function renderFields(fields, prefs) {
  const nodes = [];
  const groups = new Map();
  for (const field of fields) {
    if (!field.group) {
      nodes.push(fieldLabel(field, prefs));
      continue;
    }
    let group = groups.get(field.group.id);
    if (!group) {
      group = el("div", { class: "field-row" }, el("div", { class: "row-title" }, [
        el("strong", {}, field.group.label),
        field.group.hint && el("small", { class: "muted" }, field.group.hint),
      ]));
      groups.set(field.group.id, group);
      nodes.push(group);
    }
    group.append(fieldLabel(field, prefs));
  }
  return nodes;
}

function taskCard(task, prefs, disabled) {
  const enabled = !disabled.has(task.task);
  const schedule = task.schedule
    || (task.loop ? tr("task.every", { interval: formatInterval(task.interval) }) : tr("task.once"));
  const toggle = onOffSwitch(enabled, async (on) => {
    const next = disabledTasks();
    if (on) next.delete(task.task);
    else next.add(task.task);
    if (!await savePrefs({ disabled_tasks: [...next] })) return false;
    card.classList.toggle("off", !on);
    renderMenu();
    return true;
  }, tr("task.toggle"));
  const card = el("article", { class: `task-card ${enabled ? "" : "off"}` }, [
    el("div", { class: "task-head" }, [
      toggle,
      el("div", { class: "grow" }, [
        el("h3", {}, task.title),
        task.summary && el("p", { class: "muted small" }, task.summary),
      ]),
      el("span", { class: "badge" }, schedule),
    ]),
    task.fields.length ? el("div", { class: "task-fields" }, renderFields(task.fields, prefs)) : null,
    task.howto.length ? howto(tr("howto.title"), task.howto) : null,
  ]);
  return card;
}

function renderSection(container, section) {
  const account = currentAccount();
  if (!account) {
    container.replaceChildren(el("section", { class: "card empty" }, [
      el("h2", {}, tr("noAccount.title")),
      el("p", {}, tr("noAccount.text")),
    ]));
    return;
  }
  const prefs = prefsOf(account);
  const disabled = disabledTasks();
  container.replaceChildren(
    ...section.tasks.map((task) => taskCard(task, prefs, disabled)),
    ...(section.panels || []).map((panel) => panelCard(panel, account.account_id)),
  );
}

function panelCard(panel, accountId) {
  const body = el("div", { class: "panel-body" }, el("p", { class: "muted" }, tr("loading")));
  Planning.mount(panel.id, body, accountId);
  return el("article", { class: "task-card panel-card" }, [
    el("div", { class: "task-head" }, el("div", { class: "grow" }, [
      el("h3", {}, panel.title),
      panel.summary && el("p", { class: "muted small" }, panel.summary),
    ])),
    body,
    panel.howto && panel.howto.length ? howto(tr("howto.title"), panel.howto) : null,
  ]);
}

// -- emulators ----------------------------------------------------------------
function botFor(port) {
  return state.bots.find((b) => b.port === port);
}

function addDevice(host, port) {
  if (!state.devices.some((d) => d.port === port)) state.devices.push({ host, port });
  state.devices.sort((a, b) => a.port - b.port);
}

function renderEmulators() {
  const box = document.getElementById("emulators");
  for (const bot of state.bots) addDevice(bot.host, bot.port);
  if (!changed("emulators", [lang, state.devices, state.bots])) return;
  if (!state.devices.length) {
    box.replaceChildren(el("p", { class: "muted" }, tr("emu.none")));
    return;
  }
  box.replaceChildren(...state.devices.map(({ host, port }) => {
    const bot = botFor(port);
    const running = bot && bot.running;
    const paused = running && bot.paused;
    let info = tr("emu.stopped");
    if (paused) info = tr("emu.paused");
    else if (running) info = tr("emu.runningSince", { time: formatTime(bot.started_at) });
    else if (bot && bot.exit_code != null) info = tr("emu.exited", { code: bot.exit_code });
    const controls = running
      ? [paused
          ? el("button", { onclick: () => botAction(port, "resume") }, tr("bot.resume"))
          : el("button", { class: "warn", onclick: () => botAction(port, "pause") }, tr("bot.pause")),
        el("button", { class: "danger", onclick: () => botAction(port, "stop") }, tr("bot.stop"))]
      : [el("button", { onclick: () => startBot(host, port) }, tr("bot.start"))];
    return el("div", { class: "emulator" }, [
      el("span", { class: `dot ${paused ? "paused" : running ? "on" : ""}` }),
      el("div", { class: "grow" }, [
        el("strong", {}, tr("emu.name", { port })),
        el("div", { class: "muted small" }, `${host}:${port} · ${info}`),
      ]),
      ...controls,
      el("button", { class: "ghost", onclick: () => showLog(port), disabled: !bot }, tr("logs.title")),
    ]);
  }));
}

async function scanDevices() {
  const button = document.getElementById("scan-btn");
  button.disabled = true;
  button.textContent = tr("emu.scanning");
  try {
    const { devices } = await api("/api/devices");
    devices.forEach((d) => addDevice(d.host, d.port));
    renderEmulators();
    toast(devices.length ? tr("emu.found", { count: devices.length }) : tr("emu.notFound"));
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = tr("emu.scan");
  }
}

async function startBot(host, port) {
  try {
    await api("/api/bots/start", { host, port });
    toast(tr("bot.started", { port }));
    await refreshBots();
    showLog(port);
  } catch (err) {
    toast(err.message, true);
  }
}

const BOT_ACTIONS = {
  pause: ["bot.pausing", "bot.paused"],
  resume: ["bot.resuming", "bot.resumed"],
  stop: ["bot.stopping", "bot.stopped"],
};

async function botAction(port, action) {
  const [doing, done] = BOT_ACTIONS[action];
  try {
    toast(tr(doing, { port }));
    await api(`/api/bots/${action}`, { port });
    toast(tr(done));
    await refreshBots();
  } catch (err) {
    toast(err.message, true);
  }
}

// -- logs ---------------------------------------------------------------------
function renderLogTabs() {
  const tabs = document.getElementById("log-tabs");
  if (!changed("tabs", [lang, state.logPort, state.bots.map((b) => [b.port, b.running, b.paused])])) return;
  tabs.replaceChildren(...state.bots.map((bot) => el("button", {
    class: `tab ${bot.port === state.logPort ? "active" : ""}`,
    onclick: () => showLog(bot.port),
  }, `${bot.port}${bot.paused ? tr("logs.paused") : bot.running ? "" : tr("logs.stopped")}`)));
}

function showLog(port) {
  if (state.logPort !== port) {
    state.logPort = port;
    state.logCursor = 0;
    document.getElementById("log").textContent = "";
  }
  renderLogTabs();
  pollLogs();
}

async function pollLogs() {
  if (state.logPort == null) return;
  const port = state.logPort;
  try {
    const data = await api(`/api/logs?port=${port}&since=${state.logCursor}`);
    if (port !== state.logPort || !data.lines.length) return;
    const log = document.getElementById("log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.append(data.lines.map((l) => `[${formatTime(l.ts)}] ${l.text}\n`).join(""));
    state.logCursor = data.cursor;
    if (atBottom) log.scrollTop = log.scrollHeight;
  } catch { /* the bot may have been replaced; next poll retries */ }
}

// -- polling / init -----------------------------------------------------------
async function refreshBots() {
  const data = await api("/api/state");
  state.bots = data.bots;
  renderEmulators();
  renderLogTabs();
  const paused = state.bots.filter((b) => b.running && b.paused).length;
  const running = state.bots.filter((b) => b.running).length - paused;
  document.getElementById("status").textContent =
    tr("status.running", { count: running }) + (paused ? tr("status.paused", { count: paused }) : "");
}

// Re-fetch the server-translated schema and redraw everything in the current language.
async function loadSchema() {
  const data = await api("/api/state");
  state.sections = data.sections;
  state.generalHowto = data.general_howto;
  state.defaultHost = data.default_host;
  state.bots = data.bots;
  document.getElementById("general-howto").replaceChildren(el("summary", {}, tr("howto.general")),
    el("div", { class: "howto-body" }, howtoBlocks(state.generalHowto)));
}

async function changeLang(value) {
  setLang(value);
  try {
    await loadSchema();
    renderAccountBar();
    renderMenu();
    renderPage();
    await refreshBots();
  } catch (err) {
    toast(err.message, true);
  }
}

async function init() {
  const langSelect = document.getElementById("lang-select");
  langSelect.replaceChildren(...Object.entries(LANGUAGES).map(([code, name]) =>
    el("option", { value: code, selected: code === lang }, name)));
  langSelect.addEventListener("change", (e) => changeLang(e.target.value));
  applyStaticTexts();

  document.getElementById("scan-btn").addEventListener("click", scanDevices);
  document.getElementById("add-account-form").addEventListener("submit", addAccount);
  document.getElementById("account-select").addEventListener("change", (e) => selectAccount(e.target.value));
  document.getElementById("manual-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("manual-port");
    addDevice(state.defaultHost, Number.parseInt(input.value, 10));
    input.value = "";
    renderEmulators();
  });

  try {
    await loadSchema();
    await loadAccounts();
    renderMenu();
    renderPage();
    await refreshBots();
  } catch (err) {
    toast(err.message, true);
  }

  setInterval(() => refreshBots().catch(() => {}), 2000);
  setInterval(() => loadAccounts(false).catch(() => {}), 5000);
  setInterval(pollLogs, 1000);
}

init();

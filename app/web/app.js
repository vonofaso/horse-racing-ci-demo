const entityConfig = {
  competitions: {
    title: "Состязания",
    columns: [["name", "Название"], ["event_date", "Дата"], ["location", "Место"], ["distance_m", "Дистанция"], ["status", "Статус"], ["prize_fund_rub", "Призовой фонд"]],
    fields: [
      ["name", "Название", "text"], ["event_date", "Дата проведения", "date"],
      ["location", "Место проведения", "text"], ["distance_m", "Дистанция, м", "number"],
      ["status", "Статус", "select", {planned: "Запланировано", ongoing: "Идёт", completed: "Завершено", cancelled: "Отменено"}],
      ["prize_fund_rub", "Призовой фонд, ₽", "number"],
    ],
  },
  horses: {
    title: "Лошади",
    columns: [["name", "Кличка"], ["breed", "Порода"], ["birth_date", "Дата рождения"], ["owner_id", "Владелец"]],
    fields: [["name", "Кличка", "text"], ["breed", "Порода", "text"], ["birth_date", "Дата рождения", "date"], ["owner_id", "Владелец", "relation", "owners"]],
  },
  jockeys: {
    title: "Жокеи",
    columns: [["full_name", "ФИО"], ["birth_date", "Дата рождения"], ["weight_kg", "Вес, кг"]],
    fields: [["full_name", "ФИО", "text"], ["birth_date", "Дата рождения", "date"], ["weight_kg", "Вес, кг", "number-step"]],
  },
  owners: {
    title: "Владельцы",
    columns: [["name", "Имя / организация"], ["contact", "Контакты"]],
    fields: [["name", "Имя или организация", "text"], ["contact", "Контактные данные", "text-optional"]],
  },
  results: {
    title: "Результаты",
    columns: [["competition_id", "Состязание"], ["horse_id", "Лошадь"], ["jockey_id", "Жокей"], ["position", "Место"], ["time_seconds", "Время, с"], ["disqualified", "Статус"]],
    fields: [
      ["competition_id", "Состязание", "relation", "competitions"], ["horse_id", "Лошадь", "relation", "horses"],
      ["jockey_id", "Жокей", "relation", "jockeys"], ["position", "Место", "number"],
      ["time_seconds", "Время, с", "number-step"], ["disqualified", "Дисквалификация", "checkbox"],
      ["disqualification_reason", "Причина дисквалификации", "text-optional"],
    ],
  },
};

const state = { current: "overview", data: {}, editingId: null, user: null };
const $ = (selector) => document.querySelector(selector);

function toast(message, error = false) {
  const box = $("#toast");
  box.textContent = message;
  box.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.className = "toast", 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) showAuth();
    const details = payload.error?.details?.map((item) => item.message).join("; ");
    throw new Error(details || payload.error?.message || "Не удалось выполнить запрос");
  }
  return payload;
}

function showAuth() {
  $("#auth-view").classList.remove("hidden");
  $("#app-view").classList.add("hidden");
}

function showApp(user) {
  state.user = user;
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#user-name").textContent = user.username;
  $("#user-email").textContent = user.email;
  $("#user-avatar").textContent = user.username[0].toUpperCase();
  loadAll();
}

async function loadAll() {
  try {
    const keys = Object.keys(entityConfig);
    const rows = await Promise.all(keys.map((key) => api(`/${key}`)));
    keys.forEach((key, index) => state.data[key] = rows[index]);
    renderOverview();
    if (state.current !== "overview") renderTable();
  } catch (error) { toast(error.message, true); }
}

function relationName(entity, id) {
  const item = (state.data[entity] || []).find((row) => row.id === Number(id));
  return item?.name || item?.full_name || `#${id}`;
}

function statusLabel(value) {
  return {planned: "Запланировано", ongoing: "Идёт", completed: "Завершено", cancelled: "Отменено"}[value] || value;
}

function displayValue(key, value) {
  const relations = {owner_id: "owners", competition_id: "competitions", horse_id: "horses", jockey_id: "jockeys"};
  if (relations[key]) return relationName(relations[key], value);
  if (key === "status") return statusLabel(value);
  if (key === "prize_fund_rub") return `${Number(value).toLocaleString("ru-RU")} ₽`;
  if (key === "disqualified") return value ? "Дисквалификация" : "Зачтён";
  if (key.includes("date") && value) return new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU");
  return value ?? "—";
}

function renderOverview() {
  const cards = [
    ["competitions", "Состязаний"], ["horses", "Лошадей"], ["jockeys", "Жокеев"], ["owners", "Владельцев"],
  ];
  $("#stats").innerHTML = cards.map(([key, label], index) => `<article class="stat-card ${index === 0 ? "featured" : ""}"><span>${label}</span><strong>${state.data[key]?.length || 0}</strong></article>`).join("");

  const events = [...(state.data.competitions || [])].sort((a, b) => a.event_date.localeCompare(b.event_date)).slice(0, 4);
  $("#upcoming-list").innerHTML = events.length ? events.map((item) => {
    const date = new Date(`${item.event_date}T00:00:00`);
    return `<div class="event-row"><div class="event-date"><strong>${date.getDate()}</strong><small>${date.toLocaleDateString("ru-RU", {month: "short"})}</small></div><div><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.location)} · ${item.distance_m} м</p></div><span class="status-pill">${statusLabel(item.status)}</span></div>`;
  }).join("") : `<p class="muted">События ещё не добавлены.</p>`;

  const results = [...(state.data.results || [])].sort((a, b) => b.id - a.id).slice(0, 5);
  $("#latest-results").innerHTML = results.length ? results.map((item) => `<div class="result-row"><span class="result-place">${item.position}</span><div><p>${escapeHtml(relationName("horses", item.horse_id))}</p><small>${escapeHtml(relationName("competitions", item.competition_id))} · ${item.time_seconds} с</small></div></div>`).join("") : `<p class="muted">Результаты ещё не внесены.</p>`;
}

function switchView(view) {
  state.current = view;
  $("#overview").classList.toggle("active-view", view === "overview");
  $("#entity-view").classList.toggle("active-view", view !== "overview");
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $("#page-title").textContent = view === "overview" ? "Обзор" : entityConfig[view].title;
  $("#add-button").classList.toggle("hidden", view === "overview");
  $("#search-input").value = "";
  if (view !== "overview") renderTable();
  $(".sidebar").classList.remove("open");
}

function renderTable() {
  const config = entityConfig[state.current];
  const query = $("#search-input").value.trim().toLowerCase();
  const rows = (state.data[state.current] || []).filter((row) => Object.entries(row).some(([key, value]) => String(displayValue(key, value)).toLowerCase().includes(query)));
  $("#table-head").innerHTML = `<tr>${config.columns.map(([, label]) => `<th>${label}</th>`).join("")}<th></th></tr>`;
  $("#table-body").innerHTML = rows.map((row) => `<tr>${config.columns.map(([key]) => `<td>${escapeHtml(String(displayValue(key, row[key])))}</td>`).join("")}<td><div class="row-actions"><button data-edit="${row.id}">Изменить</button><button class="danger" data-delete="${row.id}">Удалить</button></div></td></tr>`).join("");
  $("#record-count").textContent = `${rows.length} ${declension(rows.length, ["запись", "записи", "записей"])}`;
  $(".table-wrap").classList.toggle("hidden", rows.length === 0);
  $("#empty-state").classList.toggle("hidden", rows.length !== 0);
}

function declension(number, forms) {
  const n10 = number % 10, n100 = number % 100;
  return forms[n10 === 1 && n100 !== 11 ? 0 : n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20) ? 1 : 2];
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}[char]));
}

function openDialog(id = null) {
  state.editingId = id;
  const config = entityConfig[state.current];
  const row = id ? state.data[state.current].find((item) => item.id === Number(id)) : {};
  $("#dialog-title").textContent = id ? `Изменить: ${config.title.toLowerCase()}` : `Добавить: ${config.title.toLowerCase()}`;
  $("#form-fields").innerHTML = config.fields.map(([name, label, type, options]) => fieldHtml(name, label, type, options, row?.[name])).join("");
  $("#entity-dialog").showModal();
}

function fieldHtml(name, label, type, options, value) {
  const safe = value ?? (name === "prize_fund_rub" ? 0 : "");
  if (type === "select") return `<label>${label}<select name="${name}" required>${Object.entries(options).map(([key, text]) => `<option value="${key}" ${key === safe ? "selected" : ""}>${text}</option>`).join("")}</select></label>`;
  if (type === "relation") {
    const rows = state.data[options] || [];
    return `<label>${label}<select name="${name}" required><option value="">Выберите…</option>${rows.map((item) => `<option value="${item.id}" ${item.id === safe ? "selected" : ""}>${escapeHtml(item.name || item.full_name)}</option>`).join("")}</select></label>`;
  }
  if (type === "checkbox") return `<label class="checkbox-label"><input name="${name}" type="checkbox" ${safe ? "checked" : ""}>${label}</label>`;
  const inputType = type === "number-step" ? "number" : type.replace("-optional", "");
  const required = type.includes("optional") ? "" : "required";
  const step = type === "number-step" ? 'step="0.1" min="0.1"' : type === "number" ? `step="1" min="${name === "prize_fund_rub" ? 0 : 1}"` : "";
  return `<label class="${name === "disqualification_reason" ? "full" : ""}">${label}<input name="${name}" type="${inputType}" value="${escapeHtml(String(safe))}" ${required} ${step}></label>`;
}

async function saveEntity(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  const config = entityConfig[state.current];
  config.fields.forEach(([name, , type]) => {
    if (type === "number" || type === "relation") data[name] = Number(data[name]);
    if (type === "number-step") data[name] = Number(data[name]);
    if (type === "checkbox") data[name] = event.currentTarget.elements[name].checked;
    if (type.includes("optional") && !data[name]) data[name] = null;
  });
  if (data.disqualified === false) data.disqualification_reason = null;
  try {
    const path = state.editingId ? `/${state.current}/${state.editingId}` : `/${state.current}`;
    await api(path, {method: state.editingId ? "PUT" : "POST", body: JSON.stringify(data)});
    $("#entity-dialog").close();
    toast(state.editingId ? "Изменения сохранены" : "Запись добавлена");
    await loadAll();
  } catch (error) { toast(error.message, true); }
}

async function deleteEntity(id) {
  if (!confirm("Удалить эту запись? Действие нельзя отменить.")) return;
  try {
    await api(`/${state.current}/${id}`, {method: "DELETE"});
    toast("Запись удалена");
    await loadAll();
  } catch (error) { toast(error.message, true); }
}

function bindEvents() {
  $("#switch-auth").addEventListener("click", () => {
    const registering = $("#register-form").classList.contains("hidden");
    $("#register-form").classList.toggle("hidden", !registering);
    $("#login-form").classList.toggle("hidden", registering);
    $("#auth-title").textContent = registering ? "Новый аккаунт" : "С возвращением";
    $("#auth-subtitle").textContent = registering ? "Зарегистрируйтесь для начала работы" : "Войдите, чтобы продолжить работу";
    $("#switch-question").textContent = registering ? "Уже зарегистрированы?" : "Нет аккаунта?";
    $("#switch-auth").textContent = registering ? "Войти" : "Зарегистрироваться";
  });
  ["login", "register"].forEach((mode) => $(`#${mode}-form`).addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const user = await api(`/auth/${mode}`, {method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form).entries()))});
      form.reset();
      showApp(user);
      toast(mode === "register" ? "Аккаунт создан" : "Вход выполнен");
    } catch (error) { toast(error.message, true); }
  }));
  $("#logout-button").addEventListener("click", async () => { await api("/auth/logout", {method: "POST"}); showAuth(); });
  $("#navigation").addEventListener("click", (event) => { const item = event.target.closest("[data-view]"); if (item) switchView(item.dataset.view); });
  document.addEventListener("click", (event) => { const go = event.target.closest("[data-go]"); if (go) switchView(go.dataset.go); });
  $("#add-button").addEventListener("click", () => openDialog());
  $("#search-input").addEventListener("input", renderTable);
  $("#table-body").addEventListener("click", (event) => { const edit = event.target.closest("[data-edit]"); const remove = event.target.closest("[data-delete]"); if (edit) openDialog(edit.dataset.edit); if (remove) deleteEntity(remove.dataset.delete); });
  $("#entity-form").addEventListener("submit", saveEntity);
  $("#dialog-close").addEventListener("click", () => $("#entity-dialog").close());
  $("#cancel-button").addEventListener("click", () => $("#entity-dialog").close());
  $("#menu-button").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
}

async function init() {
  bindEvents();
  $("#today").textContent = new Date().toLocaleDateString("ru-RU", {day: "numeric", month: "long", year: "numeric"});
  $("#add-button").classList.add("hidden");
  try { showApp(await api("/auth/me")); } catch { showAuth(); }
}

init();

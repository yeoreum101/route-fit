const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

let places = [];
let selected = null; // 편집 중인 장소 id. 새 장소면 null

// ---------- 지도 (좌표 고르기) ----------

const miniMap = L.map("mini-map").setView([35.1487, 126.9165], 15);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(miniMap);
const marker = L.marker([35.1487, 126.9165]);

function setPoint(lat, lng, pan = true) {
  marker.setLatLng([lat, lng]).addTo(miniMap);
  if (pan) miniMap.setView([lat, lng], Math.max(miniMap.getZoom(), 16));
}

miniMap.on("click", (e) => {
  $("f-lat").value = e.latlng.lat.toFixed(6);
  $("f-lng").value = e.latlng.lng.toFixed(6);
  setPoint(e.latlng.lat, e.latlng.lng, false);
});
for (const id of ["f-lat", "f-lng"]) {
  $(id).addEventListener("change", () => {
    const lat = Number($("f-lat").value), lng = Number($("f-lng").value);
    if (lat && lng) setPoint(lat, lng);
  });
}

// ---------- 목록 ----------

for (const [value, label] of Object.entries(CATEGORY_KO)) $("f-category").append(new Option(label, value));

// ---------- 태그 (data/tags.json) ----------

let tagGroups = [];

async function loadTags() {
  tagGroups = await fetch("/api/tags").then((r) => r.json());
  $("tag-groups").replaceChildren(...tagGroups.map((g) => {
    const row = el("div", "tag-group");
    row.dataset.key = g.key;
    const name = el("span", "tag-group-label", g.label);
    if (g.required) name.append(el("b", "req", " *"));
    if (!g.multiple) name.append(el("span", "muted small", " (하나)"));
    const chips = el("div", "tag-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-label", g.label);
    for (const v of g.values) {
      const b = el("button", "tag-chip", v);
      b.type = "button";
      b.dataset.value = v;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => toggleTag(g, b));
      chips.append(b);
    }
    row.append(name, chips);
    return row;
  }));
}

function toggleTag(group, button) {
  const on = button.getAttribute("aria-pressed") !== "true";
  if (on && !group.multiple) {
    $("tag-groups").querySelectorAll(`[data-key="${group.key}"] .tag-chip`).forEach((b) => b.setAttribute("aria-pressed", "false"));
  }
  button.setAttribute("aria-pressed", String(on));
  showTagSentence();
}

function readTags() {
  const out = {};
  for (const g of tagGroups) {
    const values = [...$("tag-groups").querySelectorAll(`[data-key="${g.key}"] .tag-chip[aria-pressed="true"]`)].map((b) => b.dataset.value);
    if (values.length) out[g.key] = values;
  }
  return out;
}

function fillTags(tags) {
  for (const g of tagGroups) {
    $("tag-groups").querySelectorAll(`[data-key="${g.key}"] .tag-chip`).forEach((b) => {
      b.setAttribute("aria-pressed", String((tags[g.key] || []).includes(b.dataset.value)));
    });
  }
  showTagSentence();
}

// 서버의 tags.sentence 와 같은 형식 (취향 매칭에 실제로 들어가는 문장)
function showTagSentence() {
  const tags = readTags();
  const text = tagGroups.filter((g) => tags[g.key]).map((g) => `${g.label}: ${tags[g.key].join(" / ")}`).join(" | ");
  const missing = $("f-kind").value === "candidate"
    ? tagGroups.filter((g) => g.required && !tags[g.key]).map((g) => g.label) : [];
  $("tag-sentence").textContent = text || "태그를 고르세요";
  $("tag-sentence").classList.toggle("muted", !text);
  $("tag-groups").querySelectorAll(".tag-group").forEach((row) => {
    const g = tagGroups.find((x) => x.key === row.dataset.key);
    row.classList.toggle("missing", missing.includes(g.label));
  });
}
$("f-kind").addEventListener("change", showTagSentence);
$("f-closed").replaceChildren(...WEEKDAYS.map((d, i) => {
  const label = el("label");
  const box = el("input");
  box.type = "checkbox";
  box.value = i;
  label.append(box, ` ${d}`);
  return label;
}));

async function loadPlaces() {
  const res = await adminFetch("/api/admin/places");
  if (!res.ok) {
    $("count").textContent = res.status === 401 ? "(관리자 토큰이 필요합니다. 새로고침 후 입력하세요)" : "(불러오기 실패)";
    return;
  }
  places = await res.json();
  drawList();
}

function drawList() {
  const q = $("search").value.trim().toLowerCase();
  const kind = $("filter-kind").value;
  const verified = $("filter-verified").value;
  const shown = places.filter((p) =>
    (!kind || p.kind === kind)
    && (!verified || String(p.verified) === verified)
    && (!q || [p.name, p.id, p.area, ...p.aliases, ...Object.values(p.tags || {}).flat()].some((s) => s.toLowerCase().includes(q))));

  const lacking = places.filter((p) => p.missing_tags.length).length;
  $("count").textContent = `${shown.length} / ${places.length}곳 · 검증 ${places.filter((p) => p.verified).length}곳`
    + (lacking ? ` · 태그 부족 ${lacking}곳` : "");
  $("places").querySelector("tbody").replaceChildren(...shown.map((p) => {
    const tr = el("tr");
    tr.tabIndex = 0;
    tr.dataset.id = p.id;
    if (p.id === selected) tr.classList.add("selected");
    const name = el("td");
    name.append(el("div", "", p.name), el("div", "muted small", `${p.id}${p.kind === "anchor" ? " · 목적지" : ""}`));
    if (p.missing_tags.length) name.firstChild.append(el("span", "badge-warn", "태그 부족"));
    tr.append(
      name,
      el("td", "nowrap", CATEGORY_KO[p.category]),
      el("td", "nowrap col-area", p.area),
      el("td", "nowrap col-hours", `${p.open}–${p.close}`),
      el("td", "num nowrap col-cost", p.cost ? `${p.cost.toLocaleString()}원` : "무료"),
      el("td", "num", Math.round(p.local_contribution * 100)), // 알고리즘이 쓰는 지역상권 기여도(0~1)를 100점 만점으로
      el("td", "num", p.n_ratings ? `${p.n_ratings}명` : "–"),
      el("td", "verified", p.verified ? "✓" : ""),
    );
    tr.addEventListener("click", () => openPlace(p.id));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openPlace(p.id); });
    return tr;
  }));
}

for (const id of ["search", "filter-kind", "filter-verified"]) $(id).addEventListener("input", drawList);

// ---------- 편집 폼 ----------

function fillForm(p) {
  $("f-id").value = p.id;
  $("f-kind").value = p.kind;
  $("f-name").value = p.name;
  $("f-category").value = p.category;
  $("f-area").value = p.area;
  $("f-aliases").value = p.aliases.join(", ");
  $("f-description").value = p.description;
  fillTags(p.tags || {});
  $("f-lat").value = p.lat;
  $("f-lng").value = p.lng;
  $("f-open").value = p.open;
  $("f-close").value = p.close;
  $("f-closed").querySelectorAll("input").forEach((b) => { b.checked = p.closed_days.includes(Number(b.value)); });
  $("f-stay").value = p.stay_min;
  $("f-cost").value = p.cost;
  $("f-gwangju").value = p.gwangju_ness;
  $("f-stayind").value = p.stay_inducement;
  $("f-commerce").value = p.commerce_link;
  $("f-local").checked = p.is_local_commerce;
  $("f-verified").checked = p.verified;

  // 체크리스트가 있으면 점수·지역상권 여부는 체크리스트가 정한다
  const rated = p.n_ratings > 0;
  for (const id of ["f-gwangju", "f-stayind", "f-commerce"]) $(id).readOnly = rated;
  $("f-local").disabled = rated;
  $("scores-note").textContent = rated
    ? `팀원 ${p.n_ratings}명의 체크리스트로 계산한 값입니다. 아래 체크리스트에서 고치세요.`
    : "체크리스트가 아직 없어 직접 입력한 값을 씁니다.";
  $("updated-at").textContent = p.updated_at ? `마지막 수정 ${formatTime(p.updated_at)}` : "";
}

function readForm() {
  return {
    id: $("f-id").value.trim(),
    kind: $("f-kind").value,
    name: $("f-name").value.trim(),
    category: $("f-category").value,
    area: $("f-area").value.trim(),
    aliases: $("f-aliases").value.split(",").map((s) => s.trim()).filter(Boolean),
    description: $("f-description").value.trim(),
    tags: readTags(),
    lat: Number($("f-lat").value),
    lng: Number($("f-lng").value),
    open: $("f-open").value.trim(),
    close: $("f-close").value.trim(),
    closed_days: [...$("f-closed").querySelectorAll("input:checked")].map((b) => Number(b.value)),
    stay_min: Number($("f-stay").value),
    cost: Number($("f-cost").value),
    gwangju_ness: Number($("f-gwangju").value),
    stay_inducement: Number($("f-stayind").value),
    commerce_link: Number($("f-commerce").value),
    is_local_commerce: $("f-local").checked,
    verified: $("f-verified").checked,
  };
}

function showEditor(isNew) {
  $("empty").hidden = true;
  $("place-form").hidden = false;
  $("checklist-section").hidden = isNew;
  $("f-id").readOnly = !isNew;
  $("delete").hidden = isNew;
  $("form-title").textContent = isNew ? "새 장소" : "장소 편집";
  $("form-status").textContent = "";
  $("checklist-status").textContent = "";
  miniMap.invalidateSize(); // 숨겨져 있던 지도는 크기를 다시 재야 한다
}

async function openPlace(id) {
  const p = places.find((x) => x.id === id);
  if (!p) return;
  selected = id;
  history.replaceState(null, "", `?place=${encodeURIComponent(id)}`); // 이 장소를 바로 여는 링크
  showEditor(false);
  fillForm(p);
  setPoint(p.lat, p.lng);
  drawList();
  await loadChecklist();
}

$("new-place").addEventListener("click", () => {
  selected = null;
  history.replaceState(null, "", location.pathname);
  showEditor(true);
  fillForm({
    id: "", kind: "candidate", name: "", category: "sight", area: "", aliases: [], description: "",
    lat: "", lng: "", open: "10:00", close: "22:00", closed_days: [], stay_min: 60, cost: 0,
    gwangju_ness: 3, stay_inducement: 3, commerce_link: 3, is_local_commerce: false, verified: false, n_ratings: 0,
  });
  marker.remove();
  drawList();
  $("f-id").focus();
});

function setStatus(id, text, ok) {
  $(id).textContent = text;
  $(id).classList.toggle("ok", ok);
}

$("place-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = readForm();
  const isNew = selected === null;
  const res = await adminFetch(isNew ? "/api/admin/places" : `/api/admin/places/${selected}`, {
    method: isNew ? "POST" : "PUT",
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    setStatus("form-status", errorText(data, "저장하지 못했습니다."), false);
    return;
  }
  await loadPlaces();
  await openPlace(data.id);
  setStatus("form-status", isNew ? "새 장소를 추가했습니다." : "저장했습니다.", true);
});

$("delete").addEventListener("click", async () => {
  const p = places.find((x) => x.id === selected);
  if (!confirm(`'${p.name}' 을(를) 삭제할까요? 체크리스트와 이동시간 기록도 함께 지워집니다.`)) return;
  const res = await adminFetch(`/api/admin/places/${selected}`, { method: "DELETE" });
  if (!res.ok) {
    setStatus("form-status", "삭제하지 못했습니다.", false);
    return;
  }
  selected = null;
  $("place-form").hidden = true;
  $("checklist-section").hidden = true;
  $("empty").hidden = false;
  marker.remove();
  await loadPlaces();
});

// ---------- 현장조사 체크리스트 (data/checklist.json) ----------

let checklistDef = null;
let checklistView = { sheets: [], evaluation: null };
const NEW_RATER = "__new__";

async function loadChecklistDef() {
  checklistDef = await fetch("/api/checklist").then((r) => r.json());
}

async function loadChecklist(keepRater) {
  const res = await adminFetch(`/api/admin/places/${selected}/checklists`);
  checklistView = res.ok ? await res.json() : { sheets: [], evaluation: null };
  const raters = checklistView.sheets.map((x) => x.rater);
  $("c-rater").replaceChildren(
    ...raters.map((r) => new Option(r, r)),
    new Option("+ 새 채점자", NEW_RATER),
  );
  $("c-rater").value = raters.includes(keepRater) ? keepRater : (raters[0] || NEW_RATER);
  drawChecklist();
}

function currentSheet() {
  return checklistView.sheets.find((x) => x.rater === $("c-rater").value) || { checks: {}, evidence: {} };
}

function drawChecklist() {
  const isNew = $("c-rater").value === NEW_RATER;
  $("c-rater-new").hidden = !isNew;
  $("c-delete").hidden = isNew;
  const sheet = currentSheet();
  const items = Object.fromEntries((checklistView.evaluation?.items || []).map((i) => [i.key, i]));
  const scores = checklistView.evaluation?.scores || {};
  const counted = checklistView.sheets.length > 0;

  $("checklist-groups").replaceChildren(...checklistDef.attributes.map((attr) => {
    const card = el("div", "check-card");
    const head = el("div", "check-head");
    head.append(el("b", "", attr.label), el("span", "muted small", attr.question));
    head.append(el("span", "check-score", counted ? `${scores[attr.key].toFixed(1)} / 5` : "체크리스트 없음"));
    card.append(head);
    for (const item of checklistDef.items.filter((i) => i.attribute === attr.key)) {
      const ev = items[item.key] || { value: 0, votes: {}, disagree: false };
      const row = el("div", `check-row${ev.disagree ? " disagree" : ""}`);
      const box = el("span", "check-box");
      if (item.auto) {
        box.append(el("span", `auto ${ev.value ? "yes" : "no"}`, ev.value ? "✓" : "–"));
      } else {
        const input = el("input");
        input.type = "checkbox";
        input.dataset.key = item.key;
        input.id = `c-${item.key}`;
        input.checked = !!sheet.checks[item.key];
        box.append(input);
      }
      const text = el("label", "check-text");
      if (!item.auto) text.htmlFor = `c-${item.key}`;
      text.append(el("span", "", item.label), el("span", "muted small", item.how));
      const votes = el("span", "check-votes small");
      if (item.auto) votes.append(el("span", "badge-auto", "자동"));
      else {
        for (const [rater, v] of Object.entries(ev.votes)) votes.append(el("span", v ? "vote yes" : "vote no", `${rater} ${v ? "✓" : "✗"}`));
        if (ev.disagree) votes.append(el("span", "badge-warn", "불일치"));
      }
      row.append(box, text, votes);
      if (!item.auto) {
        const evidence = el("input", "check-evidence");
        evidence.dataset.key = item.key;
        evidence.placeholder = "근거 (링크·메모)";
        evidence.maxLength = 300;
        evidence.value = sheet.evidence[item.key] || "";
        row.append(evidence);
      }
      card.append(row);
    }
    return card;
  }));
}

$("c-rater").addEventListener("change", () => { setStatus("checklist-status", "", true); drawChecklist(); });

async function afterChecklistChange(res, message, rater) {
  const data = await res.json();
  if (!res.ok) {
    setStatus("checklist-status", errorText(data, "저장하지 못했습니다."), false);
    return;
  }
  const i = places.findIndex((p) => p.id === data.id);
  places[i] = data;
  fillForm(data);
  drawList();
  await loadChecklist(rater);
  setStatus("checklist-status", message, true);
}

$("checklist-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const rater = $("c-rater").value === NEW_RATER ? $("c-rater-new").value.trim() : $("c-rater").value;
  if (!rater) {
    setStatus("checklist-status", "채점자 이름을 입력하세요.", false);
    $("c-rater-new").focus();
    return;
  }
  const checks = {}, evidence = {};
  $("checklist-groups").querySelectorAll("input[type=checkbox]").forEach((b) => { checks[b.dataset.key] = b.checked; });
  $("checklist-groups").querySelectorAll(".check-evidence").forEach((t) => { if (t.value.trim()) evidence[t.dataset.key] = t.value.trim(); });
  const res = await adminFetch(`/api/admin/places/${selected}/checklists`, {
    method: "PUT", body: JSON.stringify({ rater, checks, evidence }),
  });
  $("c-rater-new").value = "";
  await afterChecklistChange(res, `${rater} 님의 체크리스트를 저장했습니다.`, rater);
});

$("c-delete").addEventListener("click", async () => {
  const rater = $("c-rater").value;
  if (!confirm(`${rater} 님의 체크리스트를 삭제할까요?`)) return;
  const res = await adminFetch(`/api/admin/places/${selected}/checklists/${encodeURIComponent(rater)}`, { method: "DELETE" });
  await afterChecklistChange(res, `${rater} 님의 체크리스트를 삭제했습니다.`, null);
});

// ---------- 내보내기 / 초기화 ----------

$("export").addEventListener("click", async () => {
  const res = await adminFetch("/api/admin/export");
  if (!res.ok) return;
  const data = await res.json();
  // data/places.json · anchors.json · travel_matrix.json · checklists.json 으로 나눠 저장한다
  const files = [["places", data.places], ["anchors", data.anchors], ["travel_matrix", data.travel_matrix], ["checklists", data.checklists]];
  for (const [name, rows] of files) {
    if (!Array.isArray(rows) && !Object.keys(rows).length) continue; // 비어 있는 이동시간·체크리스트는 건너뛴다
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${name}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
});

$("import").addEventListener("click", async () => {
  if (!confirm("장소·이동시간·체크리스트를 data/*.json 기준으로 되돌립니다.\n이 화면에서 고친 내용과 체크리스트가 모두 지워집니다(data/checklists.json 이 있으면 그 내용으로). 계속할까요?")) return;
  const res = await adminFetch("/api/admin/import", { method: "POST" });
  if (!res.ok) return;
  selected = null;
  $("place-form").hidden = true;
  $("checklist-section").hidden = true;
  $("empty").hidden = false;
  await loadPlaces();
});

Promise.all([loadTags(), loadChecklistDef(), loadPlaces()]).then(() => {
  const id = new URLSearchParams(location.search).get("place");
  if (id) openPlace(id);
});

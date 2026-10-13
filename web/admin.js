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
    && (!q || [p.name, p.id, p.area, ...p.aliases].some((s) => s.toLowerCase().includes(q))));

  $("count").textContent = `${shown.length} / ${places.length}곳 · 검증 ${places.filter((p) => p.verified).length}곳`;
  $("places").querySelector("tbody").replaceChildren(...shown.map((p) => {
    const tr = el("tr");
    tr.tabIndex = 0;
    tr.dataset.id = p.id;
    if (p.id === selected) tr.classList.add("selected");
    const name = el("td");
    name.append(el("div", "", p.name), el("div", "muted small", `${p.id}${p.kind === "anchor" ? " · 목적지" : ""}`));
    tr.append(
      name,
      el("td", "nowrap", CATEGORY_KO[p.category]),
      el("td", "nowrap col-area", p.area),
      el("td", "nowrap col-hours", `${p.open}–${p.close}`),
      el("td", "num col-cost", p.cost ? `${p.cost.toLocaleString()}원` : "무료"),
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

  const rated = p.n_ratings > 0;
  for (const id of ["f-gwangju", "f-stayind", "f-commerce"]) $(id).readOnly = rated;
  $("scores-note").textContent = rated
    ? `팀원 ${p.n_ratings}명의 채점 평균입니다. 아래 '팀원별 채점'에서 고치세요.`
    : "아직 채점이 없어 직접 입력한 값을 씁니다.";
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
  $("ratings-section").hidden = isNew;
  $("f-id").readOnly = !isNew;
  $("delete").hidden = isNew;
  $("form-title").textContent = isNew ? "새 장소" : "장소 편집";
  $("form-status").textContent = "";
  $("rating-status").textContent = "";
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
  await loadRatings();
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
  await loadPlaces().then(() => {
  const id = new URLSearchParams(location.search).get("place");
  if (id) openPlace(id);
});
  await openPlace(data.id);
  setStatus("form-status", isNew ? "새 장소를 추가했습니다." : "저장했습니다.", true);
});

$("delete").addEventListener("click", async () => {
  const p = places.find((x) => x.id === selected);
  if (!confirm(`'${p.name}' 을(를) 삭제할까요? 채점과 이동시간 기록도 함께 지워집니다.`)) return;
  const res = await adminFetch(`/api/admin/places/${selected}`, { method: "DELETE" });
  if (!res.ok) {
    setStatus("form-status", "삭제하지 못했습니다.", false);
    return;
  }
  selected = null;
  $("place-form").hidden = true;
  $("ratings-section").hidden = true;
  $("empty").hidden = false;
  marker.remove();
  await loadPlaces().then(() => {
  const id = new URLSearchParams(location.search).get("place");
  if (id) openPlace(id);
});
});

// ---------- 채점 ----------

async function loadRatings() {
  const res = await adminFetch(`/api/admin/places/${selected}/ratings`);
  const rows = res.ok ? await res.json() : [];
  const tbody = $("ratings").querySelector("tbody");
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", "muted small", "아직 채점이 없습니다.");
    td.colSpan = 5;
    tr.append(td);
    tbody.replaceChildren(tr);
    return;
  }
  tbody.replaceChildren(...rows.map((r) => {
    const tr = el("tr");
    const del = el("button", "inline secondary", "삭제");
    del.type = "button";
    del.addEventListener("click", () => deleteRating(r.rater));
    const cell = el("td", "num");
    cell.append(del);
    tr.append(
      el("td", "", r.rater),
      el("td", "num", r.gwangju_ness),
      el("td", "num", r.stay_inducement),
      el("td", "num", r.commerce_link),
      cell,
    );
    return tr;
  }));
}

async function afterRatingChange(res, message) {
  const data = await res.json();
  if (!res.ok) {
    setStatus("rating-status", errorText(data, "저장하지 못했습니다."), false);
    return false;
  }
  const i = places.findIndex((p) => p.id === data.id);
  places[i] = data;
  fillForm(data);
  drawList();
  await loadRatings();
  setStatus("rating-status", message, true);
  return true;
}

$("rating-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    rater: $("r-rater").value.trim(),
    gwangju_ness: Number($("r-gwangju").value),
    stay_inducement: Number($("r-stayind").value),
    commerce_link: Number($("r-commerce").value),
  };
  const res = await adminFetch(`/api/admin/places/${selected}/ratings`, { method: "PUT", body: JSON.stringify(body) });
  if (await afterRatingChange(res, `${body.rater} 님의 채점을 저장했습니다.`)) $("rating-form").reset();
});

async function deleteRating(rater) {
  if (!confirm(`${rater} 님의 채점을 삭제할까요?`)) return;
  const res = await adminFetch(`/api/admin/places/${selected}/ratings/${encodeURIComponent(rater)}`, { method: "DELETE" });
  await afterRatingChange(res, `${rater} 님의 채점을 삭제했습니다.`);
}

// ---------- 내보내기 / 초기화 ----------

$("export").addEventListener("click", async () => {
  const res = await adminFetch("/api/admin/export");
  if (!res.ok) return;
  const data = await res.json();
  // data/places.json · anchors.json · travel_matrix.json 으로 나눠 저장한다
  for (const [name, rows] of [["places", data.places], ["anchors", data.anchors], ["travel_matrix", data.travel_matrix]]) {
    if (name === "travel_matrix" && !Object.keys(rows).length) continue;
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${name}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
});

$("import").addEventListener("click", async () => {
  if (!confirm("장소·이동시간을 data/*.json 예시 데이터로 되돌립니다.\n이 화면에서 고친 내용과 팀원별 채점이 모두 지워집니다. 계속할까요?")) return;
  const res = await adminFetch("/api/admin/import", { method: "POST" });
  if (!res.ok) return;
  selected = null;
  $("place-form").hidden = true;
  $("ratings-section").hidden = true;
  $("empty").hidden = false;
  await loadPlaces().then(() => {
  const id = new URLSearchParams(location.search).get("place");
  if (id) openPlace(id);
});
});

loadPlaces().then(() => {
  const id = new URLSearchParams(location.search).get("place");
  if (id) openPlace(id);
});

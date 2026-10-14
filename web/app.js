// 지도: 카카오맵 또는 OpenStreetMap (map.js). 만들어지는 데 시간이 걸리므로 그리기 전에 기다린다.
const routeButton = el("button", "route-control", "전체 경로 보기"); // 지도 오른쪽 위. 코스를 그리면 보인다(drawMap)
routeButton.type = "button";
routeButton.id = "show-route";
routeButton.hidden = true;
let mapView = null;
const mapReady = createMapView($("map")).then((view) => {
  mapView = view;
  view.addControl(routeButton);
  return view;
});

// 필수 방문지는 여러 곳을 넣을 수 있다. 한 줄 = 장소 + 시작 시각 + 머무는 시간.
const MAX_MUSTS = 5;
const mustInfo = {};
let mustGroups = []; // [[optgroup 이름, 장소 목록], ...]
let mustSeq = 0; // 줄마다 label 과 입력칸을 잇는 고유 id

async function loadMustOptions() {
  const [anchors, places] = await Promise.all(
    ["/api/anchors", "/api/places"].map((url) => fetch(url).then((r) => r.json())),
  );
  mustGroups = [["목적지", anchors], ["원도심 장소", places]];
  for (const p of [...anchors, ...places]) mustInfo[p.id] = p;
  setMustRows([{ id: "champions_field", start: "18:30" }]);
}

// 시각 고르기. 브라우저 기본 시각 입력은 오전/오후 칸을 따로 바꿔야 해서 헷갈리므로,
// '오후 6:30' 을 보여 주는 칸을 누르면 오전/오후 · 시 · 분을 눌러 고르는 작은 판이 열린다.
// <input type=time> 처럼 box.value('HH:MM', 시를 안 고르면 "")와 box.disabled 를 쓸 수 있고, 고르면 change 가 난다.
function timePicker(box, name) {
  const pad = (n) => String(n).padStart(2, "0");
  let h = null; // 0~23, 안 고르면 null
  let m = "00";
  let pm = true; // 시를 고르기 전 오전/오후 선택. 일정은 대개 오후다
  let disabled = false;

  const field = el("button", "time-field");
  field.type = "button";
  field.id = `${box.id}-field`;
  field.setAttribute("aria-haspopup", "dialog");
  field.setAttribute("aria-expanded", "false");

  const clear = el("button", "time-clear", "×");
  clear.type = "button";
  clear.setAttribute("aria-label", `${name} 지우기`);
  clear.title = "지우기";

  const pop = el("div", "time-pop");
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", name);
  pop.hidden = true;

  const choice = (text, cls, onPick) => {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", onPick);
    return b;
  };
  const changed = () => {
    paint();
    box.dispatchEvent(new Event("change", { bubbles: true }));
  };

  const ampm = el("div", "time-seg");
  const amBtn = choice("오전", "", () => { pm = false; if (h !== null) h %= 12; changed(); });
  const pmBtn = choice("오후", "", () => { pm = true; if (h !== null) h = (h % 12) + 12; changed(); });
  ampm.append(amBtn, pmBtn);

  const hours = el("div", "time-grid hours");
  const hourBtns = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((n) =>
    choice(String(n), "", () => { h = (n % 12) + (pm ? 12 : 0); changed(); }));
  hours.append(...hourBtns);

  const minutes = el("div", "time-grid minutes");
  const minuteBtns = ["00", "10", "20", "30", "40", "50"].map((v) =>
    choice(v, "", () => { m = v; changed(); close(true); }));
  minutes.append(...minuteBtns);

  const foot = el("div", "time-foot");
  foot.append(
    choice("지우기", "link", () => { h = null; m = "00"; changed(); close(true); }),
    choice("확인", "inline", () => close(true)),
  );
  pop.append(ampm, el("div", "time-sub", "시"), hours, el("div", "time-sub", "분"), minutes, foot);
  box.append(field, clear, pop);

  function paint() {
    if (h !== null) pm = h >= 12;
    field.textContent = h === null ? "선택 안 함" : `${pm ? "오후" : "오전"} ${h % 12 || 12}:${m}`;
    field.classList.toggle("empty", h === null);
    field.disabled = disabled;
    clear.hidden = disabled || h === null;
    amBtn.setAttribute("aria-pressed", String(!pm));
    pmBtn.setAttribute("aria-pressed", String(pm));
    hourBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(h !== null && h % 12 === i)));
    minuteBtns.forEach((b) => {
      b.setAttribute("aria-pressed", String(h !== null && b.textContent === m));
      b.disabled = h === null; // 시를 고르기 전에는 분이 의미 없다
    });
  }

  function open() {
    pop.hidden = false;
    field.setAttribute("aria-expanded", "true");
    // 화면 오른쪽 끝을 넘으면 칸의 오른쪽에 맞춰 연다
    pop.classList.remove("right");
    if (pop.getBoundingClientRect().right > document.documentElement.clientWidth - 8) pop.classList.add("right");
    (pop.querySelector("[aria-pressed=true]:not(:disabled)") || pmBtn).focus();
  }
  function close(focusField) {
    if (pop.hidden) return;
    pop.hidden = true;
    field.setAttribute("aria-expanded", "false");
    if (focusField) field.focus();
  }
  field.addEventListener("click", () => (pop.hidden ? open() : close()));
  clear.addEventListener("click", () => {
    h = null;
    m = "00";
    changed();
    close();
    field.focus();
  });
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") close(true); });
  document.addEventListener("click", (e) => { if (!box.contains(e.target)) close(); });
  box.addEventListener("focusout", (e) => { if (e.relatedTarget && !box.contains(e.relatedTarget)) close(); });

  Object.defineProperties(box, {
    value: {
      get: () => (h === null ? "" : `${pad(h)}:${m}`),
      set: (v) => {
        const [hh, mm = "00"] = (v || "").split(":");
        h = hh ? Number(hh) % 24 : null;
        m = mm; // 10분 단위가 아닌 값(예전 공유 링크 등)도 칸에는 그대로 보여 준다
        paint();
      },
    },
    disabled: { get: () => disabled, set: (v) => { disabled = !!v; if (disabled) close(); paint(); } },
  });
  paint();
  return box;
}
for (const box of document.querySelectorAll(".time-pick[data-label]")) timePicker(box, box.dataset.label);

function mustRows() {
  return [...$("must-list").querySelectorAll(".must-item")];
}

function addMustRow({ id = "", start = "", stay_min = "" } = {}) {
  const n = ++mustSeq;
  const row = el("div", "must-item");

  const head = el("div", "must-head");
  const label = el("label", "", "장소");
  label.htmlFor = `must-${n}`;
  const remove = el("button", "remove-must", "삭제");
  remove.type = "button";
  remove.setAttribute("aria-label", "이 필수 방문지 삭제");
  remove.addEventListener("click", () => {
    row.remove();
    syncMustRows();
  });
  head.append(label, remove);

  const select = el("select", "must-place");
  select.id = `must-${n}`;
  select.append(new Option("", "")); // 문구는 syncMustRows 가 줄 순서에 맞춰 넣는다
  for (const [name, list] of mustGroups) {
    const group = el("optgroup");
    group.label = name;
    for (const p of list) group.append(new Option(p.name, p.id));
    select.append(group);
  }
  select.value = mustInfo[id] ? id : "";

  const detail = el("div", "row must-detail");
  const startBox = el("div");
  const startLabel = el("label", "", "방문 예정 시각 ");
  startLabel.append(el("span", "muted small", "(선택)"));
  const startInput = el("span", "time-pick must-start");
  startInput.id = `must-${n}-start`;
  startLabel.htmlFor = `${startInput.id}-field`;
  timePicker(startInput, "방문 예정 시각");
  startInput.value = start || "";
  startBox.append(startLabel, startInput);

  const stayBox = el("div");
  const stayLabel = el("label", "", "머무는 시간");
  const stayInput = el("input", "must-stay");
  stayInput.type = "number";
  stayInput.min = "10";
  stayInput.step = "10";
  stayInput.id = stayLabel.htmlFor = `must-${n}-stay`;
  stayInput.value = stay_min || "";
  const unit = el("div", "with-unit");
  unit.append(stayInput, el("span", "", "분"));
  stayBox.append(stayLabel, unit);
  detail.append(startBox, stayBox);

  const error = el("p", "must-error");
  error.id = `must-${n}-error`;
  error.setAttribute("role", "alert");
  error.hidden = true;
  startInput.querySelector(".time-field").setAttribute("aria-describedby", error.id);
  startInput.addEventListener("change", syncMustRows);
  stayInput.addEventListener("input", syncMustRows);

  select.addEventListener("change", () => {
    // 시작 시각 고정은 경기·공연장에만 기본으로 의미가 있다. 다른 장소로 바꾸면 비워 둔다.
    const p = mustInfo[select.value];
    if (p && p.category !== "venue") startInput.value = "";
    syncMustRows();
  });

  row.append(head, select, detail, error);
  $("must-list").append(row);
  syncMustRows();
  return row;
}

function setMustRows(list) {
  $("must-list").replaceChildren();
  mustSeq = 0;
  for (const m of list.length ? list : [{}]) addMustRow(m);
}

// 장소를 고르지 않은 줄은 시작 시각·머무는 시간을 쓸 데가 없으므로 잠근다.
// 다른 줄에서 이미 고른 장소는 고를 수 없게 하고, 한 줄만 남으면 빼기 버튼을 숨긴다.
function syncMustRows() {
  const rows = mustRows();
  const chosen = rows.map((r) => r.querySelector(".must-place").value);
  rows.forEach((row, i) => {
    const id = chosen[i];
    row.querySelector(".must-head label").textContent = rows.length > 1 ? `장소 ${i + 1}` : "장소";
    row.querySelector(".remove-must").hidden = rows.length === 1;
    const select = row.querySelector(".must-place");
    select.options[0].text = i === 0 ? "없음 (문장에서 찾기)" : "장소를 고르세요";
    for (const opt of select.options) {
      opt.disabled = !!opt.value && opt.value !== id && chosen.includes(opt.value);
    }
    const stay = row.querySelector(".must-stay");
    for (const input of [row.querySelector(".must-start"), stay]) input.disabled = !id;
    row.querySelector(".must-detail").classList.toggle("off", !id);
    stay.placeholder = id ? `기본 ${mustInfo[id].stay_min}` : ""; // 장소마다 기본 체류시간이 다르다
  });
  showMustConflicts(rows);
  const any = chosen.some(Boolean);
  $("must-help-off").hidden = any;
  $("add-must").hidden = rows.length >= MAX_MUSTS;
}

const minutes = (hm) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };
const hhmm = (t) => `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;

const CONFLICT_STATUS = "필수 방문지 시간이 겹칩니다.";

// 시작 시각을 정한 필수 방문지끼리 (시작 ~ 시작 + 머무는 시간) 이 겹치면 뒤쪽 줄에 알린다.
// 장소 사이 이동시간은 서버가 따져서 한 번 더 막는다.
function showMustConflicts(rows) {
  const fixed = rows.map((row) => {
    const id = row.querySelector(".must-place").value;
    const start = row.querySelector(".must-start").value;
    if (!id || !start) return null;
    const stay = Number(row.querySelector(".must-stay").value) || mustInfo[id].stay_min;
    return { row, name: mustInfo[id].name, start: minutes(start), end: minutes(start) + stay };
  }).filter(Boolean).sort((a, b) => a.start - b.start);

  const messages = new Map();
  const bad = new Set();
  fixed.forEach((b, i) => {
    const a = fixed.slice(0, i).find((x) => x.end > b.start); // 앞서 시작해서 아직 안 끝난 곳
    if (!a) return;
    bad.add(a.row).add(b.row);
    messages.set(b.row, `‘${a.name}’(${hhmm(a.start)}–${hhmm(a.end)}) 일정과 겹칩니다.`);
  });
  for (const row of rows) {
    const error = row.querySelector(".must-error");
    error.textContent = messages.get(row) || "";
    error.hidden = !messages.has(row);
    for (const input of row.querySelectorAll(".must-start .time-field, .must-stay")) {
      input.toggleAttribute("aria-invalid", bad.has(row));
    }
  }
  if (!messages.size && $("status").textContent === CONFLICT_STATUS) $("status").textContent = "";
  return messages.size;
}

$("add-must").addEventListener("click", () => {
  addMustRow().querySelector(".must-place").focus();
});

$("clear-optional").addEventListener("click", () => {
  for (const id of ["visit-date", "day-start", "day-end", "budget"]) $(id).value = "";
  showWeekday();
});

// 날짜 옆에 요일을 보여 준다. 'YYYY-MM-DD' 를 그대로 Date 로 읽으면 UTC 로 해석되므로 나눠서 만든다.
function showWeekday() {
  const v = $("visit-date").value;
  if (!v) { $("visit-weekday").textContent = ""; return; }
  const [y, m, d] = v.split("-").map(Number);
  $("visit-weekday").textContent = `${"일월화수목금토"[new Date(y, m - 1, d).getDay()]}요일`;
}
$("visit-date").addEventListener("input", showWeekday);

// 코스 짜는 방식 설명. 고른 방식에 맞춰 한 줄로 보여 준다.
const PLANNER_HELP = {
  greedy: "취향·동선에 맞는 곳부터 하나씩 채웁니다. 예상 시간: 약 10초",
  ortools: "여러 조합을 한꺼번에 비교해 더 나은 코스를 찾습니다. 예상 시간: 약 12초",
};
function showPlannerHelp() {
  $("planner-help").textContent = PLANNER_HELP[$("planner").value];
}
$("planner").addEventListener("change", showPlannerHelp);
showPlannerHelp();

// 서버가 실제로 쓴 조건과 그 출처. 화면 값이 문장을 덮어썼으면 notes 로 알려 준다.
const WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"];

function drawConditions(course) {
  const c = course.constraints;
  // 출처 표시: 직접 입력한 값은 따로 표시하지 않고, 문장에서 읽은 값은 '텍스트'로 보여 준다.
  const sourceLabel = (s) => (s === "화면" ? null : s === "문장" ? "텍스트" : s || null);
  const src = Object.fromEntries(Object.entries(c.sources || {}).map(([k, v]) => [k, sourceLabel(v)]));
  const chips = [];
  const add = (label, value, source) => chips.push([label, value, source]);

  if (c.must_visits && c.must_visits.length) add("필수 방문지", c.must_visits.join(", "), src.must_visits);
  const timeSource = src.day_start === src.day_end ? src.day_start : [src.day_start && `시작 ${src.day_start}`, src.day_end && `종료 ${src.day_end}`].filter(Boolean).join(", ");
  add("시간", `${c.day_start}–${c.day_end}`, timeSource);
  add("예산", c.budget == null ? "제한 없음" : `${c.budget.toLocaleString()}원`, c.budget == null ? null : src.budget);
  if (c.weekday != null) {
    const day = c.visit_date ? `${Number(c.visit_date.slice(5, 7))}/${Number(c.visit_date.slice(8))} ` : "";
    add("방문일", `${day}${WEEKDAY_KO[c.weekday]}요일`, src.weekday === undefined ? "텍스트" : src.weekday);
  } else {
    add("방문일", "모름 (휴무일 미확인)", null);
  }
  if (c.companions) add("동행", c.companions, "텍스트");
  if (c.avoid_categories && c.avoid_categories.length) add("제외", c.avoid_categories.map((k) => CATEGORY_KO[k] || k).join(", "), "텍스트");

  $("condition-chips").replaceChildren(...chips.map(([label, value, source]) => {
    const li = el("li");
    li.append(el("span", "chip-label", label), el("b", "", value));
    if (source) li.append(el("span", "chip-source", source));
    return li;
  }));
  $("condition-taste").textContent = c.taste ? `취향: “${c.taste}”` : "";
  $("condition-notes").replaceChildren(...(c.notes || []).map((n) => el("li", "", n)));
  $("conditions").hidden = false;
}

// 장소를 다른 지도 서비스에서 우리 좌표 그대로 연다. 카카오는 좌표에 이름을 붙인 핀을 찍는 공식 링크가 있다.
// (네이버 웹은 좌표에 핀을 찍는 링크 형식이 없어 뺐다)
const MAP_SITES = [
  ["카카오맵", (s) => `https://map.kakao.com/link/map/${encodeURIComponent(s.name.replace(/,/g, " "))},${s.lat},${s.lng}`],
];
function mapLinks(s) {
  const box = el("span", "map-links");
  MAP_SITES.forEach(([label, url], i) => {
    if (i) box.append(el("span", "", "·"));
    const a = el("a", "", label);
    a.href = url(s);
    a.target = "_blank";
    a.rel = "noopener";
    a.title = `${label}에서 ${s.name} 열기`;
    box.append(a);
  });
  return box;
}

function drawTimeline(course) {
  $("summary").textContent = course.summary;
  $("summary").classList.remove("muted");

  const m = course.metrics;
  const items = [
    ["방문 장소", `${m.n_places}곳`],
    ["체류시간", `${Math.floor(m.stay_min / 60)}시간 ${m.stay_min % 60}분`],
    ["이동", `${m.travel_min}분`],
    ["1인 지출", m.total_cost ? `약 ${m.total_cost.toLocaleString()}원` : "무료"],
    ["지역상권", `${m.local_commerce_count}곳 (${Math.round(m.local_commerce_ratio * 100)}%)`],
  ];
  $("metrics").replaceChildren(...items.map(([k, v]) => {
    const li = el("li", "", `${k} `);
    li.append(el("b", "", v));
    return li;
  }));

  $("timeline").replaceChildren(...course.stops.map((s) => {
    const li = el("li", s.kind);
    li.dataset.order = s.order;
    const dot = el("button", "dot", s.order);
    dot.type = "button";
    dot.setAttribute("aria-label", `${s.order}번 ${s.name} 지도에서 보기`);
    dot.addEventListener("click", () => focusStop(s.order));
    li.append(dot);
    if (s.travel_min) li.append(el("div", "move", `이동 ${s.travel_min}분`));
    const time = el("div", "time", `${s.start} – ${s.end}`);
    time.append(el("span", "cost", s.cost ? `1인 약 ${s.cost.toLocaleString()}원` : "무료"));
    li.append(time);
    const name = el("div", "name");
    const link = el("button", "stop-link", s.name);
    link.type = "button";
    link.title = "지도에서 보기";
    link.addEventListener("click", () => focusStop(s.order));
    name.append(link, " ");
    if (s.kind === "must") name.append(el("span", "tag must", "필수"));
    if (s.is_local_commerce) name.append(" ", el("span", "tag local", "지역상권"));
    name.append(mapLinks(s));
    li.append(name);
    li.append(el("div", "muted small", `${CATEGORY_KO[s.category]} · ${s.area}`));
    if (s.kind === "ai" && s.reason) li.append(el("p", "reason", s.reason));
    return li;
  }));

  const e = course.engine;
  $("engine-box").hidden = false;
  $("engine").textContent =
    `파싱 ${e.parser} · 임베딩 ${e.embedder} · 최적화 ${PLANNER_KO[e.planner] || e.planner} · 설명 ${e.explainer} · 점수 ${m.score}`;
}

// 코스와 지도를 잇는다. 코스의 번호·이름을 누르면 지도에서 그 장소를 가운데로 옮기고,
// 지도의 핀을 누르면 코스에서 그 장소로 스크롤한다. 고른 장소는 양쪽에 함께 표시한다.
const markers = {}; // 방문 순서 -> 지도 핀 (map.js addPin)

function markActive(order) {
  for (const [k, m] of Object.entries(markers)) m.setFront(Number(k) === order);
  for (const li of $("timeline").children) li.classList.toggle("active", Number(li.dataset.order) === order);
}

// 핀을 잠깐 커졌다 돌아오게 해서 어디인지 알려 준다.
function flashPin(order) {
  const pin = markers[order]?.pinEl;
  if (!pin) return;
  pin.classList.remove("flash");
  void pin.offsetWidth; // 같은 핀을 연달아 눌러도 처음부터 다시 움직이게
  pin.classList.add("flash");
}

const offScreen = (node) => {
  const box = node.getBoundingClientRect();
  return box.top < 0 || box.bottom > window.innerHeight;
};

function focusStop(order) {
  const marker = markers[order];
  if (!marker) return;
  markActive(order);
  for (const m of Object.values(markers)) m.hideTooltip();
  const s = stopsByOrder[order];
  mapView.focus(s.lat, s.lng, () => flashPin(order)); // 지도가 다 움직인 뒤에 강조해야 보인다
  marker.showTooltip();
  // 좁은 화면에서는 지도가 코스 아래에 있으므로 지도가 보이게 내려 준다
  if (offScreen($("map"))) $("map").scrollIntoView({ behavior: "smooth", block: "center" });
}

function focusTimeline(order) {
  markActive(order);
  const li = $("timeline").querySelector(`li[data-order="${order}"]`);
  if (li && offScreen(li)) li.scrollIntoView({ behavior: "smooth", block: "center" });
}

let routePoints = [];
let stopsByOrder = {};

// 코스 전체가 지도에 들어오게 한다. 장소를 골라 둔 표시는 지운다.
function showWholeRoute() {
  if (!routePoints.length) return;
  markActive(null);
  for (const m of Object.values(markers)) m.hideTooltip();
  mapView.fitAll(routePoints, true);
  if (offScreen($("map"))) $("map").scrollIntoView({ behavior: "smooth", block: "center" });
}
routeButton.addEventListener("click", showWholeRoute);
$("course-on-map").addEventListener("click", showWholeRoute); // 코스 제목 옆. 좁은 화면에서는 지도로 내려 준다

async function drawMap(course) {
  const view = await mapReady;
  view.clear();
  for (const k of Object.keys(markers)) delete markers[k];
  const points = (routePoints = course.stops.map((s) => [s.lat, s.lng]));
  stopsByOrder = Object.fromEntries(course.stops.map((s) => [s.order, s]));
  routeButton.hidden = $("course-on-map").hidden = !points.length;
  // 지도 위에서 잘 보이도록 흰 테두리 위에 파란 점선을 긋는다. 점선은 실제 도로가 아니라 방문 순서를 잇는 선이라는 뜻이다.
  view.drawRoute(points);
  for (const s of course.stops) {
    markers[s.order] = view.addPin(s, {
      label: s.order,
      title: `${s.order}번 ${s.name} 코스에서 보기`,
      tooltip: `${s.start} ${s.name}`,
      onClick: () => focusTimeline(s.order),
    });
  }
  view.fitAll(points, false);
}

let currentCourseId = null;
let currentRating = 0;

function paintStars() {
  $("rating").querySelectorAll("button").forEach((b, i) => {
    b.classList.toggle("on", i < currentRating);
    b.setAttribute("aria-checked", String(i + 1 === currentRating));
  });
}

function showShare(course) {
  currentCourseId = course.id;
  currentRating = 0;
  $("share").hidden = !course.id; // 저장에 실패한 코스는 공유할 수 없다
  $("share-status").textContent = "";
  $("comment").value = "";
  $("feedback-form").hidden = false;
  $("feedback-form").querySelector("button[type=submit]").disabled = true;
  $("rating").replaceChildren(...[1, 2, 3, 4, 5].map((n) => {
    const b = el("button", "star", "★");
    b.type = "button";
    b.title = `${n}점`;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-label", `${n}점`);
    b.addEventListener("click", () => {
      currentRating = n;
      paintStars();
      $("feedback-form").querySelector("button[type=submit]").disabled = false;
    });
    return b;
  }));
  paintStars();
}

function showCourse(course) {
  drawConditions(course);
  drawTimeline(course);
  drawMap(course);
  showShare(course);
}

$("feedback-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const res = await fetch(`/api/courses/${currentCourseId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating: currentRating, comment: $("comment").value.trim() }),
  });
  if (res.ok) {
    $("feedback-form").hidden = true; // 한 코스에 한 번만
    $("share-status").textContent = `${currentRating}점 평가를 보냈습니다. 고맙습니다!`;
  } else {
    $("share-status").textContent = "평가를 저장하지 못했습니다.";
  }
});

$("copy-link").addEventListener("click", async () => {
  const url = `${location.origin}${location.pathname}?course=${currentCourseId}`;
  try {
    await navigator.clipboard.writeText(url);
    $("share-status").textContent = "링크를 복사했습니다.";
  } catch {
    $("share-status").textContent = url;
  }
});

// 공유 링크(?course=<id>)로 들어오면 저장된 코스를 보여 준다.
async function loadSharedCourse() {
  const id = new URLSearchParams(location.search).get("course");
  if (!id) return;
  const res = await fetch(`/api/courses/${encodeURIComponent(id)}`);
  if (!res.ok) {
    $("status").textContent = "공유된 코스를 찾을 수 없습니다.";
    return;
  }
  const course = await res.json();
  if (course.request) fillForm(course.request);
  showCourse(course);
}

// 저장된 요청으로 입력칸을 되살린다. 받은 사람이 조건을 조금 바꿔 다시 만들어 볼 수 있다.
function fillForm(req) {
  $("query").value = req.query;
  setMustRows(req.must_visits.filter((m) => m.id && mustInfo[m.id]));
  $("day-start").value = req.day_start || "";
  $("day-end").value = req.day_end || "";
  $("budget").value = req.budget ?? "";
  $("visit-date").value = req.visit_date || "";
  showWeekday();
  $("planner").value = req.planner || "greedy";
  showPlannerHelp();
}

$("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type=submit]");
  if (showMustConflicts(mustRows())) {
    $("status").textContent = CONFLICT_STATUS;
    $("must-list").querySelector("[aria-invalid]").focus();
    return;
  }
  const body = {
    query: $("query").value,
    must_visits: [],
    day_start: $("day-start").value || null,
    day_end: $("day-end").value || null,
    budget: $("budget").value === "" ? null : Number($("budget").value),
    visit_date: $("visit-date").value || null,
    planner: $("planner").value,
  };
  for (const row of mustRows()) {
    const id = row.querySelector(".must-place").value;
    if (!id) continue; // 장소를 고르지 않은 줄은 건너뛴다
    body.must_visits.push({
      id,
      start: row.querySelector(".must-start").value || null,
      stay_min: Number(row.querySelector(".must-stay").value) || null,
    });
  }

  button.disabled = true;
  $("status").textContent = "코스를 조합하는 중…";
  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.");
    showCourse(data);
    history.replaceState(null, "", data.id ? `?course=${data.id}` : location.pathname);
    $("status").textContent = "";
    $("course").scrollIntoView({ behavior: "smooth", block: "start" }); // 만든 코스로 화면을 옮긴다
  } catch (err) {
    $("status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

// 필수 방문지 목록이 채워진 뒤에 공유 코스의 입력값을 넣어야 선택이 맞는다.
loadMustOptions().then(loadSharedCourse);

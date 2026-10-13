const $ = (id) => document.getElementById(id);

const CATEGORY_KO = {
  sight: "명소·산책", culture: "문화·전시", market: "전통시장", food: "식당",
  cafe: "카페·디저트", shop: "상점가", night: "야간 콘텐츠", venue: "행사장",
};

// 지도: 기본은 OSM 타일. 카카오/네이버 지도로 바꿀 때는 이 블록과 drawMap 만 교체하면 된다.
const map = L.map("map").setView([35.1487, 126.9165], 14);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
const layer = L.layerGroup().addTo(map);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function loadMustOptions() {
  const [anchors, places] = await Promise.all(
    ["/api/anchors", "/api/places"].map((url) => fetch(url).then((r) => r.json())),
  );
  const select = $("must");
  select.append(new Option("없음 (문장에서 찾기)", ""));
  for (const [label, list] of [["목적지", anchors], ["원도심 장소", places]]) {
    const group = el("optgroup");
    group.label = label;
    for (const p of list) group.append(new Option(p.name, p.id));
    select.append(group);
  }
  select.value = "champions_field";
}

function drawTimeline(course) {
  $("summary").textContent = course.summary;
  $("summary").classList.remove("muted");

  const m = course.metrics;
  const items = [
    ["방문 장소", `${m.n_places}곳`],
    ["체류시간", `${Math.floor(m.stay_min / 60)}시간 ${m.stay_min % 60}분`],
    ["이동", `${m.travel_min}분`],
    ["예상 지출", `${m.total_cost.toLocaleString()}원`],
    ["지역상권", `${m.local_commerce_count}곳 (${Math.round(m.local_commerce_ratio * 100)}%)`],
  ];
  $("metrics").replaceChildren(...items.map(([k, v]) => {
    const li = el("li", "", `${k} `);
    li.append(el("b", "", v));
    return li;
  }));

  $("timeline").replaceChildren(...course.stops.map((s) => {
    const li = el("li", s.kind);
    li.append(el("span", "dot", s.order));
    if (s.travel_min) li.append(el("div", "move", `이동 ${s.travel_min}분`));
    li.append(el("div", "time", `${s.start} – ${s.end}`));
    const name = el("div", "name", `${s.name} `);
    name.append(el("span", `tag ${s.kind}`, s.kind === "must" ? "필수" : "AI 추천"));
    if (s.is_local_commerce) name.append(" ", el("span", "tag local", "지역상권"));
    li.append(name);
    li.append(el("div", "muted small", `${CATEGORY_KO[s.category]} · ${s.area}`));
    if (s.kind === "ai" && s.reason) li.append(el("p", "reason", s.reason));
    return li;
  }));

  const e = course.engine;
  $("engine").textContent =
    `파싱 ${e.parser} · 임베딩 ${e.embedder} · 최적화 ${e.planner} · 설명 ${e.explainer} · 점수 ${m.score}`;
}

function drawMap(course) {
  layer.clearLayers();
  const points = course.stops.map((s) => [s.lat, s.lng]);
  L.polyline(points, { color: "#1f2328", weight: 3, opacity: 0.6, dashArray: "6 6" }).addTo(layer);
  for (const s of course.stops) {
    const icon = L.divIcon({ className: "", html: `<div class="pin ${s.kind}">${s.order}</div>`, iconSize: [26, 26] });
    L.marker([s.lat, s.lng], { icon }).bindTooltip(`${s.start} ${s.name}`).addTo(layer);
  }
  if (points.length) map.fitBounds(points, { padding: [40, 40], maxZoom: 16 });
}

let currentCourseId = null;

function showShare(course) {
  currentCourseId = course.id;
  $("share").hidden = !course.id; // 저장에 실패한 코스는 공유할 수 없다
  $("share-status").textContent = "";
  $("rating").replaceChildren(...[1, 2, 3, 4, 5].map((n) => {
    const b = el("button", "star", "★");
    b.type = "button";
    b.title = `${n}점`;
    b.addEventListener("click", () => sendRating(n));
    return b;
  }));
}

function showCourse(course) {
  drawTimeline(course);
  drawMap(course);
  showShare(course);
}

async function sendRating(rating) {
  const res = await fetch(`/api/courses/${currentCourseId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  $("share-status").textContent = res.ok ? `${rating}점 평가를 저장했습니다.` : "평가를 저장하지 못했습니다.";
  if (res.ok) $("rating").querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i < rating));
}

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
  if (res.ok) showCourse(await res.json());
  else $("status").textContent = "공유된 코스를 찾을 수 없습니다.";
}

$("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  const body = {
    query: $("query").value,
    must_visits: [],
    day_start: $("day-start").value || null,
    day_end: $("day-end").value || null,
    planner: $("planner").value,
  };
  if ($("must").value) {
    body.must_visits.push({
      id: $("must").value,
      start: $("must-start").value || null,
      stay_min: Number($("must-stay").value) || null,
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
  } catch (err) {
    $("status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

loadMustOptions();
loadSharedCourse();

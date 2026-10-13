const ROWS = [
  ["courses", "코스 수", (v) => `${v}개`],
  ["avg_places", "평균 장소 수", (v) => `${v.toFixed(1)}곳`],
  ["avg_ai_places", "평균 AI 추천 수", (v) => `${v.toFixed(1)}곳`],
  ["avg_travel_min", "평균 이동시간", (v) => `${Math.round(v)}분`],
  ["avg_local_commerce_ratio", "지역상권 비율", (v) => `${Math.round(v * 100)}%`],
  ["avg_score", "평균 코스 점수", (v) => v.toFixed(2)],
];

function drawTiles(s) {
  const ai = Object.values(s.by_planner);
  const total = ai.reduce((n, p) => n + p.courses, 0);
  const localRatio = total ? ai.reduce((n, p) => n + p.avg_local_commerce_ratio * p.courses, 0) / total : null;
  const tiles = [
    ["생성된 코스", `${s.courses}`, "개"],
    ["평균 지역상권 비율", localRatio === null ? "–" : `${Math.round(localRatio * 100)}`, localRatio === null ? "" : "%"],
    ["평균 별점", s.avg_rating === null ? "–" : s.avg_rating.toFixed(1), s.avg_rating === null ? "" : " / 5"],
    ["받은 평가", `${s.feedback}`, "건"],
  ];
  $("tiles").replaceChildren(...tiles.map(([label, value, unit]) => {
    const li = el("li", "panel tile");
    li.append(el("span", "tile-label", label));
    const v = el("span", "tile-value", value);
    if (unit) v.append(el("small", "", unit));
    li.append(v);
    return li;
  }));
}

function drawPlanners(s) {
  const names = Object.keys(s.by_planner).sort();
  const table = $("planners");
  if (!names.length) {
    table.replaceChildren(el("caption", "muted small", "아직 생성된 코스가 없습니다."));
    return;
  }
  const head = el("tr");
  head.append(el("th", "", "지표"), ...names.map((n) => el("th", "num", PLANNER_KO[n] || n)));
  const rows = ROWS.map(([key, label, fmt]) => {
    const tr = el("tr");
    tr.append(el("th", "", label), ...names.map((n) => el("td", "num", fmt(s.by_planner[n][key]))));
    return tr;
  });
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  tbody.append(...rows);
  table.replaceChildren(thead, tbody);
}

function drawTopPlaces(s) {
  const list = $("top-places");
  if (!s.top_places.length) {
    list.replaceChildren(el("li", "muted small", "아직 추천 기록이 없습니다."));
    return;
  }
  const max = s.top_places[0].count;
  const totalAi = s.top_places.reduce((n, p) => n + p.count, 0);
  list.replaceChildren(...s.top_places.map((p) => {
    const li = el("li");
    li.tabIndex = 0;
    li.append(el("span", "bar-label", p.name));
    const track = el("span", "bar-track");
    const bar = el("span", "bar");
    bar.style.width = `${(p.count / max) * 100}%`;
    track.append(bar);
    li.append(track, el("span", "bar-value", `${p.count}회`));
    li.append(el("span", "tip", `${p.name} · ${p.count}회 추천 (상위 10곳 추천의 ${Math.round((p.count / totalAi) * 100)}%)`));
    return li;
  }));
}

function drawRecent(items) {
  const tbody = $("recent").querySelector("tbody");
  if (!items.length) {
    const tr = el("tr");
    const td = el("td", "muted small", "아직 생성된 코스가 없습니다.");
    td.colSpan = 6;
    tr.append(td);
    tbody.replaceChildren(tr);
    return;
  }
  tbody.replaceChildren(...items.map((c) => {
    const tr = el("tr");
    const href = `/?course=${encodeURIComponent(c.id)}`;
    const query = el("td", "query");
    const a = el("a", "", c.query);
    a.href = href;
    a.title = c.query;
    query.append(a);
    tr.append(
      el("td", "nowrap muted", formatTime(c.created_at)),
      query,
      el("td", "nowrap", PLANNER_KO[c.planner] || c.planner),
      el("td", "num", `${c.n_places}곳`),
      el("td", "num", `${Math.round(c.local_commerce_ratio * 100)}%`),
      el("td", "num", c.score.toFixed(2)),
    );
    tr.addEventListener("click", (e) => { if (e.target.tagName !== "A") location.href = href; });
    return tr;
  }));
}

async function drawFeedback() {
  const list = $("feedback");
  const res = await adminFetch("/api/admin/feedback?limit=20", {}, false);
  if (res.status === 401) {
    const button = el("button", "inline secondary", "관리자 토큰 입력 후 보기");
    button.type = "button";
    button.addEventListener("click", async () => {
      const token = prompt("관리자 토큰을 입력하세요 (ROUTEFIT_ADMIN_TOKEN)");
      if (token) { adminToken.set(token); drawFeedback(); }
    });
    const li = el("li");
    li.append(el("p", "muted small", "한줄평은 관리자만 볼 수 있습니다."), button);
    list.replaceChildren(li);
    return;
  }
  const items = (await res.json()).filter((f) => f.comment);
  list.replaceChildren(...(items.length ? items.map((f) => {
    const li = el("li");
    li.append(el("div", "", `“${f.comment}”`));
    const meta = el("div", "muted small", `${"★".repeat(f.rating)}${"☆".repeat(5 - f.rating)} · ${formatTime(f.created_at)} · `);
    const a = el("a", "", "코스 보기");
    a.href = `/?course=${encodeURIComponent(f.course_id)}`;
    meta.append(a);
    li.append(meta);
    return li;
  }) : [el("li", "muted small", "아직 한줄평이 없습니다.")]));
}

async function load() {
  $("refresh").disabled = true;
  try {
    const [stats, recent] = await Promise.all([
      fetch("/api/stats").then((r) => r.json()),
      fetch("/api/courses?limit=10").then((r) => r.json()),
    ]);
    drawTiles(stats);
    drawPlanners(stats);
    drawTopPlaces(stats);
    drawRecent(recent);
    await drawFeedback();
    $("updated").textContent = `(${new Date().toLocaleTimeString("ko-KR")} 기준)`;
  } finally {
    $("refresh").disabled = false;
  }
}

$("refresh").addEventListener("click", load);
load();

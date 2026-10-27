import { useEffect, useRef, useState } from "react";
import Header from "../components/Header.jsx";
import MiniMap from "../components/MiniMap.jsx";
import { CATEGORY_KO, adminFetch, errorText, formatTime } from "../common.js";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const NEW_RATER = "__new__";
const NO_STATUS = { text: "", ok: false };

const BLANK_PLACE = {
  id: "", kind: "candidate", name: "", category: "sight", area: "", aliases: [], description: "",
  lat: "", lng: "", open: "10:00", close: "22:00", break_start: null, break_end: null, closed_days: [], stay_min: 60, cost: 0,
  gwangju_ness: 3, stay_inducement: 3, commerce_link: 3, is_local_commerce: false, verified: false, n_ratings: 0,
};

// 서버의 장소 -> 입력칸 값
function toForm(p) {
  return {
    id: p.id,
    kind: p.kind,
    name: p.name,
    category: p.category,
    area: p.area,
    aliases: p.aliases.join(", "),
    description: p.description ?? "",
    tags: p.tags || {},
    lat: p.lat,
    lng: p.lng,
    open: p.open,
    close: p.close,
    breakStart: p.break_start ?? "",
    breakEnd: p.break_end ?? "",
    closed: p.closed_days,
    stay: p.stay_min,
    cost: p.cost,
    gwangju: p.gwangju_ness,
    stayind: p.stay_inducement,
    commerce: p.commerce_link,
    local: p.is_local_commerce,
    verified: p.verified,
    nRatings: p.n_ratings,
    updatedAt: p.updated_at,
  };
}

// 태그는 목록(tags.json) 순서대로, 값이 있는 묶음만
function pickedTags(tags, groups) {
  const out = {};
  for (const g of groups) {
    const values = g.values.filter((v) => (tags[g.key] || []).includes(v));
    if (values.length) out[g.key] = values;
  }
  return out;
}

const sheetOf = (view, rater) => {
  const sheet = view.sheets.find((x) => x.rater === rater);
  return { checks: { ...(sheet?.checks || {}) }, evidence: { ...(sheet?.evidence || {}) } };
};

export default function AdminPage() {
  // ---------- 상태 ----------
  const [places, setPlacesState] = useState([]);
  const placesRef = useRef([]); // await 뒤에서도 최신 목록을 읽기 위해
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelectedState] = useState(null); // 편집 중인 장소 id. 새 장소면 null
  const selectedRef = useRef(null);
  const [editor, setEditor] = useState(null); // null(안 보임) | { isNew }
  const [editorToken, setEditorToken] = useState(0);

  const [search, setSearch] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [filterVerified, setFilterVerified] = useState("");

  const [form, setForm] = useState(() => toForm(BLANK_PLACE));
  const [formStatus, setFormStatus] = useState(NO_STATUS);
  const [tagGroups, setTagGroups] = useState([]);

  const [checklistDef, setChecklistDef] = useState(null);
  const [checklistView, setChecklistView] = useState({ sheets: [], evaluation: null });
  const [rater, setRater] = useState(NEW_RATER);
  const [raterNew, setRaterNew] = useState("");
  const [draft, setDraft] = useState({ checks: {}, evidence: {} });
  const [checklistStatus, setChecklistStatus] = useState(NO_STATUS);

  const miniMap = useRef(null);
  const pendingPoint = useRef(null); // 편집창이 열린 뒤 지도에 적용할 좌표 ({lat, lng} | "remove")

  const setPlaces = (list) => { placesRef.current = list; setPlacesState(list); };
  const setSelected = (id) => { selectedRef.current = id; setSelectedState(id); };
  const patch = (changes) => setForm((f) => ({ ...f, ...changes }));
  const text = (name) => ({ value: form[name], onChange: (e) => patch({ [name]: e.target.value }) });

  // ---------- 지도 (좌표 고르기) ----------

  // 편집창이 (다시) 열리면 지도 크기를 다시 재고, 정해 둔 좌표로 옮긴다.
  useEffect(() => {
    if (!miniMap.current) return;
    miniMap.current.invalidateSize();
    const point = pendingPoint.current;
    pendingPoint.current = null;
    if (point === "remove") miniMap.current.removeMarker();
    else if (point) miniMap.current.setPoint(point.lat, point.lng);
  }, [editorToken]);

  function pickPoint(lat, lng) {
    patch({ lat: lat.toFixed(6), lng: lng.toFixed(6) });
    miniMap.current.setPoint(lat, lng, false);
  }

  function movePoint() {
    const lat = Number(form.lat), lng = Number(form.lng);
    if (lat && lng) miniMap.current.setPoint(lat, lng);
  }

  // ---------- 불러오기 ----------

  async function loadPlaces() {
    const res = await adminFetch("/api/admin/places");
    if (!res.ok) {
      setLoadError(res.status === 401 ? "(관리자 토큰이 필요합니다. 새로고침 후 입력하세요)" : "(불러오기 실패)");
      return;
    }
    setLoadError("");
    setPlaces(await res.json());
    setLoaded(true);
  }

  useEffect(() => {
    Promise.all([
      fetch("/api/tags").then((r) => r.json()).then(setTagGroups),
      fetch("/api/checklist").then((r) => r.json()).then(setChecklistDef),
      loadPlaces(),
    ]).then(() => {
      const id = new URLSearchParams(location.search).get("place");
      if (id) openPlace(id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- 목록 ----------

  const q = search.trim().toLowerCase();
  const shown = places.filter((p) =>
    (!filterKind || p.kind === filterKind)
    && (!filterVerified || String(p.verified) === filterVerified)
    && (!q || [p.name, p.id, p.area, ...p.aliases, ...Object.values(p.tags || {}).flat()].some((s) => s.toLowerCase().includes(q))));
  const lacking = places.filter((p) => p.missing_tags.length).length;
  const countText = loadError || (loaded
    ? `${shown.length} / ${places.length}곳 · 검증 ${places.filter((p) => p.verified).length}곳${lacking ? ` · 태그 부족 ${lacking}곳` : ""}`
    : "");

  // ---------- 편집 폼 ----------

  function showEditor(isNew) {
    setEditor({ isNew });
    setEditorToken((t) => t + 1);
    setFormStatus(NO_STATUS);
    setChecklistStatus(NO_STATUS);
  }

  async function openPlace(id) {
    const p = placesRef.current.find((x) => x.id === id);
    if (!p) return;
    setSelected(id);
    history.replaceState(null, "", `?place=${encodeURIComponent(id)}`); // 이 장소를 바로 여는 링크
    showEditor(false);
    setForm(toForm(p));
    pendingPoint.current = { lat: p.lat, lng: p.lng };
    await loadChecklist();
  }

  function newPlace() {
    setSelected(null);
    history.replaceState(null, "", location.pathname);
    showEditor(true);
    setForm(toForm(BLANK_PLACE));
    pendingPoint.current = "remove";
    setTimeout(() => document.getElementById("f-id")?.focus());
  }

  function readForm() {
    return {
      id: form.id.trim(),
      kind: form.kind,
      name: form.name.trim(),
      category: form.category,
      area: form.area.trim(),
      aliases: form.aliases.split(",").map((s) => s.trim()).filter(Boolean),
      description: form.description.trim(),
      tags: pickedTags(form.tags, tagGroups),
      lat: Number(form.lat),
      lng: Number(form.lng),
      open: form.open.trim(),
      close: form.close.trim(),
      break_start: form.breakStart.trim() || null,
      break_end: form.breakEnd.trim() || null,
      closed_days: [...form.closed].sort((a, b) => a - b),
      stay_min: Number(form.stay),
      cost: Number(form.cost),
      gwangju_ness: Number(form.gwangju),
      stay_inducement: Number(form.stayind),
      commerce_link: Number(form.commerce),
      is_local_commerce: form.local,
      verified: form.verified,
    };
  }

  async function savePlace(event) {
    event.preventDefault();
    const isNew = selected === null;
    const res = await adminFetch(isNew ? "/api/admin/places" : `/api/admin/places/${selected}`, {
      method: isNew ? "POST" : "PUT",
      body: JSON.stringify(readForm()),
    });
    const data = await res.json();
    if (!res.ok) {
      setFormStatus({ text: errorText(data, "저장하지 못했습니다."), ok: false });
      return;
    }
    await loadPlaces();
    await openPlace(data.id);
    setFormStatus({ text: isNew ? "새 장소를 추가했습니다." : "저장했습니다.", ok: true });
  }

  async function deletePlace() {
    const p = places.find((x) => x.id === selected);
    if (!confirm(`'${p.name}' 을(를) 삭제할까요? 체크리스트와 이동시간 기록도 함께 지워집니다.`)) return;
    const res = await adminFetch(`/api/admin/places/${selected}`, { method: "DELETE" });
    if (!res.ok) {
      setFormStatus({ text: "삭제하지 못했습니다.", ok: false });
      return;
    }
    setSelected(null);
    setEditor(null);
    pendingPoint.current = "remove";
    setEditorToken((t) => t + 1);
    await loadPlaces();
  }

  // ---------- 태그 (data/tags.json) ----------

  function toggleTag(group, value) {
    setForm((f) => {
      const current = f.tags[group.key] || [];
      const on = !current.includes(value);
      const next = on ? (group.multiple ? [...current, value] : [value]) : current.filter((v) => v !== value);
      return { ...f, tags: { ...f.tags, [group.key]: next } };
    });
  }

  // 서버의 tags.sentence 와 같은 형식 (취향 매칭에 실제로 들어가는 문장)
  const tags = pickedTags(form.tags, tagGroups);
  const sentence = tagGroups.filter((g) => tags[g.key]).map((g) => `${g.label}: ${tags[g.key].join(" / ")}`).join(" | ");
  const missing = form.kind === "candidate" ? tagGroups.filter((g) => g.required && !tags[g.key]).map((g) => g.label) : [];

  // ---------- 현장조사 체크리스트 (data/checklist.json) ----------

  async function loadChecklist(keepRater) {
    const res = await adminFetch(`/api/admin/places/${selectedRef.current}/checklists`);
    const view = res.ok ? await res.json() : { sheets: [], evaluation: null };
    const raters = view.sheets.map((x) => x.rater);
    const next = raters.includes(keepRater) ? keepRater : (raters[0] || NEW_RATER);
    setChecklistView(view);
    setRater(next);
    setDraft(sheetOf(view, next));
  }

  function changeRater(value) {
    setRater(value);
    setChecklistStatus(NO_STATUS);
    setDraft(sheetOf(checklistView, value));
  }

  async function afterChecklistChange(res, message, keepRater) {
    const data = await res.json();
    if (!res.ok) {
      setChecklistStatus({ text: errorText(data, "저장하지 못했습니다."), ok: false });
      return;
    }
    setPlaces(placesRef.current.map((p) => (p.id === data.id ? data : p)));
    setForm(toForm(data));
    await loadChecklist(keepRater);
    setChecklistStatus({ text: message, ok: true });
  }

  async function saveChecklist(event) {
    event.preventDefault();
    const name = rater === NEW_RATER ? raterNew.trim() : rater;
    if (!name) {
      setChecklistStatus({ text: "채점자 이름을 입력하세요.", ok: false });
      document.getElementById("c-rater-new").focus();
      return;
    }
    const checks = {}, evidence = {};
    for (const item of checklistDef.items.filter((i) => !i.auto)) {
      checks[item.key] = !!draft.checks[item.key];
      const note = (draft.evidence[item.key] || "").trim();
      if (note) evidence[item.key] = note;
    }
    const res = await adminFetch(`/api/admin/places/${selected}/checklists`, {
      method: "PUT", body: JSON.stringify({ rater: name, checks, evidence }),
    });
    setRaterNew("");
    await afterChecklistChange(res, `${name} 님의 체크리스트를 저장했습니다.`, name);
  }

  async function deleteRater() {
    if (!confirm(`${rater} 님의 체크리스트를 삭제할까요?`)) return;
    const res = await adminFetch(`/api/admin/places/${selected}/checklists/${encodeURIComponent(rater)}`, { method: "DELETE" });
    await afterChecklistChange(res, `${rater} 님의 체크리스트를 삭제했습니다.`, null);
  }

  // ---------- 내보내기 / 초기화 ----------

  async function exportJson() {
    const res = await adminFetch("/api/admin/export");
    if (!res.ok) return;
    const data = await res.json();
    // data/places.json · anchors.json · travel_matrix.json · checklists.json 으로 나눠 저장한다
    const files = [["places", data.places], ["anchors", data.anchors], ["travel_matrix", data.travel_matrix], ["checklists", data.checklists]];
    for (const [name, rows] of files) {
      if (!Array.isArray(rows) && !Object.keys(rows).length) continue; // 비어 있는 이동시간·체크리스트는 건너뛴다
      const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${name}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    }
  }

  async function resetToExamples() {
    if (!confirm("장소·이동시간·체크리스트를 data/*.json 기준으로 되돌립니다.\n이 화면에서 고친 내용과 체크리스트가 모두 지워집니다(data/checklists.json 이 있으면 그 내용으로). 계속할까요?")) return;
    const res = await adminFetch("/api/admin/import", { method: "POST" });
    if (!res.ok) return;
    setSelected(null);
    setEditor(null);
    await loadPlaces();
  }

  // ---------- 화면 ----------

  const rated = form.nRatings > 0; // 체크리스트가 있으면 점수·지역상권 여부는 체크리스트가 정한다
  const isNewRater = rater === NEW_RATER;
  const items = Object.fromEntries((checklistView.evaluation?.items || []).map((i) => [i.key, i]));
  const scores = checklistView.evaluation?.scores || {};
  const counted = checklistView.sheets.length > 0;

  return (
    <>
      <Header tagline="장소 관리 · 현장조사 입력" current="admin" />

      <main className="page">
        <section className="toolbar">
          <p className="muted small">저장하면 다음 코스부터 바로 반영됩니다. 다 고친 뒤에는 <b>JSON 내보내기</b>로 받아 <code>data/</code>에 커밋해 두세요.</p>
          <div className="actions">
            <button type="button" id="export" className="inline secondary" onClick={exportJson}>JSON 내보내기</button>
            <button type="button" id="import" className="inline secondary" onClick={resetToExamples}>예시 데이터로 초기화</button>
          </div>
        </section>

        <div className="admin-grid">
          <section className="panel">
            <div className="list-head">
              <h2>장소 <span id="count" className="muted small">{countText}</span></h2>
              <button type="button" id="new-place" className="inline" onClick={newPlace}>+ 새 장소</button>
            </div>
            <div className="filters">
              <input id="search" type="search" placeholder="이름 · id · 지역 검색" aria-label="검색" value={search} onChange={(e) => setSearch(e.target.value)} />
              <select id="filter-kind" aria-label="구분" value={filterKind} onChange={(e) => setFilterKind(e.target.value)}>
                <option value="">전체</option>
                <option value="candidate">AI 추천 후보</option>
                <option value="anchor">Must Visit 목적지</option>
              </select>
              <select id="filter-verified" aria-label="검증 여부" value={filterVerified} onChange={(e) => setFilterVerified(e.target.value)}>
                <option value="">검증 전체</option>
                <option value="false">미검증</option>
                <option value="true">검증 완료</option>
              </select>
            </div>
            <div className="table-wrap">
              <table id="places" className="clickable">
                <thead>
                  <tr>
                    <th>이름</th><th>유형</th><th className="col-area">지역</th><th className="col-hours">영업</th>
                    <th className="num col-cost">1인 비용</th><th className="num">지역상권 점수</th><th className="num">채점</th><th>검증</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((p) => (
                    <tr
                      key={p.id}
                      tabIndex={0}
                      data-id={p.id}
                      className={p.id === selected ? "selected" : undefined}
                      onClick={() => openPlace(p.id)}
                      onKeyDown={(e) => { if (e.key === "Enter") openPlace(p.id); }}
                    >
                      <td>
                        <div>{p.name}{p.missing_tags.length ? <span className="badge-warn">태그 부족</span> : null}</div>
                        <div className="muted small">{`${p.id}${p.kind === "anchor" ? " · 목적지" : ""}`}</div>
                      </td>
                      <td className="nowrap">{CATEGORY_KO[p.category]}</td>
                      <td className="nowrap col-area">{p.area}</td>
                      <td className="nowrap col-hours">
                        {`${p.open}–${p.close}`}
                        {p.break_start && <div className="muted small">{`쉼 ${p.break_start}–${p.break_end}`}</div>}
                      </td>
                      <td className="num nowrap col-cost">{p.cost ? `${p.cost.toLocaleString()}원` : "무료"}</td>
                      <td className="num">{Math.round(p.local_contribution * 100) /* 알고리즘이 쓰는 지역상권 기여도(0~1)를 100점 만점으로 */}</td>
                      <td className="num">{p.n_ratings ? `${p.n_ratings}명` : "–"}</td>
                      <td className="verified">{p.verified ? "✓" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" id="editor">
            <p id="empty" className="muted" hidden={!!editor}>왼쪽에서 장소를 고르거나 <b>새 장소</b>를 누르세요.</p>

            <form id="place-form" hidden={!editor} onSubmit={savePlace}>
              <div className="list-head">
                <h2 id="form-title">{editor?.isNew ? "새 장소" : "장소 편집"}</h2>
                <span id="updated-at" className="muted small">{form.updatedAt ? `마지막 수정 ${formatTime(form.updatedAt)}` : ""}</span>
                <div className="actions">
                  <button type="button" className="inline danger" id="delete" hidden={!!editor?.isNew} onClick={deletePlace}>삭제</button>
                  <button type="submit" className="inline" id="save">저장</button>
                </div>
              </div>
              <p id="form-status" className={`form-status${formStatus.ok ? " ok" : ""}`} role="status">{formStatus.text}</p>

              <h3>기본 정보</h3>
              <div className="form-grid">
                <div className="field span-2">
                  <label htmlFor="f-name">이름</label>
                  <input id="f-name" required {...text("name")} />
                </div>
                <div className="field">
                  <label htmlFor="f-id">id <span className="muted small">(만든 뒤 변경 불가)</span></label>
                  <input id="f-id" required pattern="[a-z0-9_]+" maxLength={64} placeholder="영문 소문자·숫자·_" title="영문 소문자, 숫자, _ 만 쓸 수 있습니다" readOnly={!editor?.isNew} {...text("id")} />
                </div>
                <div className="field">
                  <label htmlFor="f-kind">구분</label>
                  <select id="f-kind" {...text("kind")}>
                    <option value="candidate">AI 추천 후보</option>
                    <option value="anchor">Must Visit 목적지</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="f-category">유형</label>
                  <select id="f-category" {...text("category")}>
                    {Object.entries(CATEGORY_KO).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="f-area">지역</label>
                  <input id="f-area" required placeholder="동구 동명동" {...text("area")} />
                </div>
                <div className="field span-2">
                  <label htmlFor="f-aliases">다른 이름 <span className="muted small">(쉼표로 구분)</span></label>
                  <input id="f-aliases" placeholder="ACC, 아시아문화전당" title="사용자 문장에서 이 장소를 찾을 때 씁니다" {...text("aliases")} />
                </div>
              </div>

              <h3>취향 태그 <span className="muted small">취향 매칭은 여기서 고른 태그로만 합니다 · <b className="req">*</b> 필수</span></h3>
              <div id="tag-groups" className="tag-groups">
                {tagGroups.map((g) => (
                  <div className={`tag-group${missing.includes(g.label) ? " missing" : ""}`} data-key={g.key} key={g.key}>
                    <span className="tag-group-label">
                      {g.label}
                      {g.required ? <b className="req"> *</b> : null}
                      {!g.multiple ? <span className="muted small"> (하나)</span> : null}
                    </span>
                    <div className="tag-chips" role="group" aria-label={g.label}>
                      {g.values.map((v) => (
                        <button
                          key={v}
                          type="button"
                          className="tag-chip"
                          data-value={v}
                          aria-pressed={(form.tags[g.key] || []).includes(v)}
                          onClick={() => toggleTag(g, v)}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p className="tag-preview"><span className="muted small">AI가 읽는 문장</span> <span id="tag-sentence" className={sentence ? "" : "muted"}>{sentence || "태그를 고르세요"}</span></p>

              <div className="form-grid">
                <div className="field span-4">
                  <label htmlFor="f-description">한줄 소개 <span className="muted small">(선택 · 취향 매칭에는 쓰이지 않고, 추천 이유를 쓸 때 사실 자료로만 씁니다)</span></label>
                  <textarea id="f-description" rows={2} placeholder="예: 1935년 개관한 단관 극장. 손으로 그린 간판이 남아 있다." {...text("description")} />
                </div>
              </div>

              <h3>위치 <span className="muted small">지도를 클릭하면 좌표가 들어갑니다</span></h3>
              <div className="form-grid location">
                <MiniMap ref={miniMap} onPick={pickPoint} />
                <div className="field-stack">
                  <div className="field"><label htmlFor="f-lat">위도</label><input id="f-lat" type="number" step="any" required onBlur={movePoint} {...text("lat")} /></div>
                  <div className="field"><label htmlFor="f-lng">경도</label><input id="f-lng" type="number" step="any" required onBlur={movePoint} {...text("lng")} /></div>
                </div>
              </div>

              <h3>운영 <span className="muted small">자정을 넘기면 새벽 1시를 25:00처럼 적습니다</span></h3>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="f-open">여는 시각</label>
                  <input id="f-open" required pattern="\d{1,2}:[0-5]\d" placeholder="10:00" {...text("open")} />
                </div>
                <div className="field">
                  <label htmlFor="f-close">닫는 시각</label>
                  <input id="f-close" required pattern="\d{1,2}:[0-5]\d" placeholder="22:00" {...text("close")} />
                </div>
                <div className="field">
                  <label htmlFor="f-break-start">브레이크 시작</label>
                  <input id="f-break-start" pattern="\d{1,2}:[0-5]\d" placeholder="없으면 비움" {...text("breakStart")} />
                </div>
                <div className="field">
                  <label htmlFor="f-break-end">브레이크 끝</label>
                  <input id="f-break-end" pattern="\d{1,2}:[0-5]\d" placeholder="예: 17:00" {...text("breakEnd")} />
                </div>
                <div className="field"><label htmlFor="f-stay">머무는 시간(분)</label><input id="f-stay" type="number" min="5" max="600" step="5" required {...text("stay")} /></div>
                <div className="field"><label htmlFor="f-cost">1인 예상 지출(원)</label><input id="f-cost" type="number" min="0" step="1000" required {...text("cost")} /></div>
                <div className="field span-4">
                  <span className="label">휴무 요일</span>
                  <div id="f-closed" className="checks" role="group" aria-label="휴무 요일">
                    {WEEKDAYS.map((d, i) => (
                      <label key={d}>
                        <input
                          type="checkbox"
                          value={i}
                          checked={form.closed.includes(i)}
                          onChange={(e) => patch({ closed: e.target.checked ? [...form.closed, i] : form.closed.filter((x) => x !== i) })}
                        />
                        {` ${d}`}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <h3>
                현장조사 점수{" "}
                <span className="muted small" id="scores-note">
                  {rated ? `팀원 ${form.nRatings}명의 체크리스트로 계산한 값입니다. 아래 체크리스트에서 고치세요.` : "체크리스트가 아직 없어 직접 입력한 값을 씁니다."}
                </span>
              </h3>
              <div className="form-grid">
                <div className="field"><label htmlFor="f-gwangju">광주다움 (1~5)</label><input id="f-gwangju" type="number" min="1" max="5" step="0.01" required readOnly={rated} {...text("gwangju")} /></div>
                <div className="field"><label htmlFor="f-commerce">상권 연계성 (1~5)</label><input id="f-commerce" type="number" min="1" max="5" step="0.01" required readOnly={rated} {...text("commerce")} /></div>
                <div className="field"><label htmlFor="f-stayind">체류 유도성 (1~5)</label><input id="f-stayind" type="number" min="1" max="5" step="0.01" required readOnly={rated} {...text("stayind")} /></div>
                <div className="field checks-col">
                  <label className="check" title="체크리스트가 있으면 '프랜차이즈 아님'과 '시장·상점가 구역'으로 정해집니다">
                    <input id="f-local" type="checkbox" checked={form.local} disabled={rated} onChange={(e) => patch({ local: e.target.checked })} /> 지역상권 장소
                  </label>
                  <label className="check">
                    <input id="f-verified" type="checkbox" checked={form.verified} onChange={(e) => patch({ verified: e.target.checked })} /> 현장 검증 완료
                  </label>
                </div>
              </div>
            </form>

            <section id="checklist-section" hidden={!editor || editor.isNew}>
              <div className="list-head">
                <h3>현장조사 체크리스트</h3>
                <span className="muted small">점수 = 1 + 체크한 항목 수 · 수동 항목은 체크한 팀원 비율(2명 중 1명이면 0.5)</span>
              </div>
              <form id="checklist-form" onSubmit={saveChecklist}>
                <div className="rater-bar">
                  <label htmlFor="c-rater">채점자</label>
                  <select id="c-rater" value={rater} onChange={(e) => changeRater(e.target.value)}>
                    {checklistView.sheets.map((x) => <option key={x.rater} value={x.rater}>{x.rater}</option>)}
                    <option value={NEW_RATER}>+ 새 채점자</option>
                  </select>
                  <input id="c-rater-new" placeholder="새 채점자 이름" maxLength={50} aria-label="새 채점자 이름" hidden={!isNewRater} value={raterNew} onChange={(e) => setRaterNew(e.target.value)} />
                  <div className="actions">
                    <button type="button" id="c-delete" className="inline secondary" hidden={isNewRater} onClick={deleteRater}>이 채점자 삭제</button>
                    <button type="submit" className="inline">체크리스트 저장</button>
                  </div>
                </div>
                <p id="checklist-status" className={`form-status${checklistStatus.ok ? " ok" : ""}`} role="status">{checklistStatus.text}</p>
                <div id="checklist-groups">
                  {checklistDef?.attributes.map((attr) => (
                    <div className="check-card" key={attr.key}>
                      <div className="check-head">
                        <b>{attr.label}</b>
                        <span className="muted small">{attr.question}</span>
                        <span className="check-score">{counted ? `${scores[attr.key].toFixed(1)} / 5` : "체크리스트 없음"}</span>
                      </div>
                      {checklistDef.items.filter((i) => i.attribute === attr.key).map((item) => {
                        const ev = items[item.key] || { value: 0, votes: {}, disagree: false };
                        return (
                          <div className={`check-row${ev.disagree ? " disagree" : ""}`} key={item.key}>
                            <span className="check-box">
                              {item.auto ? (
                                <span className={`auto ${ev.value ? "yes" : "no"}`}>{ev.value ? "✓" : "–"}</span>
                              ) : (
                                <input
                                  type="checkbox"
                                  id={`c-${item.key}`}
                                  checked={!!draft.checks[item.key]}
                                  onChange={(e) => setDraft((d) => ({ ...d, checks: { ...d.checks, [item.key]: e.target.checked } }))}
                                />
                              )}
                            </span>
                            <label className="check-text" htmlFor={item.auto ? undefined : `c-${item.key}`}>
                              <span>{item.label}</span>
                              <span className="muted small">{item.how}</span>
                            </label>
                            <span className="check-votes small">
                              {item.auto ? <span className="badge-auto">자동</span> : (
                                <>
                                  {Object.entries(ev.votes).map(([name, v]) => (
                                    <span className={v ? "vote yes" : "vote no"} key={name}>{`${name} ${v ? "✓" : "✗"}`}</span>
                                  ))}
                                  {ev.disagree ? <span className="badge-warn">불일치</span> : null}
                                </>
                              )}
                            </span>
                            {item.auto ? null : (
                              <input
                                className="check-evidence"
                                placeholder="근거 (링크·메모)"
                                maxLength={300}
                                value={draft.evidence[item.key] || ""}
                                onChange={(e) => setDraft((d) => ({ ...d, evidence: { ...d.evidence, [item.key]: e.target.value } }))}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </form>
            </section>
          </section>
        </div>
      </main>
    </>
  );
}

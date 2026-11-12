import { useEffect, useMemo, useRef, useState } from "react";
import Header from "../components/Header.jsx";
import TimePicker from "../components/TimePicker.jsx";
import MustVisitList, { CONFLICT_STATUS, findConflicts } from "../components/MustVisitList.jsx";
import PlaceSearch from "../components/PlaceSearch.jsx";
import CourseView from "../components/CourseView.jsx";
import CourseMap from "../components/CourseMap.jsx";
import { offScreen } from "../common.js";

// 코스 짜는 방식 설명. 고른 방식에 맞춰 한 줄로 보여 준다.
const PLANNER_HELP = {
  greedy: "취향·동선에 맞는 곳부터 하나씩 채웁니다. 예상 시간: 약 10초",
  ortools: "여러 조합을 한꺼번에 비교해 더 나은 코스를 찾습니다. 예상 시간: 약 12초",
};

// 입력칸은 비워 두고, 무엇을 적으면 되는지 예시로만 보여 준다(입력하면 사라진다).
const QUERY_EXAMPLE = "예) 연인이랑 조용하고 아늑한 데이트, 맛있는 거 먹고 디저트 카페도 가고 싶어.";

// 서버에 보낼 장소. 카카오 검색으로 고른 곳은 서버에 없으니 이름·업종·좌표를 함께 보낸다.
// 업종 이름(description)은 영화관이면 머무는 시간을 길게 잡고 다른 영화관을 빼는 데 쓴다.
function placeInput(p) {
  if (!p.id.startsWith("kakao_")) return { id: p.id };
  return { id: p.id, name: p.name, category: p.category, area: p.area, lat: p.lat, lng: p.lng, description: p.description };
}

// 날짜 옆에 요일을 보여 준다. 'YYYY-MM-DD' 를 그대로 Date 로 읽으면 UTC 로 해석되므로 나눠서 만든다.
function weekdayOf(value) {
  if (!value) return "";
  const [y, m, d] = value.split("-").map(Number);
  return `${"일월화수목금토"[new Date(y, m - 1, d).getDay()]}요일`;
}

export default function PlanPage() {
  const [query, setQuery] = useState("");
  const [visitDate, setVisitDate] = useState("");
  const [dayStart, setDayStart] = useState("");
  const [dayEnd, setDayEnd] = useState("");
  const [budget, setBudget] = useState("");
  const [planner, setPlanner] = useState("greedy");
  const [excludes, setExcludes] = useState([]); // 추천에서 뺄 등록된 장소들
  const [startPlace, setStartPlace] = useState(null); // 출발 위치(선택)
  const [moreOpen, setMoreOpen] = useState(false); // '더 자세히 정하기' 펼침
  // 접혀 있어도 값이 들어가 있다는 걸 알 수 있게 제목 옆에 개수를 보인다
  const optionalCount = [visitDate, dayStart, dayEnd, budget !== "" && budget != null].filter(Boolean).length + excludes.length;

  const [mustData, setMustData] = useState({ known: [], info: {} });
  const [musts, setMusts] = useState([]); // [{ key, id, place, start, stay }]
  const mustSeq = useRef(0); // 줄마다 label 과 입력칸을 잇는 고유 id
  const focusMust = useRef(null);

  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [course, setCourse] = useState(null);
  const [courseSeq, setCourseSeq] = useState(0);
  const [activeOrder, setActiveOrder] = useState(null);
  const mapRef = useRef(null);

  const conflicts = useMemo(() => findConflicts(musts), [musts]);

  // ---------- 필수 방문지 ----------

  const newMust = ({ place = null, start = "", stay_min = "" } = {}) =>
    ({ key: ++mustSeq.current, id: place ? place.id : "", place, start: start || "", stay: stay_min || "" });

  // 저장된 요청의 필수 방문지 -> 장소. 등록된 곳은 목록에서, 카카오 검색으로 고른 곳은 요청에 담긴 정보로.
  function placeOf(m, info) {
    if (info[m.id]) return info[m.id];
    if (m.id && m.id.startsWith("kakao_") && m.name && m.lat != null && m.lng != null) {
      return {
        id: m.id, name: m.name, category: m.category || "etc", area: m.area || "광주", lat: m.lat, lng: m.lng,
        description: m.description || "", stay_min: m.stay_min || 60,
      };
    }
    return null;
  }

  function setMustRows(list, info) {
    mustSeq.current = 0;
    const rows = list.map((m) => ({ ...m, place: placeOf(m, info) })).filter((m) => m.place);
    setMusts((rows.length ? rows : [{}]).map((m) => newMust(m)));
  }

  const changeMust = (key, patch) => setMusts((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const removeMust = (key) => setMusts((rows) => rows.filter((r) => r.key !== key));
  function addMust() {
    const row = newMust();
    focusMust.current = row.key;
    setMusts((rows) => [...rows, row]);
  }
  useEffect(() => {
    if (focusMust.current === null) return;
    document.getElementById(`must-${focusMust.current}`)?.focus();
    focusMust.current = null;
  }, [musts]);

  // 겹침이 풀리면 위에 띄워 둔 안내를 지운다.
  useEffect(() => {
    if (!conflicts.messages.size) setStatus((s) => (s === CONFLICT_STATUS ? "" : s));
  }, [conflicts]);

  // ---------- 코스와 지도를 잇는다 ----------
  // 코스의 번호·이름을 누르면 지도에서 그 장소를 가운데로 옮기고,
  // 지도의 핀을 누르면 코스에서 그 장소로 스크롤한다. 고른 장소는 양쪽에 함께 표시한다.

  function focusStop(order) {
    if (mapRef.current?.focusStop(order)) setActiveOrder(order);
  }

  function focusTimeline(order) {
    setActiveOrder(order);
    const li = document.querySelector(`#timeline li[data-order="${order}"]`);
    if (li && offScreen(li)) li.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // 코스 전체가 지도에 들어오게 한다. 장소를 골라 둔 표시는 지운다.
  function showWholeRoute() {
    setActiveOrder(null);
    mapRef.current?.showWholeRoute();
  }

  function showCourse(data) {
    setCourse(data);
    setCourseSeq((n) => n + 1);
    setActiveOrder(null);
  }

  // 결과의 AI 추천 장소 하나를 고른 곳으로 바꾼 새 코스. 실패하면 안내 문구를 돌려준다(바꾸기 상자에 보인다).
  async function swapStop(order, placeId) {
    try {
      const res = await fetch(`/api/courses/${encodeURIComponent(course.id)}/swap`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order, place_id: placeId }),
      });
      const data = await res.json();
      if (!res.ok) return typeof data.detail === "string" ? data.detail : "바꾸지 못했습니다.";
      showCourse(data);
      history.replaceState(null, "", data.id ? `?course=${data.id}` : location.pathname);
      const swapped = data.stops.find((s) => s.place_id === placeId);
      if (swapped) setActiveOrder(swapped.order); // 바뀐 곳을 표시해 둔다
      return null;
    } catch {
      return "바꾸지 못했습니다. 잠시 뒤 다시 해 주세요.";
    }
  }

  // ---------- 불러오기 ----------

  // 저장된 요청으로 입력칸을 되살린다. 받은 사람이 조건을 조금 바꿔 다시 만들어 볼 수 있다.
  function fillForm(req, info) {
    setQuery(req.query);
    setMustRows(req.must_visits, info);
    setDayStart(req.day_start || "");
    setDayEnd(req.day_end || "");
    setBudget(req.budget ?? "");
    setVisitDate(req.visit_date || "");
    setPlanner(req.planner || "greedy");
    setExcludes((req.exclude_ids || []).map((id) => info[id]).filter(Boolean));
    setStartPlace(req.start ? placeOf(req.start, info) : null);
    setMoreOpen(Boolean(req.day_start || req.day_end || req.budget != null || req.visit_date || req.exclude_ids?.length));
  }

  // 공유 링크(?course=<id>)로 들어오면 저장된 코스를 보여 준다.
  async function loadSharedCourse(info) {
    const id = new URLSearchParams(location.search).get("course");
    if (!id) return;
    const res = await fetch(`/api/courses/${encodeURIComponent(id)}`);
    if (!res.ok) {
      setStatus("공유된 코스를 찾을 수 없습니다.");
      return;
    }
    const shared = await res.json();
    if (shared.request) fillForm(shared.request, info);
    showCourse(shared);
  }

  // 필수 방문지 목록이 채워진 뒤에 공유 코스의 입력값을 넣어야 선택이 맞는다.
  useEffect(() => {
    (async () => {
      const [anchors, places] = await Promise.all(
        ["/api/anchors", "/api/places"].map((url) => fetch(url).then((r) => r.json())),
      );
      const info = {};
      for (const p of [...anchors, ...places]) info[p.id] = p;
      setMustData({ known: [...anchors, ...places], info });
      setMustRows([], info); // 처음에는 필수 방문지 없음(빈 줄 하나)
      await loadSharedCourse(info);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- 만들기 ----------

  async function submit(event) {
    event.preventDefault();
    if (conflicts.messages.size) {
      setStatus(CONFLICT_STATUS);
      document.getElementById("must-list").querySelector("[aria-invalid]")?.focus();
      return;
    }
    const body = {
      query,
      must_visits: musts
        .filter((m) => m.place) // 장소를 고르지 않은 줄은 건너뛴다
        .map((m) => ({ ...placeInput(m.place), start: m.start || null, stay_min: Number(m.stay) || null })),
      start: startPlace ? placeInput(startPlace) : null,
      day_start: dayStart || null,
      day_end: dayEnd || null,
      budget: budget === "" ? null : Number(budget),
      visit_date: visitDate || null,
      exclude_ids: excludes.map((p) => p.id),
      planner,
    };

    setBusy(true);
    setStatus("코스를 조합하는 중…");
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
      setStatus("");
      document.getElementById("course").scrollIntoView({ behavior: "smooth", block: "start" }); // 만든 코스로 화면을 옮긴다
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Header tagline="광주에 온 하나의 이유를 하루로" current="plan" />

      <main>
        <form id="plan-form" className="panel" onSubmit={submit}>
          <h2>조건 입력</h2>

          <label htmlFor="start-place">출발 위치 <span className="muted small">(선택)</span></label>
          <PlaceSearch
            id="start-place"
            place={startPlace}
            known={mustData.known}
            chosenIds={[]}
            placeholder="예) 광주역, 유스퀘어, 묵는 숙소"
            describedBy="start-help"
            suggestVenues={false}
            onPick={setStartPlace}
            onClear={() => setStartPlace(null)}
          />
          <p id="start-help" className="muted small help">정하면 이곳에서 출발하는 동선으로 짭니다. 비워 두면 첫 장소부터 시작해요.</p>

          <MustVisitList
            musts={musts}
            known={mustData.known}
            conflicts={conflicts}
            onChange={changeMust}
            onRemove={removeMust}
            onAdd={addMust}
          />

          <label htmlFor="query">어떤 하루를 원하세요? <span className="tag ai">AI 추천</span></label>
          <textarea id="query" rows={3} required aria-describedby="query-help" placeholder={QUERY_EXAMPLE} value={query} onChange={(e) => setQuery(e.target.value)} />
          <p id="query-help" className="muted small help">하고 싶은 것을 적어 주세요. 요일·시간·동행도 알아서 읽습니다.</p>

          {/* 직접 지정: 문장으로 다 말할 수 있어서 접어 둔다. 공유 링크로 값이 채워지면 펼친다(fillForm) */}
          <details className="optional-box" open={moreOpen} onToggle={(e) => setMoreOpen(e.currentTarget.open)}>
            <summary>
              더 자세히 정하기 <span className="muted small">(선택{optionalCount ? ` · ${optionalCount}개 지정됨` : ""})</span>
            </summary>
            <label htmlFor="visit-date">방문 날짜 <span className="muted small">(휴무 제외)</span></label>
            <div className="with-unit">
              <input id="visit-date" type="date" value={visitDate} onChange={(e) => setVisitDate(e.target.value)} />
              <span id="visit-weekday" className="weekday">{weekdayOf(visitDate)}</span>
            </div>
            <div className="row">
              <div>
                <label htmlFor="day-start-field">하루 시작</label>
                <TimePicker id="day-start" name="하루 시작" value={dayStart} onChange={setDayStart} />
              </div>
              <div>
                <label htmlFor="day-end-field">하루 종료</label>
                <TimePicker id="day-end" name="하루 종료" value={dayEnd} onChange={setDayEnd} />
              </div>
            </div>
            <label htmlFor="budget">1인 예산</label>
            <div className="with-unit">
              <input id="budget" type="number" min="0" step="10000" placeholder="문장에서 찾기" value={budget} onChange={(e) => setBudget(e.target.value)} />
              <span>원</span>
            </div>
            <label htmlFor="exclude-search">빼고 싶은 장소</label>
            <PlaceSearch
              id="exclude-search"
              place={null}
              known={mustData.known}
              chosenIds={excludes.map((p) => p.id)}
              placeholder="장소 이름으로 검색"
              describedBy="exclude-help"
              forExclude
              onPick={(p) => setExcludes((list) => [...list, p])}
              onClear={() => {}}
            />
            {excludes.length ? (
              <ul className="chips exclude-chips">
                {excludes.map((p) => (
                  <li key={p.id}>
                    <b>{p.name}</b>
                    <button type="button" className="chip-remove" aria-label={`${p.name} 빼기 취소`} onClick={() => setExcludes((list) => list.filter((x) => x.id !== p.id))}>×</button>
                  </li>
                ))}
              </ul>
            ) : null}
            <p id="exclude-help" className="muted small help">음식이나 낱말은 문장에 적어도 됩니다. 예) 훠궈는 싫어요</p>
            <button
              type="button"
              id="clear-optional"
              className="link"
              onClick={() => { setVisitDate(""); setDayStart(""); setDayEnd(""); setBudget(""); setExcludes([]); }}
            >
              모두 비우기
            </button>
          </details>

          <label htmlFor="planner">코스 짜는 방식</label>
          <select id="planner" aria-describedby="planner-help" value={planner} onChange={(e) => setPlanner(e.target.value)}>
            <option value="greedy">기본 추천</option>
            <option value="ortools">최적화 추천</option>
          </select>
          <p id="planner-help" className="muted small help">{PLANNER_HELP[planner]}</p>

          <button type="submit" disabled={busy}>코스 만들기</button>
          <p id="status" role="status">{status}</p>
        </form>

        <CourseView
          course={course}
          courseSeq={courseSeq}
          activeOrder={activeOrder}
          onFocusStop={focusStop}
          onShowRoute={showWholeRoute}
          onSwap={swapStop}
        />

        <CourseMap
          ref={mapRef}
          course={course}
          activeOrder={activeOrder}
          onPinClick={focusTimeline}
          onShowRoute={showWholeRoute}
        />
      </main>
    </>
  );
}

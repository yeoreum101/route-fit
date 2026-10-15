import { useEffect, useMemo, useRef, useState } from "react";
import Header from "../components/Header.jsx";
import TimePicker from "../components/TimePicker.jsx";
import MustVisitList, { CONFLICT_STATUS, findConflicts } from "../components/MustVisitList.jsx";
import CourseView from "../components/CourseView.jsx";
import CourseMap from "../components/CourseMap.jsx";
import { offScreen } from "../common.js";

// 코스 짜는 방식 설명. 고른 방식에 맞춰 한 줄로 보여 준다.
const PLANNER_HELP = {
  greedy: "취향·동선에 맞는 곳부터 하나씩 채웁니다. 예상 시간: 약 10초",
  ortools: "여러 조합을 한꺼번에 비교해 더 나은 코스를 찾습니다. 예상 시간: 약 12초",
};

const DEFAULT_QUERY = "토요일 야구 보기 전에 사진 찍기 좋은 데랑 로컬 맛집 가고 싶어";

// 날짜 옆에 요일을 보여 준다. 'YYYY-MM-DD' 를 그대로 Date 로 읽으면 UTC 로 해석되므로 나눠서 만든다.
function weekdayOf(value) {
  if (!value) return "";
  const [y, m, d] = value.split("-").map(Number);
  return `${"일월화수목금토"[new Date(y, m - 1, d).getDay()]}요일`;
}

export default function PlanPage() {
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [visitDate, setVisitDate] = useState("");
  const [dayStart, setDayStart] = useState("");
  const [dayEnd, setDayEnd] = useState("");
  const [budget, setBudget] = useState("");
  const [planner, setPlanner] = useState("greedy");

  const [mustData, setMustData] = useState({ groups: [], info: {} });
  const [musts, setMusts] = useState([]); // [{ key, id, start, stay }]
  const mustSeq = useRef(0); // 줄마다 label 과 입력칸을 잇는 고유 id
  const focusMust = useRef(null);

  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [course, setCourse] = useState(null);
  const [courseSeq, setCourseSeq] = useState(0);
  const [activeOrder, setActiveOrder] = useState(null);
  const mapRef = useRef(null);

  const conflicts = useMemo(() => findConflicts(musts, mustData.info), [musts, mustData.info]);

  // ---------- 필수 방문지 ----------

  const newMust = ({ id = "", start = "", stay_min = "" } = {}) => ({ key: ++mustSeq.current, id, start, stay: stay_min || "" });

  function setMustRows(list, info) {
    mustSeq.current = 0;
    setMusts((list.length ? list : [{}]).map((m) => newMust({ ...m, id: info[m.id] ? m.id : "" })));
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

  // ---------- 불러오기 ----------

  // 저장된 요청으로 입력칸을 되살린다. 받은 사람이 조건을 조금 바꿔 다시 만들어 볼 수 있다.
  function fillForm(req, info) {
    setQuery(req.query);
    setMustRows(req.must_visits.filter((m) => m.id && info[m.id]), info);
    setDayStart(req.day_start || "");
    setDayEnd(req.day_end || "");
    setBudget(req.budget ?? "");
    setVisitDate(req.visit_date || "");
    setPlanner(req.planner || "greedy");
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
      setMustData({ groups: [["목적지", anchors], ["원도심 장소", places]], info });
      setMustRows([{ id: "champions_field", start: "18:30" }], info);
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
        .filter((m) => m.id) // 장소를 고르지 않은 줄은 건너뛴다
        .map((m) => ({ id: m.id, start: m.start || null, stay_min: Number(m.stay) || null })),
      day_start: dayStart || null,
      day_end: dayEnd || null,
      budget: budget === "" ? null : Number(budget),
      visit_date: visitDate || null,
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

          <MustVisitList
            musts={musts}
            groups={mustData.groups}
            info={mustData.info}
            conflicts={conflicts}
            onChange={changeMust}
            onRemove={removeMust}
            onAdd={addMust}
          />

          <label htmlFor="query">어떤 하루를 원하세요? <span className="tag ai">AI 추천</span></label>
          <textarea id="query" rows={4} required aria-describedby="query-help" value={query} onChange={(e) => setQuery(e.target.value)} />
          <p id="query-help" className="muted small help">하고 싶은 것을 적어 주세요. 요일·시간·동행도 알아서 읽습니다.</p>

          <fieldset className="optional-box">
            <legend>직접 지정 <span className="muted small">(선택)</span></legend>
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
            <button
              type="button"
              id="clear-optional"
              className="link"
              onClick={() => { setVisitDate(""); setDayStart(""); setDayEnd(""); setBudget(""); }}
            >
              모두 비우기
            </button>
          </fieldset>

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

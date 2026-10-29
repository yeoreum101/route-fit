import { Fragment, useState } from "react";
import { CATEGORY_KO, PLANNER_KO } from "../common.js";

const WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"];

// 서버가 실제로 쓴 조건과 그 출처. 화면 값이 문장을 덮어썼으면 notes 로 알려 준다.
function Conditions({ course }) {
  const c = course?.constraints;
  if (!c) return <div id="conditions" hidden />;

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

  return (
    <div id="conditions">
      <h3>인식된 조건</h3>
      <ul id="condition-chips" className="chips">
        {chips.map(([label, value, source]) => (
          <li key={label}>
            <span className="chip-label">{label}</span>
            <b>{value}</b>
            {source ? <span className="chip-source">{source}</span> : null}
          </li>
        ))}
      </ul>
      <p id="condition-taste" className="muted small">{c.taste ? `취향: “${c.taste}”` : ""}</p>
      <ul id="condition-notes" className="notes">
        {(c.notes || []).map((n, i) => <li key={i}>{n}</li>)}
      </ul>
    </div>
  );
}

// 장소를 다른 지도 서비스에서 우리 좌표 그대로 연다. 카카오는 좌표에 이름을 붙인 핀을 찍는 공식 링크가 있다.
// (네이버 웹은 좌표에 핀을 찍는 링크 형식이 없어 뺐다)
const MAP_SITES = [
  ["카카오맵", (s) => `https://map.kakao.com/link/map/${encodeURIComponent(s.name.replace(/,/g, " "))},${s.lat},${s.lng}`],
];

function MapLinks({ stop }) {
  return (
    <span className="map-links">
      {MAP_SITES.map(([label, url], i) => (
        <Fragment key={label}>
          {i ? <span>·</span> : null}
          <a href={url(stop)} target="_blank" rel="noopener" title={`${label}에서 ${stop.name} 열기`}>{label}</a>
        </Fragment>
      ))}
    </span>
  );
}

// 직전 장소에서 오는 수단. 예전에 저장된 코스에는 없어서 그때는 '이동'으로 보인다.
const TRAVEL_MODE_KO = { walk: "도보", transit: "대중교통", car: "자동차" };

function Timeline({ course, activeOrder, onFocusStop }) {
  return (
    <ol id="timeline">
      {course.stops.map((s) => (
        <li key={s.order} className={`${s.kind}${activeOrder === s.order ? " active" : ""}`} data-order={s.order}>
          <button type="button" className="dot" aria-label={`${s.order}번 ${s.name} 지도에서 보기`} onClick={() => onFocusStop(s.order)}>{s.order}</button>
          {s.travel_min ? <div className="move">{TRAVEL_MODE_KO[s.travel_mode] || "이동"} {s.travel_min}분</div> : null}
          <div className="time">
            {`${s.start} – ${s.end}`}
            <span className="cost">{s.cost ? `1인 약 ${s.cost.toLocaleString()}원` : "무료"}</span>
          </div>
          <div className="name">
            <button type="button" className="stop-link" title="지도에서 보기" onClick={() => onFocusStop(s.order)}>{s.name}</button>{" "}
            {s.kind === "must" ? <span className="tag must">필수</span> : null}
            {s.is_local_commerce ? <>{" "}<span className="tag local">지역상권</span></> : null}
            <MapLinks stop={s} />
          </div>
          <div className="muted small">{`${CATEGORY_KO[s.category]} · ${s.area}`}</div>
          {s.kind === "ai" && s.reason ? <p className="reason">{s.reason}</p> : null}
        </li>
      ))}
    </ol>
  );
}

function copyWithTextarea(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.append(ta);
  ta.select();
  ta.setSelectionRange(0, text.length); // iOS Safari
  try {
    return document.execCommand("copy");
  } finally {
    ta.remove();
  }
}

// 공유 링크 복사 · 별점과 한줄평. 코스가 새로 만들어지면(key) 처음 상태로 돌아간다.
function ShareBox({ course }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false); // 한 코스에 한 번만
  const [status, setStatus] = useState("");

  async function sendFeedback(event) {
    event.preventDefault();
    const res = await fetch(`/api/courses/${course.id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, comment: comment.trim() }),
    });
    if (res.ok) {
      setSent(true);
      setStatus(`${rating}점 평가를 보냈습니다. 고맙습니다!`);
    } else {
      setStatus("평가를 저장하지 못했습니다.");
    }
  }

  async function copyLink() {
    const url = `${location.origin}${location.pathname}?course=${course.id}`;
    try {
      // navigator.clipboard 는 HTTPS·localhost 에서만 있다. http://<서버 IP> 배포에서는 예전 방식으로 복사한다.
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(url);
      else if (!copyWithTextarea(url)) throw new Error("copy failed");
      setStatus("링크를 복사했습니다.");
    } catch {
      setStatus(`복사하지 못했습니다. 이 주소를 직접 복사해 주세요: ${url}`);
    }
  }

  return (
    <div id="share" hidden={!course.id}>
      <button type="button" id="copy-link" className="inline" onClick={copyLink}>공유 링크 복사</button>
      <form id="feedback-form" hidden={sent} onSubmit={sendFeedback}>
        <span className="muted small">이 코스 어땠나요?</span>
        <span id="rating" role="radiogroup" aria-label="코스 별점">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              className={`star${n <= rating ? " on" : ""}`}
              title={`${n}점`}
              role="radio"
              aria-label={`${n}점`}
              aria-checked={n === rating}
              onClick={() => setRating(n)}
            >
              ★
            </button>
          ))}
        </span>
        <input id="comment" maxLength={500} placeholder="한줄평 (선택)" value={comment} onChange={(e) => setComment(e.target.value)} />
        <button type="submit" className="inline" disabled={rating === 0}>평가 보내기</button>
      </form>
      <span id="share-status" className="muted small" role="status">{status}</span>
    </div>
  );
}

export default function CourseView({ course, courseSeq, activeOrder, onFocusStop, onShowRoute }) {
  const m = course?.metrics;
  const e = course?.engine;
  const metrics = course && [
    ["방문 장소", `${m.n_places}곳`],
    ["체류시간", `${Math.floor(m.stay_min / 60)}시간 ${m.stay_min % 60}분`],
    ["이동", `${m.travel_min}분`],
    ["1인 지출", m.total_cost ? `약 ${m.total_cost.toLocaleString()}원` : "무료"],
    ["지역상권", `${m.local_commerce_count}곳 (${Math.round(m.local_commerce_ratio * 100)}%)`],
  ];

  return (
    <section className="panel" id="course">
      <div className="panel-head">
        <h2>AI 생성 코스</h2>
        <button type="button" id="course-on-map" className="inline secondary" hidden={!course || !course.stops.length} onClick={onShowRoute}>지도에서 보기</button>
      </div>
      <Conditions course={course} />
      <p id="summary" className={course ? "" : "muted"}>{course ? course.summary : "조건을 입력하고 코스를 만들어 보세요."}</p>
      <ul id="metrics">
        {course ? metrics.map(([k, v]) => <li key={k}>{`${k} `}<b>{v}</b></li>) : null}
      </ul>
      {course ? <Timeline course={course} activeOrder={activeOrder} onFocusStop={onFocusStop} /> : <ol id="timeline" />}
      <details id="engine-box" hidden={!course}>
        <summary>생성 정보</summary>
        <p id="engine">
          {course ? `파싱 ${e.parser} · 임베딩 ${e.embedder} · 최적화 ${PLANNER_KO[e.planner] || e.planner} · 설명 ${e.explainer} · 이동시간 ${e.travel === "tmap" ? "TMAP 실측" : e.travel === "estimate" ? "어림값 포함" : "-"} · 점수 ${m.score}` : ""}
        </p>
      </details>
      {course ? <ShareBox key={courseSeq} course={course} /> : <div id="share" hidden />}
    </section>
  );
}

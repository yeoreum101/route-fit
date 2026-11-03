import PlaceSearch from "./PlaceSearch.jsx";
import TimePicker from "./TimePicker.jsx";

// 필수 방문지는 여러 곳을 넣을 수 있다. 한 줄 = 장소 + 시작 시각 + 머무는 시간.
// 줄의 place 는 고른 장소 자체다(등록된 장소 또는 카카오 검색으로 고른 장소).
export const MAX_MUSTS = 5;
export const CONFLICT_STATUS = "필수 방문지 시간이 겹칩니다.";

const minutes = (hm) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };
const hhmm = (t) => `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;

// 시작 시각을 정한 필수 방문지끼리 (시작 ~ 시작 + 머무는 시간) 이 겹치면 뒤쪽 줄에 알린다.
// 장소 사이 이동시간은 서버가 따져서 한 번 더 막는다.
export function findConflicts(musts) {
  const fixed = musts.map((m) => {
    if (!m.place || !m.start) return null;
    const stay = Number(m.stay) || m.place.stay_min;
    return { key: m.key, name: m.place.name, start: minutes(m.start), end: minutes(m.start) + stay };
  }).filter(Boolean).sort((a, b) => a.start - b.start);

  const messages = new Map(); // 줄 key -> 오류 문구
  const bad = new Set();
  fixed.forEach((b, i) => {
    const a = fixed.slice(0, i).find((x) => x.end > b.start); // 앞서 시작해서 아직 안 끝난 곳
    if (!a) return;
    bad.add(a.key).add(b.key);
    messages.set(b.key, `‘${a.name}’(${hhmm(a.start)}–${hhmm(a.end)}) 일정과 겹칩니다.`);
  });
  return { messages, bad };
}

// 장소를 고르지 않은 줄은 시작 시각·머무는 시간을 쓸 데가 없으므로 잠근다.
// 다른 줄에서 이미 고른 장소는 고를 수 없게 하고, 한 줄만 남으면 빼기 버튼을 숨긴다.
export default function MustVisitList({ musts, known, conflicts, onChange, onRemove, onAdd }) {
  const chosen = musts.map((m) => m.id);
  const any = chosen.some(Boolean);

  return (
    <fieldset className="must-box">
      <legend>필수 방문지 <span className="tag must">필수</span></legend>
      <div id="must-list">
        {musts.map((m, i) => {
          const n = m.key;
          const id = m.id;
          const message = conflicts.messages.get(m.key) || "";
          const invalid = conflicts.bad.has(m.key);
          const errorId = `must-${n}-error`;
          return (
            <div className="must-item" key={m.key}>
              <div className="must-head">
                <label htmlFor={`must-${n}`}>{musts.length > 1 ? `장소 ${i + 1}` : "장소"}</label>
                <button
                  type="button"
                  className="remove-must"
                  aria-label="이 필수 방문지 삭제"
                  hidden={musts.length === 1}
                  onClick={() => onRemove(m.key)}
                >
                  삭제
                </button>
              </div>

              <PlaceSearch
                id={`must-${n}`}
                place={m.place}
                known={known}
                chosenIds={chosen}
                placeholder="장소 이름으로 검색" // 비워 두면 문장에서 찾는다(아래 안내 문구)
                // 시작 시각 고정은 경기·공연장에만 기본으로 의미가 있다. 다른 장소로 바꾸면 비워 둔다.
                onPick={(p) => onChange(m.key, p.category !== "venue" ? { id: p.id, place: p, start: "" } : { id: p.id, place: p })}
                onClear={() => onChange(m.key, { id: "", place: null })}
              />

              <div className={`row must-detail${id ? "" : " off"}`}>
                <div>
                  <label htmlFor={`must-${n}-start-field`}>방문 예정 시각 <span className="muted small">(선택)</span></label>
                  <TimePicker
                    id={`must-${n}-start`}
                    className="must-start"
                    name="방문 예정 시각"
                    value={m.start}
                    disabled={!id}
                    describedBy={errorId}
                    invalid={invalid}
                    onChange={(start) => onChange(m.key, { start })}
                  />
                </div>
                <div>
                  <label htmlFor={`must-${n}-stay`}>머무는 시간</label>
                  <div className="with-unit">
                    <input
                      id={`must-${n}-stay`}
                      className="must-stay"
                      type="number"
                      min="10"
                      step="10"
                      value={m.stay}
                      disabled={!id}
                      placeholder={m.place ? `기본 ${m.place.stay_min}` : ""} // 장소마다 기본 체류시간이 다르다
                      aria-invalid={invalid ? true : undefined}
                      onChange={(e) => onChange(m.key, { stay: e.target.value })}
                    />
                    <span>분</span>
                  </div>
                </div>
              </div>

              <p className="must-error" id={errorId} role="alert" hidden={!message}>{message}</p>
            </div>
          );
        })}
      </div>
      <p className="muted small" id="must-help-off" hidden={musts.length === 0 || any}>문장에서 찾습니다. 예: “챔필에서 야구 보기 전에…”</p>
      <button type="button" id="add-must" className="add-must" hidden={musts.length >= MAX_MUSTS} onClick={onAdd}>+ 필수 방문지 추가</button>
    </fieldset>
  );
}

import { useEffect, useLayoutEffect, useRef, useState } from "react";

// 시각 고르기. 브라우저 기본 시각 입력은 오전/오후 칸을 따로 바꿔야 해서 헷갈리므로,
// '오후 6:30' 을 보여 주는 칸을 누르면 오전/오후 · 시 · 분을 눌러 고르는 작은 판이 열린다.
// value 는 'HH:MM' (시를 안 고르면 ""). 고르면 onChange(value) 가 불린다.

const pad = (n) => String(n).padStart(2, "0");
const HOURS = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const MINUTES = ["00", "10", "20", "30", "40", "50"];

function parse(value) {
  const [hh, mm = "00"] = (value || "").split(":");
  // 10분 단위가 아닌 값(예전 공유 링크 등)도 칸에는 그대로 보여 준다
  return { h: hh ? Number(hh) % 24 : null, m: mm };
}

export default function TimePicker({ id, name, className = "", value, onChange, disabled = false, describedBy, invalid = false }) {
  const { h, m } = parse(value);
  const [pmPref, setPmPref] = useState(true); // 시를 고르기 전 오전/오후 선택. 일정은 대개 오후다
  const [open, setOpen] = useState(false);
  const [right, setRight] = useState(false);
  const boxRef = useRef(null);
  const fieldRef = useRef(null);
  const popRef = useRef(null);

  const pm = h === null ? pmPref : h >= 12;
  useEffect(() => { if (h !== null) setPmPref(h >= 12); }, [h]);

  const emit = (nextH, nextM) => onChange(nextH === null ? "" : `${pad(nextH)}:${nextM}`);

  const close = (focusField) => {
    if (!open) return;
    setOpen(false);
    if (focusField) fieldRef.current?.focus();
  };

  // 열 때: 화면 오른쪽 끝을 넘으면 칸의 오른쪽에 맞춰 열고, 고른 값(없으면 '오후')으로 포커스를 옮긴다
  useLayoutEffect(() => {
    if (!open) return;
    const pop = popRef.current;
    pop.classList.remove("right");
    const overflow = pop.getBoundingClientRect().right > document.documentElement.clientWidth - 8;
    pop.classList.toggle("right", overflow);
    setRight(overflow);
    (pop.querySelector("[aria-pressed=true]:not(:disabled)") || pop.querySelector(".time-seg button:last-child")).focus();
  }, [open]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e) => { if (!boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [open]);

  const pickAmPm = (toPm) => {
    setPmPref(toPm);
    if (h !== null) emit(toPm ? (h % 12) + 12 : h % 12, m);
  };
  const pickHour = (n) => emit((n % 12) + (pm ? 12 : 0), m);
  const pickMinute = (v) => {
    emit(h, v);
    close(true);
  };
  const clear = () => {
    setPmPref(pm);
    emit(null, "00");
  };

  return (
    <span
      id={id}
      ref={boxRef}
      className={`time-pick ${className}`.trim()}
      onBlur={(e) => { if (e.relatedTarget && !boxRef.current.contains(e.relatedTarget)) close(); }}
    >
      <button
        type="button"
        ref={fieldRef}
        id={`${id}-field`}
        className={`time-field${h === null ? " empty" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-describedby={describedBy}
        aria-invalid={invalid ? true : undefined}
        disabled={disabled}
        onClick={() => (open ? close() : setOpen(true))}
      >
        {h === null ? "선택 안 함" : `${pm ? "오후" : "오전"} ${h % 12 || 12}:${m}`}
      </button>
      <button
        type="button"
        className="time-clear"
        aria-label={`${name} 지우기`}
        title="지우기"
        hidden={disabled || h === null}
        onClick={() => { clear(); close(); fieldRef.current.focus(); }}
      >
        ×
      </button>
      <div
        ref={popRef}
        className={`time-pop${right ? " right" : ""}`}
        role="dialog"
        aria-label={name}
        hidden={!open}
        onKeyDown={(e) => { if (e.key === "Escape") close(true); }}
      >
        <div className="time-seg">
          <button type="button" aria-pressed={!pm} onClick={() => pickAmPm(false)}>오전</button>
          <button type="button" aria-pressed={pm} onClick={() => pickAmPm(true)}>오후</button>
        </div>
        <div className="time-sub">시</div>
        <div className="time-grid hours">
          {HOURS.map((n) => (
            <button key={n} type="button" aria-pressed={h !== null && h % 12 === n % 12} onClick={() => pickHour(n)}>{n}</button>
          ))}
        </div>
        <div className="time-sub">분</div>
        <div className="time-grid minutes">
          {MINUTES.map((v) => (
            <button key={v} type="button" aria-pressed={h !== null && v === m} disabled={h === null} onClick={() => pickMinute(v)}>{v}</button>
          ))}
        </div>
        <div className="time-foot">
          <button type="button" className="link" onClick={() => { clear(); close(true); }}>지우기</button>
          <button type="button" className="inline" onClick={() => close(true)}>확인</button>
        </div>
      </div>
    </span>
  );
}

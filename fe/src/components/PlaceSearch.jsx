import { useEffect, useMemo, useState } from "react";
import { CATEGORY_KO } from "../common.js";

// 필수 방문지 장소 검색. 등록된 장소(목적지·원도심 장소)를 먼저 보여 주고, 두 글자부터는
// 등록되지 않은 광주의 장소도 카카오 장소 검색(/api/place-search)으로 찾는다.
// 고르면 onPick(장소), 글자를 고치면 선택이 풀린다(onClear).
// 빼고 싶은 장소를 고를 때는 forExclude: 카카오 검색 없이 등록된 장소만, 고른 뒤 입력칸을 비운다.
const MAX_KNOWN = 8;

const compact = (s) => s.replace(/\s/g, "");

function matchKnown(known, text, suggestVenues) {
  const key = compact(text);
  if (!key) return suggestVenues ? known.filter((p) => p.category === "venue") : []; // 비어 있으면 자주 쓰는 목적지(행사장)
  return known.filter((p) => [p.name, ...(p.aliases || [])].some((n) => compact(n).includes(key))).slice(0, MAX_KNOWN);
}

export default function PlaceSearch({
  id, place, known, chosenIds, placeholder, invalid, describedBy, onPick, onClear, forExclude = false,
  suggestVenues = !forExclude, // 비어 있을 때 목적지(행사장)를 보여 줄지. 출발 위치에는 보여 주지 않는다
}) {
  const [text, setText] = useState(place ? place.name : "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [kakao, setKakao] = useState({ query: "", items: [], loading: false });
  const listId = `${id}-list`;

  // 바깥에서 장소가 정해지면(공유 링크로 채우기) 입력칸도 맞춘다. 선택이 풀릴 때는 입력 중인 글자를 그대로 둔다.
  useEffect(() => { if (place) setText(place.name); }, [place]);

  const knownHits = useMemo(() => matchKnown(known, text, suggestVenues), [known, text, suggestVenues]);

  // 카카오 검색은 입력이 멈추고 0.3초 뒤에, 두 글자부터. 선택한 상태에서는 부르지 않는다.
  useEffect(() => {
    const q = text.trim();
    if (forExclude || !open || place || compact(q).length < 2) {
      setKakao({ query: "", items: [], loading: false });
      return undefined;
    }
    setKakao((k) => ({ ...k, loading: true }));
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/place-search?q=${encodeURIComponent(q)}`, { signal: ctrl.signal });
        const data = res.ok ? await res.json() : { kakao: [] };
        setKakao({ query: q, items: data.kakao || [], loading: false });
      } catch (e) {
        if (e.name !== "AbortError") setKakao({ query: q, items: [], loading: false });
      }
    }, 300);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [text, open, place, forExclude]);

  const options = [...knownHits.map((p) => ({ p, from: "known" })), ...kakao.items.map((p) => ({ p, from: "kakao" }))];
  const disabled = (p) => p.id !== place?.id && chosenIds.includes(p.id);

  function pick(p) {
    if (disabled(p)) return;
    setText(forExclude ? "" : p.name);
    setOpen(false);
    setActive(-1);
    onPick(p);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (!options.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + options.length) % options.length);
    } else if (e.key === "Enter" && open && active >= 0 && options[active]) {
      e.preventDefault(); // 코스 만들기(폼 제출) 대신 장소를 고른다
      pick(options[active].p);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    }
  }

  const option = ({ p, from }, i) => (
    <li
      key={`${from}-${p.id}`}
      id={`${listId}-${i}`}
      role="option"
      aria-selected={i === active}
      aria-disabled={disabled(p) || undefined}
      className={i === active ? "active" : undefined}
      onMouseDown={(e) => e.preventDefault()} // 입력칸이 포커스를 잃어 목록이 먼저 닫히지 않게
      onClick={() => pick(p)}
    >
      <span className="place-name">{p.name}</span>
      <span className="place-meta">{`${CATEGORY_KO[p.category] || "기타"} · ${p.area}`}</span>
    </li>
  );

  const showList = open && (options.length > 0 || kakao.loading || compact(text).length >= 2);
  return (
    <div className="place-search">
      <input
        id={id}
        className="must-place"
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(-1);
          if (place) onClear();
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {place ? (
        <button type="button" className="place-clear" aria-label="고른 장소 지우기" onClick={() => { setText(""); onClear(); }}>×</button>
      ) : null}
      <ul id={listId} role="listbox" className="place-list" hidden={!showList}>
        {knownHits.length ? <li role="presentation" className="place-group">{compact(text) ? "등록된 장소" : "목적지"}</li> : null}
        {knownHits.map((p, i) => option({ p, from: "known" }, i))}
        {kakao.items.length ? <li role="presentation" className="place-group">광주의 다른 장소 (카카오 검색)</li> : null}
        {kakao.items.map((p, i) => option({ p, from: "kakao" }, knownHits.length + i))}
        {kakao.loading ? <li role="presentation" className="place-note">검색 중…</li> : null}
        {!kakao.loading && !options.length && compact(text).length >= 2 ? (
          <li role="presentation" className="place-note">찾는 장소가 없습니다. 이름을 바꿔 검색해 보세요.</li>
        ) : null}
      </ul>
    </div>
  );
}

import { useEffect, useState } from "react";
import Header from "../components/Header.jsx";
import { PLANNER_KO, adminFetch, adminToken, askAdminToken, formatTime } from "../common.js";

const ROWS = [
  ["courses", "코스 수", (v) => `${v}개`],
  ["avg_places", "평균 장소 수", (v) => `${v.toFixed(1)}곳`],
  ["avg_ai_places", "평균 AI 추천 수", (v) => `${v.toFixed(1)}곳`],
  ["avg_travel_min", "평균 이동시간", (v) => `${Math.round(v)}분`],
  ["avg_local_commerce_ratio", "지역상권 비율", (v) => `${Math.round(v * 100)}%`],
  ["avg_score", "평균 코스 점수", (v) => v.toFixed(2)],
];

function Tiles({ stats }) {
  const ai = Object.values(stats.by_planner);
  const total = ai.reduce((n, p) => n + p.courses, 0);
  const localRatio = total ? ai.reduce((n, p) => n + p.avg_local_commerce_ratio * p.courses, 0) / total : null;
  const tiles = [
    ["생성된 코스", `${stats.courses}`, "개"],
    ["평균 지역상권 비율", localRatio === null ? "–" : `${Math.round(localRatio * 100)}`, localRatio === null ? "" : "%"],
    ["평균 별점", stats.avg_rating === null ? "–" : stats.avg_rating.toFixed(1), stats.avg_rating === null ? "" : " / 5"],
    ["받은 평가", `${stats.feedback}`, "건"],
  ];
  return tiles.map(([label, value, unit]) => (
    <li className="panel tile" key={label}>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}{unit ? <small>{unit}</small> : null}</span>
    </li>
  ));
}

function Planners({ stats }) {
  const names = Object.keys(stats.by_planner).sort();
  if (!names.length) return <caption className="muted small">아직 생성된 코스가 없습니다.</caption>;
  return (
    <>
      <thead>
        <tr>
          <th>지표</th>
          {names.map((n) => <th className="num" key={n}>{PLANNER_KO[n] || n}</th>)}
        </tr>
      </thead>
      <tbody>
        {ROWS.map(([key, label, fmt]) => (
          <tr key={key}>
            <th>{label}</th>
            {names.map((n) => <td className="num" key={n}>{fmt(stats.by_planner[n][key])}</td>)}
          </tr>
        ))}
      </tbody>
    </>
  );
}

function TopPlaces({ stats }) {
  if (!stats.top_places.length) return <li className="muted small">아직 추천 기록이 없습니다.</li>;
  const max = stats.top_places[0].count;
  const totalAi = stats.top_places.reduce((n, p) => n + p.count, 0);
  return stats.top_places.map((p) => (
    <li tabIndex={0} key={p.name}>
      <span className="bar-label">{p.name}</span>
      <span className="bar-track"><span className="bar" style={{ width: `${(p.count / max) * 100}%` }} /></span>
      <span className="bar-value">{`${p.count}회`}</span>
      <span className="tip">{`${p.name} · ${p.count}회 추천 (상위 10곳 추천의 ${Math.round((p.count / totalAi) * 100)}%)`}</span>
    </li>
  ));
}

function RecentRows({ items }) {
  if (!items.length) {
    return <tr><td className="muted small" colSpan={6}>아직 생성된 코스가 없습니다.</td></tr>;
  }
  return items.map((c) => {
    const href = `/?course=${encodeURIComponent(c.id)}`;
    return (
      <tr key={c.id} onClick={(e) => { if (e.target.tagName !== "A") location.href = href; }}>
        <td className="nowrap muted">{formatTime(c.created_at)}</td>
        <td className="query"><a href={href} title={c.query}>{c.query}</a></td>
        <td className="nowrap">{PLANNER_KO[c.planner] || c.planner}</td>
        <td className="num">{`${c.n_places}곳`}</td>
        <td className="num">{`${Math.round(c.local_commerce_ratio * 100)}%`}</td>
        <td className="num">{c.score.toFixed(2)}</td>
      </tr>
    );
  });
}

function Feedback({ feedback }) {
  if (feedback === null) return null;
  if (!feedback.length) return <li className="muted small">아직 한줄평이 없습니다.</li>;
  return feedback.map((f, i) => (
    <li key={i}>
      <div>{`“${f.comment}”`}</div>
      <div className="muted small">
        {`${"★".repeat(f.rating)}${"☆".repeat(5 - f.rating)} · ${formatTime(f.created_at)} · `}
        <a href={`/?course=${encodeURIComponent(f.course_id)}`}>코스 보기</a>
      </div>
    </li>
  ));
}

export default function StatsPage() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [locked, setLocked] = useState(false); // 관리자 토큰이 없거나 틀렸다
  const [updated, setUpdated] = useState("");
  const [loading, setLoading] = useState(false);

  // 실증 통계는 관리자 전용. 토큰이 없거나 틀리면(401) 잠긴 화면에서 토큰을 입력받는다.
  async function load() {
    setLoading(true);
    try {
      const res = await adminFetch("/api/stats", {}, false);
      if (res.status === 401) {
        setLocked(true);
        return;
      }
      const [s, r, f] = await Promise.all([
        res.json(),
        adminFetch("/api/courses?limit=10", {}, false).then((x) => x.json()),
        adminFetch("/api/admin/feedback?limit=20", {}, false).then((x) => x.json()),
      ]);
      setLocked(false);
      setStats(s);
      setRecent(r);
      setFeedback(f.filter((x) => x.comment));
      setUpdated(`(${new Date().toLocaleTimeString("ko-KR")} 기준)`);
    } catch {
      setLocked(true);
    } finally {
      setLoading(false);
    }
  }

  async function askToken() {
    const token = await askAdminToken();
    if (token) { adminToken.set(token); load(); }
  }

  useEffect(() => { load(); }, []);

  return (
    <>
      <Header tagline="실증 통계" current="stats" />

      <main className="page">
        {locked ? (
          <section className="panel">
            <p className="muted small">실증 통계는 관리자만 볼 수 있습니다.</p>
            <button type="button" className="inline secondary" onClick={askToken}>관리자 토큰 입력</button>
          </section>
        ) : (
        <>
        <section className="toolbar">
          <p className="muted small">생성된 모든 코스를 집계합니다. <span id="updated">{updated}</span></p>
          <button type="button" id="refresh" className="inline secondary" disabled={loading} onClick={load}>새로고침</button>
        </section>

        <ul id="tiles" className="tiles" aria-live="polite">
          {stats ? <Tiles stats={stats} /> : null}
        </ul>

        <div className="dash">
          <section className="panel dash-compare">
            <h2>코스 생성기 비교</h2>
            <p className="muted small">두 생성기가 만든 코스의 평균. 지역상권 비율은 AI 추천 장소 중 전통시장·골목상권·로컬카페의 비율입니다.</p>
            <div className="table-wrap">
              <table id="planners">{stats ? <Planners stats={stats} /> : null}</table>
            </div>
          </section>

          <section className="panel dash-top">
            <h2>AI가 많이 추천한 장소</h2>
            <p className="muted small">코스에 AI 추천으로 들어간 횟수 (상위 10곳)</p>
            <ol id="top-places" className="bars">
              {stats ? <TopPlaces stats={stats} /> : null}
            </ol>
          </section>

          <section className="panel dash-recent">
            <h2>최근 생성된 코스</h2>
            <div className="table-wrap">
              <table id="recent" className="clickable">
                <thead>
                  <tr>
                    <th>생성 시각</th><th>요청 문장</th><th>생성기</th>
                    <th className="num">장소</th><th className="num">지역상권</th><th className="num">점수</th>
                  </tr>
                </thead>
                <tbody>
                  {recent ? <RecentRows items={recent} /> : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel dash-feedback">
            <h2>최근 한줄평</h2>
            <ul id="feedback" className="list">
              <Feedback feedback={feedback} />
            </ul>
          </section>
        </div>
        </>
        )}
      </main>
    </>
  );
}

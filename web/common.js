// 여러 화면이 같이 쓰는 도우미.
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const CATEGORY_KO = {
  sight: "명소·산책", culture: "문화·전시", market: "전통시장", food: "식당",
  cafe: "카페·디저트", shop: "상점가", night: "야간 콘텐츠", venue: "행사장",
};

const PLANNER_KO = { greedy: "그리디 (Phase 1)", ortools: "OR-Tools (Phase 2)" };

// 관리자 토큰은 탭을 닫으면 사라지도록 sessionStorage 에 둔다. 저장소를 못 쓰는 환경에서도 동작해야 한다.
const adminToken = {
  get() { try { return sessionStorage.getItem("routefit-admin-token") || ""; } catch { return ""; } },
  set(v) { try { sessionStorage.setItem("routefit-admin-token", v); } catch { /* 무시 */ } },
};

const FIELD_KO = {
  id: "id", kind: "구분", name: "이름", category: "유형", area: "지역", lat: "위도", lng: "경도",
  open: "여는 시각", close: "닫는 시각", closed_days: "휴무 요일", stay_min: "머무는 시간", cost: "예상 지출",
  gwangju_ness: "광주다움", stay_inducement: "체류 유도성", commerce_link: "상권 연계성",
  rater: "채점자", rating: "별점", comment: "한줄평",
};

// 서버의 422 응답(pydantic 오류 목록)을 사람이 읽을 문장으로.
function errorText(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => {
      const field = (e.loc || []).filter((x) => x !== "body" && typeof x === "string").pop();
      const msg = String(e.msg).replace(/^Value error, /, "");
      return field ? `${FIELD_KO[field] || field}: ${msg}` : msg;
    }).join(" / ");
  }
  return fallback;
}

// 관리자 API 호출. 401 이면 토큰을 물어보고 한 번 다시 시도한다.
async function adminFetch(url, options = {}, retry = true) {
  const headers = { ...(options.headers || {}), "X-Admin-Token": adminToken.get() };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 && retry) {
    const token = prompt("관리자 토큰을 입력하세요 (ROUTEFIT_ADMIN_TOKEN)");
    if (token) {
      adminToken.set(token);
      return adminFetch(url, options, false);
    }
  }
  return res;
}

function formatTime(iso) {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

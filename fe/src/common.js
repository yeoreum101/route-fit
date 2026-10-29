// 여러 화면이 같이 쓰는 도우미. (web/common.js)

export const CATEGORY_KO = {
  sight: "명소·산책", culture: "문화·전시", market: "전통시장", food: "식당",
  cafe: "카페·디저트", shop: "상점가", night: "야간 콘텐츠", venue: "행사장",
};

// 화면에는 쉬운 이름을, 괄호 안에는 발표·보고서에서 쓰는 알고리즘 이름을 둔다.
export const PLANNER_KO = { greedy: "기본 추천 (그리디)", ortools: "최적화 추천 (OR-Tools)" };

// 관리자 토큰은 탭을 닫으면 사라지도록 sessionStorage 에 둔다. 저장소를 못 쓰는 환경에서도 동작해야 한다.
export const adminToken = {
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
export function errorText(data, fallback) {
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

// 관리자 토큰 입력 창. 브라우저 기본 prompt() 는 입력값이 그대로 보여서, 비밀번호 칸이 있는 <dialog> 를 띄운다.
// 확인하면 입력값, 취소·Esc 면 null.
export function askAdminToken() {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "token-dialog";
    dialog.innerHTML = `
      <form method="dialog">
        <label for="admin-token-input">관리자 토큰</label>
        <input id="admin-token-input" type="password" autocomplete="off" spellcheck="false" required>
        <div class="token-actions">
          <button type="button" class="secondary" value="cancel">취소</button>
          <button type="submit" value="ok">확인</button>
        </div>
      </form>`;
    const input = dialog.querySelector("input");
    dialog.querySelector('button[value="cancel"]').addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      const token = dialog.returnValue === "ok" ? input.value.trim() : "";
      dialog.remove();
      resolve(token || null);
    });
    document.body.append(dialog);
    dialog.showModal();
    input.focus();
  });
}

// 관리자 API 호출. 401 이면 토큰을 물어보고 한 번 다시 시도한다.
export async function adminFetch(url, options = {}, retry = true) {
  const headers = { ...(options.headers || {}), "X-Admin-Token": adminToken.get() };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 && retry) {
    const token = await askAdminToken();
    if (token) {
      adminToken.set(token);
      return adminFetch(url, options, false);
    }
  }
  return res;
}

export function formatTime(iso) {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// 화면 밖에 있는지 (지도·코스로 스크롤할지 정할 때)
export const offScreen = (node) => {
  const box = node.getBoundingClientRect();
  return box.top < 0 || box.bottom > window.innerHeight;
};

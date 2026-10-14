// 코스 지도. 카카오맵 JavaScript 키(/api/config)가 있고 이 주소에서 쓸 수 있으면 카카오맵을, 아니면 OpenStreetMap(Leaflet)을 쓴다.
// app.js 는 아래 MapView 메서드만 쓴다. 지도 엔진을 바꿀 때는 이 파일만 고치면 된다.
//
//   clear()                         그린 것을 모두 지운다
//   drawRoute(points)               방문 순서를 잇는 선. points = [[lat, lng], ...]
//   addPin(stop, { label, title, tooltip, onClick })  번호 핀. 돌려주는 값: { pinEl, setFront(bool), showTooltip(), hideTooltip() }
//   fitAll(points, animate)         모든 점이 보이게
//   focus(lat, lng, onDone)         그 점을 가운데로 옮기고 가깝게 본다. 다 움직이면 onDone
//   addControl(button)              지도 오른쪽 위에 버튼을 올린다
//   name                            "kakao" | "osm"

const CLOSE_ZOOM = { osm: 16, kakao: 3 }; // 장소를 볼 때의 확대 정도 (카카오는 숫자가 작을수록 가깝다)
const ROUTE_STYLE = { casing: "#fff", line: "#3b6ace" };

function pinElement(kind, label) {
  const pin = el("div", `pin ${kind}`, String(label));
  return pin;
}

// ---------- OpenStreetMap (Leaflet) ----------

function osmMapView(container) {
  const map = L.map(container).setView([35.1487, 126.9165], 14);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  const layer = L.layerGroup().addTo(map);

  return {
    name: "osm",
    clear: () => layer.clearLayers(),
    drawRoute(points) {
      L.polyline(points, { color: ROUTE_STYLE.casing, weight: 7, opacity: 0.9 }).addTo(layer);
      L.polyline(points, { color: ROUTE_STYLE.line, weight: 4, opacity: 0.95, dashArray: "8 6" }).addTo(layer);
    },
    addPin(stop, { label, title, tooltip, onClick }) {
      const icon = L.divIcon({ className: "pin-wrap", html: pinElement(stop.kind, label).outerHTML, iconSize: [26, 26] });
      const marker = L.marker([stop.lat, stop.lng], { icon, title }).bindTooltip(tooltip).on("click", onClick).addTo(layer);
      return {
        get pinEl() { return marker.getElement()?.querySelector(".pin"); },
        setFront: (front) => marker.setZIndexOffset(front ? 1000 : 0),
        showTooltip: () => marker.openTooltip(),
        hideTooltip: () => marker.closeTooltip(),
      };
    },
    fitAll(points, animate) {
      if (!points.length) return;
      const opts = { padding: [40, 40], maxZoom: CLOSE_ZOOM.osm };
      animate ? map.flyToBounds(points, { ...opts, duration: 0.5 }) : map.fitBounds(points, opts);
    },
    focus(lat, lng, onDone) {
      map.flyTo([lat, lng], Math.max(map.getZoom(), CLOSE_ZOOM.osm), { duration: 0.5 });
      map.once("moveend", onDone); // 지도가 다 움직인 뒤에 강조해야 보인다
    },
    addControl(button) {
      const Control = L.Control.extend({ onAdd: () => button });
      L.DomEvent.disableClickPropagation(button);
      new Control({ position: "topright" }).addTo(map);
    },
  };
}

// ---------- 카카오맵 ----------

// SDK 를 불러온다. 키가 틀렸거나 이 주소가 카카오 콘솔에 등록되지 않았으면(401) 실패한다.
function loadKakaoSdk(key) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`;
    script.onerror = () => reject(new Error("카카오맵 SDK 를 불러오지 못했습니다 (키 또는 등록된 사이트 도메인 확인)"));
    script.onload = () => {
      if (!window.kakao?.maps?.load) return reject(new Error("카카오맵 SDK 응답이 올바르지 않습니다"));
      kakao.maps.load(() => resolve(kakao.maps));
    };
    document.head.append(script);
    setTimeout(() => reject(new Error("카카오맵 SDK 응답 시간 초과")), 8000);
  });
}

function kakaoMapView(container, maps) {
  const map = new maps.Map(container, { center: new maps.LatLng(35.1487, 126.9165), level: 5 });
  map.addControl(new maps.ZoomControl(), maps.ControlPosition.LEFT);
  let drawn = []; // 지도에 올린 선·오버레이

  // 지도 칸 크기가 바뀌면(화면 폭 변화, sticky 등) 카카오맵은 직접 다시 맞춰 줘야 한다.
  new ResizeObserver(() => map.relayout()).observe(container);

  const latLng = ([lat, lng]) => new maps.LatLng(lat, lng);
  const show = (obj) => { obj.setMap(map); drawn.push(obj); return obj; };

  return {
    name: "kakao",
    clear() {
      for (const obj of drawn) obj.setMap(null);
      drawn = [];
    },
    drawRoute(points) {
      const path = points.map(latLng);
      show(new maps.Polyline({ path, strokeWeight: 7, strokeColor: ROUTE_STYLE.casing, strokeOpacity: 0.9 }));
      show(new maps.Polyline({ path, strokeWeight: 4, strokeColor: ROUTE_STYLE.line, strokeOpacity: 0.95, strokeStyle: "shortdash" }));
    },
    addPin(stop, { label, title, tooltip, onClick }) {
      const position = latLng([stop.lat, stop.lng]);
      const wrap = el("div", "pin-wrap kakao-pin");
      const pin = pinElement(stop.kind, label);
      wrap.title = title;
      wrap.append(pin);
      wrap.addEventListener("click", onClick);
      const overlay = show(new maps.CustomOverlay({ position, content: wrap, xAnchor: 0.5, yAnchor: 0.5, zIndex: 2, clickable: true }));

      // 이름 말풍선: 마우스를 올리거나 코스에서 고르면 보인다
      const tip = new maps.CustomOverlay({ position, content: el("div", "kakao-tip", tooltip), xAnchor: 0.5, yAnchor: 1.9, zIndex: 3 });
      drawn.push(tip);
      let pinned = false;
      wrap.addEventListener("mouseenter", () => tip.setMap(map));
      wrap.addEventListener("mouseleave", () => { if (!pinned) tip.setMap(null); });

      return {
        pinEl: pin,
        setFront: (front) => overlay.setZIndex(front ? 10 : 2),
        showTooltip: () => { pinned = true; tip.setMap(map); },
        hideTooltip: () => { pinned = false; tip.setMap(null); },
      };
    },
    fitAll(points) {
      if (!points.length) return;
      const bounds = new maps.LatLngBounds();
      for (const p of points) bounds.extend(latLng(p));
      map.setBounds(bounds, 40, 40, 40, 40);
      if (map.getLevel() < CLOSE_ZOOM.kakao) map.setLevel(CLOSE_ZOOM.kakao); // 한 곳뿐이면 너무 가까워지지 않게
    },
    focus(lat, lng, onDone) {
      if (map.getLevel() > CLOSE_ZOOM.kakao) map.setLevel(CLOSE_ZOOM.kakao);
      map.panTo(latLng([lat, lng]));
      // 다 움직이면 idle 이 온다. 이미 그 자리라 움직이지 않으면 오지 않으므로 잠시 뒤에도 한 번 부른다.
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        maps.event.removeListener(map, "idle", finish);
        onDone();
      };
      maps.event.addListener(map, "idle", finish);
      setTimeout(finish, 700);
    },
    addControl(button) {
      button.classList.add("kakao-control");
      container.append(button);
    },
  };
}

// 쓸 수 있는 지도를 만든다. 카카오맵이 실패하면 조용히 OpenStreetMap 으로 바꾼다.
async function createMapView(container) {
  let key = null;
  try {
    key = (await (await fetch("/api/config")).json()).kakao_js_key;
  } catch { /* 설정을 못 받으면 OSM */ }
  if (key) {
    try {
      return kakaoMapView(container, await loadKakaoSdk(key));
    } catch (e) {
      console.warn(`${e.message} → OpenStreetMap 으로 표시합니다.`);
    }
  }
  return osmMapView(container);
}

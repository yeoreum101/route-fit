import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { createMapView } from "../map/mapView.js";
import { offScreen } from "../common.js";

// 코스 지도. 지도 엔진(카카오맵 / Leaflet)은 React 밖의 mapView.js 가 다루고, 여기서는 코스가 바뀔 때 다시 그린다.
// 코스의 번호·이름을 누르면(focusStop) 그 장소를 가운데로 옮기고, 핀을 누르면 onPinClick 으로 코스에 알린다.

// 핀을 잠깐 커졌다 돌아오게 해서 어디인지 알려 준다.
function flashPin(marker) {
  const pin = marker?.pinEl;
  if (!pin) return;
  pin.classList.remove("flash");
  void pin.offsetWidth; // 같은 핀을 연달아 눌러도 처음부터 다시 움직이게
  pin.classList.add("flash");
}

const CourseMap = forwardRef(function CourseMap({ course, activeOrder, onPinClick, onShowRoute }, ref) {
  const containerRef = useRef(null);
  const state = useRef({ ready: null, view: null, routeButton: null, markers: {}, stops: {}, points: [] });
  const handlers = useRef({ onPinClick, onShowRoute });
  handlers.current = { onPinClick, onShowRoute };

  // 지도는 만들어지는 데 시간이 걸리므로 그리기 전에 기다린다(ready).
  useEffect(() => {
    const st = state.current;
    const routeButton = document.createElement("button"); // 지도 오른쪽 위. 코스를 그리면 보인다
    routeButton.className = "route-control";
    routeButton.textContent = "전체 경로 보기";
    routeButton.type = "button";
    routeButton.id = "show-route";
    routeButton.hidden = true;
    routeButton.addEventListener("click", () => handlers.current.onShowRoute());
    st.routeButton = routeButton;

    let cancelled = false;
    st.ready = createMapView(containerRef.current).then((view) => {
      if (cancelled) {
        view.destroy();
        return view;
      }
      st.view = view;
      view.addControl(routeButton);
      return view;
    });
    return () => {
      cancelled = true;
      if (st.view) st.view.destroy();
      st.view = null;
      st.markers = {};
    };
  }, []);

  useEffect(() => {
    if (!course) return undefined;
    const st = state.current;
    let cancelled = false;
    st.ready.then((view) => {
      if (cancelled || st.view !== view) return;
      view.clear();
      st.markers = {};
      const points = (st.points = course.stops.map((s) => [s.lat, s.lng]));
      st.stops = Object.fromEntries(course.stops.map((s) => [s.order, s]));
      st.routeButton.hidden = !points.length;
      // 지도 위에서 잘 보이도록 흰 테두리 위에 파란 점선을 긋는다. 점선은 실제 도로가 아니라 방문 순서를 잇는 선이라는 뜻이다.
      view.drawRoute(points);
      for (const s of course.stops) {
        st.markers[s.order] = view.addPin(s, {
          label: s.order,
          title: `${s.order}번 ${s.name} 코스에서 보기`,
          tooltip: `${s.start} ${s.name}`,
          onClick: () => handlers.current.onPinClick(s.order),
        });
      }
      view.fitAll(points, false);
    });
    return () => { cancelled = true; };
  }, [course]);

  // 고른 장소의 핀을 앞으로 올린다
  useEffect(() => {
    for (const [k, m] of Object.entries(state.current.markers)) m.setFront(Number(k) === activeOrder);
  }, [activeOrder, course]);

  useImperativeHandle(ref, () => ({
    // 성공하면 true
    focusStop(order) {
      const st = state.current;
      const marker = st.markers[order];
      if (!marker || !st.view) return false;
      for (const m of Object.values(st.markers)) m.hideTooltip();
      const s = st.stops[order];
      st.view.focus(s.lat, s.lng, () => flashPin(marker)); // 지도가 다 움직인 뒤에 강조해야 보인다
      marker.showTooltip();
      // 좁은 화면에서는 지도가 코스 아래에 있으므로 지도가 보이게 내려 준다
      if (offScreen(containerRef.current)) containerRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
      return true;
    },
    // 코스 전체가 지도에 들어오게 한다.
    showWholeRoute() {
      const st = state.current;
      if (!st.points.length || !st.view) return;
      for (const m of Object.values(st.markers)) m.hideTooltip();
      st.view.fitAll(st.points, true);
      if (offScreen(containerRef.current)) containerRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    },
  }), []);

  return (
    <section className="panel map-panel">
      <div id="map" ref={containerRef} />
    </section>
  );
});

export default CourseMap;

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { createMapView } from "../map/mapView.js";

// 좌표 고르기 지도. 지도를 클릭하면 onPick(lat, lng) 이 불린다.
// 지도 엔진은 코스 지도와 같은 mapView.js 가 고른다(카카오맵, 안 되면 OpenStreetMap).
// 지도는 만들어지는 데 시간이 걸리므로, 그 전에 온 호출은 지도가 준비되면 이어서 한다.
const MiniMap = forwardRef(function MiniMap({ onPick }, ref) {
  const containerRef = useRef(null);
  const ready = useRef(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    let cancelled = false;
    let view = null;
    ready.current = createMapView(containerRef.current).then((v) => {
      if (cancelled) {
        v.destroy(); // 만들어지는 사이에 화면이 사라졌다
        return v;
      }
      view = v;
      v.onMapClick((lat, lng) => pickRef.current(lat, lng));
      return v;
    });
    return () => {
      cancelled = true;
      ready.current = null;
      if (view) view.destroy();
    };
  }, []);

  const later = (fn) => ready.current?.then((v) => fn(v));
  useImperativeHandle(ref, () => ({
    setPoint: (lat, lng, pan = true) => later((v) => v.setMarker(lat, lng, pan)),
    removeMarker: () => later((v) => v.removeMarker()),
    invalidateSize: () => later((v) => v.relayout()), // 숨겨져 있던 지도는 크기를 다시 재야 한다
  }), []);

  return <div id="mini-map" className="span-3" ref={containerRef} />;
});

export default MiniMap;

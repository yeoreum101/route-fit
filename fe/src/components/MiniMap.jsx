import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

// 번들러를 거치면 Leaflet 이 기본 마커 그림 경로를 못 찾으므로 직접 알려 준다.
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({ iconUrl: markerIcon, iconRetinaUrl: markerIcon2x, shadowUrl: markerShadow });

// 좌표 고르기 지도. 지도를 클릭하면 onPick(lat, lng) 이 불린다.
const MiniMap = forwardRef(function MiniMap({ onPick }, ref) {
  const containerRef = useRef(null);
  const api = useRef(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    const map = L.map(containerRef.current).setView([35.1487, 126.9165], 15);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    const marker = L.marker([35.1487, 126.9165]);

    map.on("click", (e) => pickRef.current(e.latlng.lat, e.latlng.lng));
    api.current = {
      setPoint(lat, lng, pan = true) {
        marker.setLatLng([lat, lng]).addTo(map);
        if (pan) map.setView([lat, lng], Math.max(map.getZoom(), 16));
      },
      removeMarker: () => marker.remove(),
      invalidateSize: () => map.invalidateSize(), // 숨겨져 있던 지도는 크기를 다시 재야 한다
    };
    return () => {
      api.current = null;
      map.remove();
    };
  }, []);

  useImperativeHandle(ref, () => ({
    setPoint: (...args) => api.current?.setPoint(...args),
    removeMarker: () => api.current?.removeMarker(),
    invalidateSize: () => api.current?.invalidateSize(),
  }), []);

  return <div id="mini-map" className="span-3" ref={containerRef} />;
});

export default MiniMap;

const NAV = [
  ["plan", "/", "코스 만들기"],
  ["stats", "/stats.html", "실증 통계"],
  ["admin", "/admin.html", "장소 관리"],
];

export default function Header({ tagline, current }) {
  return (
    <header>
      {/* 로고를 누르면 입력칸·코스가 빈 첫 화면을 새로 연다(공유 링크의 ?course= 도 떼어 낸다) */}
      <h1><a href="/" className="home" title="처음 화면으로">Route-Fit</a></h1>
      <p>{tagline}</p>
      <nav>
        {NAV.map(([key, href, label]) => (
          <a key={key} href={href} aria-current={key === current ? "page" : undefined}>{label}</a>
        ))}
      </nav>
    </header>
  );
}

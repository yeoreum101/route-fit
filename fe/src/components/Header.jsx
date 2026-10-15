const NAV = [
  ["plan", "/", "코스 만들기"],
  ["stats", "/stats.html", "실증 통계"],
  ["admin", "/admin.html", "장소 관리"],
];

export default function Header({ tagline, current }) {
  return (
    <header>
      <h1>Route-Fit</h1>
      <p>{tagline}</p>
      <nav>
        {NAV.map(([key, href, label]) => (
          <a key={key} href={href} aria-current={key === current ? "page" : undefined}>{label}</a>
        ))}
      </nav>
    </header>
  );
}

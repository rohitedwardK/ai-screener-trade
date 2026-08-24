import { Link, Route, Routes, useLocation } from "react-router-dom";
import LiveMarketDashboard from "./pages/LiveMarketDashboard";
import IndexDetail from "./pages/IndexDetail";

function NavBar() {
  const { pathname } = useLocation();
  return (
    <header className="border-b border-border bg-bg-surface">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <Link to="/" className="flex items-center gap-2">
          <span className="text-lg font-semibold text-fg">Live Market</span>
          <span className="badge badge-blue">indices</span>
        </Link>
        <nav className="flex items-center gap-2 text-sm">
          <Link
            to="/"
            className={`btn ${pathname === "/" ? "btn-primary" : ""}`}
          >
            Dashboard
          </Link>
          <a
            className="btn"
            href="http://127.0.0.1:8001/docs"
            target="_blank"
            rel="noreferrer"
          >
            API
          </a>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t border-border bg-bg-surface">
      <div className="mx-auto max-w-7xl px-4 py-3 text-xs text-fg-subtle">
        Research and decision-support only. Not financial advice.
      </div>
    </footer>
  );
}

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <NavBar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Routes>
          <Route path="/" element={<LiveMarketDashboard />} />
          <Route path="/index/:symbol" element={<IndexDetail />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}

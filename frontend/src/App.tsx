import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Agents } from "@/pages/Agents";
import { Dashboard } from "@/pages/Dashboard";
import { IndexAnalysis } from "@/pages/IndexAnalysis";
import { LiveAnalysis } from "@/pages/LiveAnalysis";
import { MethodAnalysis } from "@/pages/MethodAnalysis";
import { Screener } from "@/pages/Screener";
import { StockDetail } from "@/pages/StockDetail";
import { useAppMode } from "@/lib/appMode";

/**
 * The default route ("/") swaps between the Historical Dashboard and the
 * Live Analysis dashboard depending on the current app mode. All other
 * routes remain individually addressable so deep-links keep working when
 * switching modes.
 */
function HomeForCurrentMode() {
  const mode = useAppMode((s) => s.mode);
  return mode === "LIVE" ? <LiveAnalysis /> : <Dashboard />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomeForCurrentMode />} />
        <Route path="screener" element={<Screener />} />
        <Route path="stock/:symbol" element={<StockDetail />} />
        <Route path="indices" element={<IndexAnalysis />} />
        <Route path="indices/:symbol" element={<IndexAnalysis />} />
        <Route path="live" element={<LiveAnalysis />} />
        <Route path="method-analysis" element={<MethodAnalysis />} />
        <Route path="agents" element={<Agents />} />
      </Route>
    </Routes>
  );
}

import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/pages/Dashboard";
import { IndexAnalysis } from "@/pages/IndexAnalysis";
import { PaperIndexTrading } from "@/pages/PaperIndexTrading";
import { PaperTrading } from "@/pages/PaperTrading";
import { Screener } from "@/pages/Screener";
import { StockDetail } from "@/pages/StockDetail";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="screener" element={<Screener />} />
        <Route path="stock/:symbol" element={<StockDetail />} />
        <Route path="paper-trading" element={<PaperTrading />} />
        <Route path="indices" element={<IndexAnalysis />} />
        <Route path="indices/:symbol" element={<IndexAnalysis />} />
        <Route path="paper-index-trading" element={<PaperIndexTrading />} />
      </Route>
    </Routes>
  );
}

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCallback, useEffect, useState } from "react";

interface TradeLogEntry {
  order_id: string;
  ticker: string;
  side: string;
  shares: number;
  price: number;
  commission: number;
  sales_tax: number;
  fill_time: string | null;
}

interface DividendEntry {
  ticker: string;
  action_type: string;
  ex_date: string | null;
  value: number;
  currency: string;
}

interface TaxReport {
  year: number;
  total_sell_value: number;
  total_tax_paid: number;
  expected_pph_final_0_1_pct: number;
  total_commission: number;
  net_proceeds: number;
  sell_count: number;
}

export default function ReportsPage() {
  const [tradeLog, setTradeLog] = useState<TradeLogEntry[]>([]);
  const [dividends, setDividends] = useState<DividendEntry[]>([]);
  const [taxReport, setTaxReport] = useState<TaxReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [taxYear, setTaxYear] = useState(new Date().getFullYear());

  const fetchTradeLog = useCallback(async () => {
    try {
      const res = await fetch("/api/reports/trade-log?limit=50");
      if (res.ok) setTradeLog(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchDividends = useCallback(async () => {
    try {
      const res = await fetch("/api/reports/dividends?limit=50");
      if (res.ok) setDividends(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchTaxReport = useCallback(async (year: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/reports/tax/${year}`);
      if (res.ok) setTaxReport(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchTradeLog();
    fetchDividends();
    fetchTaxReport(taxYear);
  }, [fetchTradeLog, fetchDividends, fetchTaxReport, taxYear]);

  const formatIDR = (v: number | undefined | null) =>
    (v ?? 0).toLocaleString("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 0 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Laporan</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Pajak, dividen, trade log, dan statement
        </p>
      </div>

      {/* Tax Report */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Laporan Pajak Tahunan</CardTitle>
            <div className="flex gap-2 items-center">
              <input
                type="number"
                value={taxYear}
                onChange={(e) => setTaxYear(parseInt(e.target.value) || new Date().getFullYear())}
                min={2020}
                max={2030}
                className="w-24 px-2 py-1 rounded-md border border-input bg-background text-sm"
              />
              <button
                onClick={() => fetchTaxReport(taxYear)}
                disabled={loading}
                className="px-3 py-1 rounded-md bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
              >
                {loading ? "Memuat..." : "Generate"}
              </button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {taxReport ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">Total Sell Value</p>
                <p className="text-lg font-bold">Rp {formatIDR(taxReport.total_sell_value)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">PPh Final 0.1%</p>
                <p className="text-lg font-bold">Rp {formatIDR(taxReport.expected_pph_final_0_1_pct)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Tax Paid</p>
                <p className="text-lg font-bold">Rp {formatIDR(taxReport.total_tax_paid)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Net Proceeds</p>
                <p className="text-lg font-bold">Rp {formatIDR(taxReport.net_proceeds)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Jumlah Transaksi Sell</p>
                <p className="text-lg font-bold">{taxReport.sell_count}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Total Komisi</p>
                <p className="text-lg font-bold">Rp {formatIDR(taxReport.total_commission)}</p>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Belum ada data pajak.</p>
          )}
        </CardContent>
      </Card>

      {/* Trade Log */}
      <Card>
        <CardHeader><CardTitle>Trade Log (50 Terakhir)</CardTitle></CardHeader>
        <CardContent>
          {tradeLog.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="py-2 pr-4">Tanggal</th>
                    <th className="py-2 pr-4">Ticker</th>
                    <th className="py-2 pr-4">Side</th>
                    <th className="py-2 pr-4 text-right">Shares</th>
                    <th className="py-2 pr-4 text-right">Price</th>
                    <th className="py-2 pr-4 text-right">Value</th>
                    <th className="py-2 pr-4 text-right">Komisi</th>
                    <th className="py-2 pr-4 text-right">Pajak</th>
                  </tr>
                </thead>
                <tbody>
                  {tradeLog.map((t, i) => (
                    <tr key={i} className="border-b">
                      <td className="py-2 pr-4 text-xs">{t.fill_time?.slice(0, 19).replace("T", " ") || "-"}</td>
                      <td className="py-2 pr-4 font-medium">{t.ticker}</td>
                      <td className={`py-2 pr-4 ${t.side === "buy" ? "text-green-600" : "text-red-600"}`}>{t.side}</td>
                      <td className="py-2 pr-4 text-right">{t.shares}</td>
                      <td className="py-2 pr-4 text-right">{formatIDR(t.price)}</td>
                      <td className="py-2 pr-4 text-right">{formatIDR(t.shares * t.price)}</td>
                      <td className="py-2 pr-4 text-right">{formatIDR(t.commission)}</td>
                      <td className="py-2 pr-4 text-right">{formatIDR(t.sales_tax)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Belum ada transaksi.</p>
          )}
        </CardContent>
      </Card>

      {/* Dividends */}
      <Card>
        <CardHeader><CardTitle>Riwayat Dividen</CardTitle></CardHeader>
        <CardContent>
          {dividends.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="py-2 pr-4">Ticker</th>
                    <th className="py-2 pr-4">Ex Date</th>
                    <th className="py-2 pr-4 text-right">Value</th>
                    <th className="py-2 pr-4">Currency</th>
                  </tr>
                </thead>
                <tbody>
                  {dividends.map((d, i) => (
                    <tr key={i} className="border-b">
                      <td className="py-2 pr-4 font-medium">{d.ticker}</td>
                      <td className="py-2 pr-4 text-xs">{d.ex_date || "-"}</td>
                      <td className="py-2 pr-4 text-right">{d.value.toFixed(2)}</td>
                      <td className="py-2 pr-4">{d.currency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Belum ada riwayat dividen.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

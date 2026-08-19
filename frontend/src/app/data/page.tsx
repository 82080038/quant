"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Database, Activity, Clock, AlertCircle, RefreshCw, Search } from "lucide-react";

interface SourceHealth {
  source: string;
  status: string;
  last_success: string | null;
  last_error: string | null;
  last_error_msg: string | null;
  total_fetches: number;
  total_failures: number;
  updated_at: string | null;
}

interface Watermark {
  ticker: string;
  table_name: string;
  last_updated: string | null;
  row_count: number | null;
  source: string;
}

interface AuditEvent {
  id: number;
  event_type: string;
  event_payload: string | null;
  actor: string;
  created_at: string | null;
}

interface DataQuality {
  ticker: string;
  bars: number;
  score: number;
  action: string;
  anomalies: string[];
}

const SOURCE_LABELS: Record<string, string> = {
  yahoo_finance: "Yahoo Finance",
  idx_scraper: "IDX Scraper",
  bps: "BPS",
  bi: "Bank Indonesia",
  fred: "FRED",
  manual: "Manual",
  parquet_archive: "Parquet Archive",
  computed: "Computed (Internal)",
};

const TABLE_LABELS: Record<string, string> = {
  ohlcv: "OHLCV (Harga Saham)",
  corporate_actions: "Aksi Korporat",
  dividends: "Dividen",
  foreign_flow: "Aliran Asing",
  macro_data: "Data Makro",
  market_calendar: "Kalender Bursa",
  fundamental_data: "Data Fundamental",
  stock_personality: "Kepribadian Saham",
  instrument_master: "Master Instrumen",
  sector_master: "Master Sektor",
  scores: "Skor Analisis",
  technical_indicators: "Indikator Teknikal",
  relationship_matrix: "Matriks Relasi",
  fear_greed: "Fear & Greed Index",
  fx_rates: "Kurs Valuta",
  audit_log: "Audit Log",
  source_health: "Kesehatan Sumber",
  data_watermark: "Watermark Data",
};

export default function DataPage() {
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [watermarks, setWatermarks] = useState<Watermark[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [qualityTicker, setQualityTicker] = useState("");
  const [qualityResult, setQualityResult] = useState<DataQuality | null>(null);
  const [fetchTicker, setFetchTicker] = useState("");
  const [fetchPeriod, setFetchPeriod] = useState("3mo");
  const [fetchStatus, setFetchStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"sources" | "watermarks" | "audit" | "tools">("sources");

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [srcRes, wmRes, auditRes] = await Promise.all([
        fetch("/api/data/sources"),
        fetch("/api/data/watermarks"),
        fetch("/api/data/audit?limit=20"),
      ]);
      if (srcRes.ok) setSources(await srcRes.json());
      if (wmRes.ok) setWatermarks(await wmRes.json());
      if (auditRes.ok) {
        const auditData = await auditRes.json();
        setAuditEvents(auditData.events || []);
      }
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const checkQuality = async () => {
    if (!qualityTicker.trim()) return;
    setQualityResult(null);
    try {
      const res = await fetch(`/api/data/quality/${encodeURIComponent(qualityTicker)}`);
      if (res.ok) {
        setQualityResult(await res.json());
      } else {
        setQualityResult({
          ticker: qualityTicker,
          bars: 0,
          score: 0,
          action: "error",
          anomalies: ["Gagal mengambil data kualitas"],
        });
      }
    } catch {
      setQualityResult({
        ticker: qualityTicker,
        bars: 0,
        score: 0,
        action: "error",
        anomalies: ["Koneksi API gagal"],
      });
    }
  };

  const triggerFetch = async () => {
    if (!fetchTicker.trim()) return;
    setFetchStatus("Sedang fetch data...");
    try {
      const res = await fetch("/api/data/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: fetchTicker, period: fetchPeriod }),
      });
      if (res.ok) {
        const data = await res.json();
        setFetchStatus(
          `Berhasil: ${data.fetched} bar di-fetch, ${data.stored} disimpan, skor kualitas: ${data.quality_score?.toFixed(1)}`
        );
        loadData();
      } else {
        const err = await res.json();
        setFetchStatus(`Gagal: ${err.detail || "Unknown error"}`);
      }
    } catch {
      setFetchStatus("Koneksi API gagal");
    }
  };

  const fmtDate = (s: string | null) => {
    if (!s) return "-";
    const d = new Date(s);
    return d.toLocaleString("id-ID", {
      timeZone: "Asia/Jakarta",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const scoreColor = (score: number) => {
    if (score >= 80) return "text-green-600";
    if (score >= 50) return "text-yellow-600";
    return "text-red-600";
  };

  const statusBadge = (status: string) => {
    if (status === "ok")
      return "bg-green-100 text-green-700 px-2 py-0.5 rounded text-xs font-medium";
    return "bg-red-100 text-red-700 px-2 py-0.5 rounded text-xs font-medium";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Data &amp; Sumber</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Sumber data eksternal, watermark, audit log, dan kualitas data
          </p>
        </div>
        <button
          onClick={loadData}
          className="flex items-center gap-2 px-3 py-2 rounded-md border border-border text-sm hover:bg-accent"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {[
          { key: "sources" as const, label: "Sumber Data", icon: Database },
          { key: "watermarks" as const, label: "Watermark", icon: Clock },
          { key: "audit" as const, label: "Audit Log", icon: Activity },
          { key: "tools" as const, label: "Fetch &amp; Kualitas", icon: Search },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "border-primary text-primary font-medium"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Sources Tab */}
      {activeTab === "sources" && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Sumber Data Eksternal</CardTitle>
            </CardHeader>
            <CardContent>
              {sources.length === 0 ? (
                <p className="text-sm text-muted-foreground">Belum ada sumber data terdaftar.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="pb-2 pr-4">Sumber</th>
                        <th className="pb-2 pr-4">Status</th>
                        <th className="pb-2 pr-4">Fetches</th>
                        <th className="pb-2 pr-4">Failures</th>
                        <th className="pb-2 pr-4">Last Success</th>
                        <th className="pb-2 pr-4">Last Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((src) => (
                        <tr key={src.source} className="border-b border-border/50">
                          <td className="py-2 pr-4 font-medium">
                            {SOURCE_LABELS[src.source] || src.source}
                          </td>
                          <td className="py-2 pr-4">
                            <span className={statusBadge(src.status)}>{src.status}</span>
                          </td>
                          <td className="py-2 pr-4">{src.total_fetches}</td>
                          <td className="py-2 pr-4">{src.total_failures}</td>
                          <td className="py-2 pr-4 text-muted-foreground">
                            {fmtDate(src.last_success)}
                          </td>
                          <td className="py-2 pr-4 text-muted-foreground">
                            {fmtDate(src.last_error)}
                            {src.last_error_msg && (
                              <span className="block text-xs text-red-500 mt-0.5">
                                {src.last_error_msg}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Klasifikasi Data</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <h4 className="text-sm font-medium mb-1">Data Eksternal (Fetch)</h4>
                <p className="text-xs text-muted-foreground">
                  OHLCV, dividen, aksi korporat, data fundamental, aliran asing, data makro,
                  kalender bursa, kurs valuta — diambil dari Yahoo Finance, IDX, BPS, BI
                </p>
              </div>
              <div>
                <h4 className="text-sm font-medium mb-1">Data Internal (Computed)</h4>
                <p className="text-xs text-muted-foreground">
                  Skor analisis (6 engine), indikator teknikal, matriks relasi, Fear &amp; Greed
                  index, kepribadian saham — dihitung oleh aplikasi dari data OHLCV
                </p>
              </div>
              <div>
                <h4 className="text-sm font-medium mb-1">Data Infrastruktur</h4>
                <p className="text-xs text-muted-foreground">
                  Source health, watermark, audit log — diisi otomatis oleh sistem saat fetch/compute
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Watermarks Tab */}
      {activeTab === "watermarks" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Watermark Data — Staleness Tracking</CardTitle>
          </CardHeader>
          <CardContent>
            {watermarks.length === 0 ? (
              <p className="text-sm text-muted-foreground">Belum ada watermark.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-muted-foreground">
                      <th className="pb-2 pr-4">Tabel</th>
                      <th className="pb-2 pr-4">Ticker</th>
                      <th className="pb-2 pr-4">Rows</th>
                      <th className="pb-2 pr-4">Sumber</th>
                      <th className="pb-2 pr-4">Last Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watermarks.map((wm, i) => (
                      <tr key={i} className="border-b border-border/50">
                        <td className="py-2 pr-4 font-medium">
                          {TABLE_LABELS[wm.table_name] || wm.table_name}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">{wm.ticker}</td>
                        <td className="py-2 pr-4">
                          {wm.row_count != null ? wm.row_count.toLocaleString("id-ID") : "-"}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">
                          {SOURCE_LABELS[wm.source] || wm.source}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">
                          {fmtDate(wm.last_updated)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Audit Tab */}
      {activeTab === "audit" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Audit Log — Event Terbaru</CardTitle>
          </CardHeader>
          <CardContent>
            {auditEvents.length === 0 ? (
              <p className="text-sm text-muted-foreground">Belum ada event audit.</p>
            ) : (
              <div className="space-y-2">
                {auditEvents.map((evt) => (
                  <div
                    key={evt.id}
                    className="flex items-start gap-3 p-3 rounded-md border border-border/50"
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      <Activity className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{evt.event_type}</span>
                        <span className="text-xs text-muted-foreground">by {evt.actor}</span>
                      </div>
                      {evt.event_payload && (
                        <p className="text-xs text-muted-foreground mt-1 font-mono truncate">
                          {evt.event_payload}
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {fmtDate(evt.created_at)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tools Tab */}
      {activeTab === "tools" && (
        <div className="space-y-4">
          {/* Fetch Tool */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Fetch Manual dari Yahoo Finance</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Ambil data OHLCV terbaru untuk ticker tertentu langsung dari Yahoo Finance.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={fetchTicker}
                  onChange={(e) => setFetchTicker(e.target.value)}
                  placeholder="Ticker (e.g. BBCA.JK)"
                  className="flex-1 px-3 py-2 rounded-md border border-border text-sm bg-background"
                />
                <select
                  value={fetchPeriod}
                  onChange={(e) => setFetchPeriod(e.target.value)}
                  className="px-3 py-2 rounded-md border border-border text-sm bg-background"
                >
                  <option value="1mo">1 Bulan</option>
                  <option value="3mo">3 Bulan</option>
                  <option value="6mo">6 Bulan</option>
                  <option value="1y">1 Tahun</option>
                  <option value="max">Max</option>
                </select>
                <button
                  onClick={triggerFetch}
                  disabled={!fetchTicker.trim()}
                  className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
                >
                  Fetch
                </button>
              </div>
              {fetchStatus && (
                <div
                  className={`flex items-start gap-2 p-3 rounded-md text-sm ${
                    fetchStatus.startsWith("Berhasil")
                      ? "bg-green-50 text-green-700"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  {fetchStatus}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quality Check Tool */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cek Kualitas Data per Ticker</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Periksa kelengkapan dan kualitas data OHLCV untuk ticker tertentu.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={qualityTicker}
                  onChange={(e) => setQualityTicker(e.target.value)}
                  placeholder="Ticker (e.g. BBCA.JK)"
                  className="flex-1 px-3 py-2 rounded-md border border-border text-sm bg-background"
                />
                <button
                  onClick={checkQuality}
                  disabled={!qualityTicker.trim()}
                  className="px-4 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50"
                >
                  Cek
                </button>
              </div>
              {qualityResult && (
                <div className="p-4 rounded-md border border-border space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{qualityResult.ticker}</span>
                    <span className={`text-2xl font-bold ${scoreColor(qualityResult.score)}`}>
                      {qualityResult.score.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex gap-4 text-sm">
                    <span>
                      <span className="text-muted-foreground">Bars: </span>
                      {qualityResult.bars.toLocaleString("id-ID")}
                    </span>
                    <span>
                      <span className="text-muted-foreground">Action: </span>
                      <span className="font-medium">{qualityResult.action}</span>
                    </span>
                  </div>
                  {qualityResult.anomalies.length > 0 && (
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium">Anomali:</span>
                      <ul className="list-disc list-inside mt-1">
                        {qualityResult.anomalies.map((a, i) => (
                          <li key={i}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

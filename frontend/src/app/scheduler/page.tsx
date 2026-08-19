"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Clock,
  CheckCircle2,
  XCircle,
  Circle,
  RefreshCw,
  Calendar,
  GitBranch,
  AlertCircle,
  Zap,
  Timer,
  AlertTriangle,
  Database,
} from "lucide-react";

interface SchedulerTask {
  task_id: string;
  name: string;
  schedule: string;
  time_of_day: string;
  last_run: string | null;
  last_status: string;
  last_error: string;
  run_count: number;
  next_run_at: string | null;
  is_stale: boolean;
  data_dependencies: string[];
  data_ready: boolean;
  is_catchup: boolean;
  last_duration_seconds: number;
}

interface CronJob {
  schedule: string;
  time_wib: string;
  script: string;
  description: string;
}

interface PipelinePhase {
  phase: string;
  name: string;
  trigger: string;
  handler: string;
  emits: string;
}

interface SchedulerStatus {
  tasks: SchedulerTask[];
  cron_jobs: CronJob[];
  pipeline_phases: PipelinePhase[];
  summary: {
    total_tasks: number;
    succeeded: number;
    failed: number;
    pending: number;
    never_run: number;
    stale: number;
  };
}

const SCHEDULE_LABELS: Record<string, string> = {
  daily: "Harian",
  EOD: "EOD (End of Day)",
  weekly: "Mingguan",
  monthly: "Bulanan",
  every_15min: "Setiap 15 menit",
  hourly: "Setiap jam",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "success")
    return <CheckCircle2 className="w-4 h-4 text-green-600" />;
  if (status === "failed")
    return <XCircle className="w-4 h-4 text-red-600" />;
  if (status === "running")
    return <RefreshCw className="w-4 h-4 text-blue-500 animate-spin" />;
  if (status === "skipped")
    return <Circle className="w-4 h-4 text-gray-400" />;
  return <Circle className="w-4 h-4 text-muted-foreground" />;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    running: "bg-blue-100 text-blue-700",
    skipped: "bg-gray-100 text-gray-500",
    pending: "bg-yellow-100 text-yellow-700",
  };
  const labels: Record<string, string> = {
    success: "Berhasil",
    failed: "Gagal",
    running: "Berjalan",
    skipped: "Skip",
    pending: "Menunggu",
  };
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || colors.pending}`}
    >
      {labels[status] || status}
    </span>
  );
}

function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const diff = new Date(target).getTime() - now;
  if (diff <= 0) return <span className="text-green-500">sekarang</span>;
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  if (h > 0) return <span className="text-primary">{h}j {m}m</span>;
  if (m > 0) return <span className="text-primary">{m}m {s}s</span>;
  return <span className="text-orange-500">{s}s</span>;
}

export default function SchedulerPage() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    "tasks" | "cron" | "pipeline"
  >("tasks");

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/scheduler/status");
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const runDueTasks = useCallback(async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const res = await fetch("/api/scheduler/run", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const light = data.results?.map(
          (r: { task_id: string; status: string; duration_seconds: number }) =>
            `${r.task_id}(${r.status}, ${r.duration_seconds}s)`,
        ).join(", ") || "";
        const heavy = data.heavy_dispatched?.length
          ? ` | Background: ${data.heavy_dispatched.join(", ")}`
          : "";
        setRunResult(
          `Menjalankan ${data.executed} task` +
            (light ? `: ${light}` : "") +
            heavy +
            (data.executed === 0 ? " — semua sudah up to date" : ""),
        );
        loadStatus();
      } else {
        setRunResult("Gagal menjalankan scheduler");
      }
    } catch {
      setRunResult("Error: tidak bisa terhubung ke API");
    }
    setRunning(false);
  }, [loadStatus]);

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Scheduler</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Status task terjadwal, cron jobs, dan event-driven pipeline
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runDueTasks}
            disabled={running}
            className="flex items-center gap-2 px-3 py-2 rounded-md bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
          >
            <Zap className={`w-4 h-4 ${running ? "animate-pulse" : ""}`} />
            {running ? "Menjalankan..." : "Run Due Tasks"}
          </button>
          <button
            onClick={loadStatus}
            className="flex items-center gap-2 px-3 py-2 rounded-md border border-border text-sm hover:bg-accent"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {runResult && (
        <div className="p-3 rounded-md border border-border bg-muted/50 text-sm">
          {runResult}
        </div>
      )}

      {/* Summary Cards */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-blue-500" />
                <div>
                  <p className="text-2xl font-bold">
                    {status.summary.total_tasks}
                  </p>
                  <p className="text-xs text-muted-foreground">Total Tasks</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-green-600" />
                <div>
                  <p className="text-2xl font-bold text-green-600">
                    {status.summary.succeeded}
                  </p>
                  <p className="text-xs text-muted-foreground">Berhasil</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <XCircle className="w-4 h-4 text-red-600" />
                <div>
                  <p className="text-2xl font-bold text-red-600">
                    {status.summary.failed}
                  </p>
                  <p className="text-xs text-muted-foreground">Gagal</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <Circle className="w-4 h-4 text-yellow-500" />
                <div>
                  <p className="text-2xl font-bold text-yellow-600">
                    {status.summary.pending}
                  </p>
                  <p className="text-xs text-muted-foreground">Menunggu</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-gray-400" />
                <div>
                  <p className="text-2xl font-bold text-gray-500">
                    {status.summary.never_run}
                  </p>
                  <p className="text-xs text-muted-foreground">Belum Pernah</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-orange-500" />
                <div>
                  <p className="text-2xl font-bold text-orange-500">
                    {status.summary.stale}
                  </p>
                  <p className="text-xs text-muted-foreground">Stale</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {[
          { key: "tasks" as const, label: "Task Scheduler", icon: Clock },
          { key: "cron" as const, label: "Cron Jobs", icon: Calendar },
          { key: "pipeline" as const, label: "Event Pipeline", icon: GitBranch },
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

      {/* Tasks Tab */}
      {activeTab === "tasks" && status && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Task Scheduler — 24 Task Terdaftar
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 pr-4">Status</th>
                    <th className="pb-2 pr-4">Task</th>
                    <th className="pb-2 pr-4">Jadwal</th>
                    <th className="pb-2 pr-4">WIB</th>
                    <th className="pb-2 pr-4">Last Run</th>
                    <th className="pb-2 pr-4">Next Run</th>
                    <th className="pb-2 pr-4">Countdown</th>
                    <th className="pb-2 pr-4">Deps</th>
                    <th className="pb-2 pr-4">Runs</th>
                    <th className="pb-2 pr-4">Dur</th>
                    <th className="pb-2 pr-4">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {status.tasks.map((task) => (
                    <tr
                      key={task.task_id}
                      className={`border-b border-border/50 ${task.is_stale ? "bg-orange-500/5" : ""}`}
                    >
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-1">
                          <StatusIcon status={task.last_status} />
                          {task.is_stale && (
                            <AlertTriangle className="w-3 h-3 text-orange-500" />
                          )}
                          {task.is_catchup && (
                            <span className="text-[9px] bg-blue-100 text-blue-700 px-1 rounded">catch-up</span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="font-medium">{task.name}</div>
                        <div className="text-xs text-muted-foreground font-mono">
                          {task.task_id}
                        </div>
                      </td>
                      <td className="py-2 pr-4">
                        <span className="text-xs bg-muted px-2 py-0.5 rounded">
                          {SCHEDULE_LABELS[task.schedule] || task.schedule}
                        </span>
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs">
                        {task.time_of_day}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground text-xs">
                        {fmtDate(task.last_run)}
                      </td>
                      <td className="py-2 pr-4 text-muted-foreground text-xs">
                        {fmtDate(task.next_run_at)}
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs">
                        {task.next_run_at ? (
                          <Countdown target={task.next_run_at} />
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        {task.data_dependencies.length > 0 ? (
                          <div className="flex items-center gap-1" title={task.data_dependencies.join(", ")}>
                            <Database className="w-3 h-3 text-muted-foreground" />
                            <span className="text-xs text-muted-foreground">
                              {task.data_dependencies.length}
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground text-xs">-</span>
                        )}
                      </td>
                      <td className="py-2 pr-4">{task.run_count}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                        {task.last_duration_seconds > 0
                          ? `${task.last_duration_seconds.toFixed(1)}s`
                          : "-"}
                      </td>
                      <td className="py-2 pr-4 text-xs text-red-500 max-w-xs truncate">
                        {task.last_error || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cron Jobs Tab */}
      {activeTab === "cron" && status && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Cron Jobs Aktif (crontab)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-muted-foreground">
                      <th className="pb-2 pr-4">Schedule (WIB)</th>
                      <th className="pb-2 pr-4">WIB</th>
                      <th className="pb-2 pr-4">Script</th>
                      <th className="pb-2 pr-4">Deskripsi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.cron_jobs.map((job, i) => (
                      <tr
                        key={i}
                        className="border-b border-border/50"
                      >
                        <td className="py-2 pr-4 font-mono text-xs">
                          {job.schedule}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs text-primary">
                          {job.time_wib}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">
                          {job.script}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">
                          {job.description}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Catch-up Mechanism
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-start gap-3 p-3 rounded-md border border-border/50">
                <Zap className="w-4 h-4 text-yellow-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium">@reboot Catch-up</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Saat komputer boot, <code className="text-xs">catchup_daily.sh</code>{" "}
                    check state files. Jika scheduler belum run hari ini,
                    jalankan <code className="text-xs">run_daily_scheduler.sh</code>.
                    Idempotent — fetch skip data fresh, recompute DELETE+INSERT.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 rounded-md border border-border/50">
                <Clock className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium">_is_due() Check</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    <code className="text-xs">run_all_due()</code> load state
                    dari DB. Task due jika: daily/EOD &gt;20h, weekly &gt;6
                    hari, monthly &gt;28 hari. Task yang belum pernah run
                    otomatis due.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 rounded-md border border-border/50">
                <AlertCircle className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium">Startup Staleness Check</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    <code className="text-xs">startup_catchup</code> task check
                    OHLCV terbaru. Jika &gt;26 jam (missed 1 trading day),
                    trigger full fetch → recompute → export chain.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Pipeline Tab */}
      {activeTab === "pipeline" && status && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Event-Driven Pipeline Architecture
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {status.pipeline_phases.map((phase) => (
                <div
                  key={phase.phase}
                  className="flex items-center gap-4 p-3 rounded-md border border-border/50"
                >
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <span className="text-sm font-bold text-primary">
                      {phase.phase}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{phase.name}</span>
                      <span className="text-xs text-muted-foreground">
                        ({phase.handler})
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-xs">
                      <span className="text-muted-foreground">Listen:</span>
                      <code className="bg-muted px-1.5 py-0.5 rounded text-xs">
                        {phase.trigger}
                      </code>
                      <span className="text-muted-foreground">→</span>
                      <span className="text-muted-foreground">Emit:</span>
                      <code className="bg-muted px-1.5 py-0.5 rounded text-xs">
                        {phase.emits}
                      </code>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {loading && !status && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      )}
    </div>
  );
}

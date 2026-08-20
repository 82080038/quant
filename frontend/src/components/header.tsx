"use client";

import { Clock, CircleDot, Globe, FlaskConical, Radio, Timer, Loader2, AlertTriangle, CheckCircle2, CalendarClock } from "lucide-react";
import { useMarket } from "./market-context";
import { useScheduler } from "./scheduler-context";
import { cn } from "@/lib/utils";

export function Header() {
  const m = useMarket();
  const s = useScheduler();

  return (
    <header className="border-b border-border bg-card shrink-0">
      {/* Row 1: Time + Mode */}
      <div className="h-10 flex items-center justify-between px-6">
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-muted-foreground" />
            <span className="font-mono text-muted-foreground text-xs">{m.utcTime}</span>
          </div>
          <div className="w-px h-4 bg-border" />
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-primary" />
            <span className="font-mono text-primary text-xs">{m.wibTime}</span>
          </div>
        </div>

        <div className="flex items-center gap-4 text-sm">
          {/* Mode indicator: Simulasi vs Real */}
          <div className="flex items-center gap-2 px-2 py-0.5 rounded-md border border-border">
            {m.mode === "simulasi" ? (
              <>
                <FlaskConical className="w-3.5 h-3.5 text-blue-500" />
                <span className="text-xs font-medium text-blue-500">SIMULASI</span>
              </>
            ) : (
              <>
                <Radio className="w-3.5 h-3.5 text-green-500" />
                <span className="text-xs font-medium text-green-500">REAL</span>
              </>
            )}
          </div>

          {/* IDX session status */}
          <div className="flex items-center gap-2">
            <CircleDot className={cn("w-3 h-3", m.idxSession.color)} />
            <span className={cn("text-xs font-medium", m.idxSession.color)}>
              IDX: {m.idxSession.label}
            </span>
          </div>
        </div>
      </div>

      {/* Row 2: Scheduler status — countdown & render status */}
      <div className="h-7 flex items-center gap-3 px-6 border-t border-border/50 text-xs overflow-x-auto">
        {/* Running tasks */}
        {s.running.length > 0 ? (
          <div className="flex items-center gap-2 shrink-0">
            <Loader2 className="w-3 h-3 text-blue-500 animate-spin shrink-0" />
            <span className="text-blue-500 font-medium shrink-0">
              Sedang render: {s.running.map(t => t.task_id).join(", ")}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />
            <span className="text-muted-foreground shrink-0">Siaga</span>
          </div>
        )}

        <div className="w-px h-3 bg-border shrink-0" />

        {/* Next task countdown */}
        {s.nextTask ? (
          <div className="flex items-center gap-2 shrink-0">
            <Timer className="w-3 h-3 text-primary shrink-0" />
            <span className="text-muted-foreground shrink-0">Berikutnya:</span>
            <span className="font-medium text-primary shrink-0">{s.nextTask.task_id}</span>
            <span className="font-mono text-primary shrink-0">
              {s.countdown}
            </span>
            <span className="text-muted-foreground text-[10px] shrink-0">
              ({new Date(s.nextTask.next_run_at).toLocaleString("id-ID", {
                timeZone: "Asia/Jakarta",
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "short",
              })} WIB)
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            <Timer className="w-3 h-3 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground shrink-0">Tidak ada task terjadwal</span>
          </div>
        )}

        {/* Stale alert */}
        {s.stale.length > 0 && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <div className="flex items-center gap-2 shrink-0">
              <AlertTriangle className="w-3 h-3 text-orange-500 shrink-0" />
              <span className="text-orange-500 font-medium shrink-0">
                Terlambat: {s.stale.length} task
              </span>
              <span className="text-muted-foreground text-[10px] shrink-0">
                ({s.stale.slice(0, 3).join(", ")}{s.stale.length > 3 ? "…" : ""})
              </span>
            </div>
          </>
        )}

        {/* Pratinjau antrian akan datang */}
        {s.upcoming.length > 1 && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-muted-foreground shrink-0">Antrian:</span>
              {s.upcoming.slice(1, 5).map((t, i) => (
                <span key={t.task_id} className="text-muted-foreground text-[10px] shrink-0">
                  {i > 0 && <span className="text-muted-foreground/40">→</span>}
                  {" "}
                  <span className="font-medium">{t.task_id}</span>
                </span>
              ))}
              {s.upcoming.length > 5 && (
                <span className="text-muted-foreground text-[10px] shrink-0">
                  +{s.upcoming.length - 5}
                </span>
              )}
            </div>
          </>
        )}

        {/* Libur IDX berikutnya */}
        {s.nextIdxHoliday && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <div className="flex items-center gap-2 shrink-0" title={`${s.nextIdxHoliday.exchange_name}: ${s.nextIdxHoliday.name}`}>
              <CalendarClock className="w-3 h-3 text-purple-500 shrink-0" />
              <span className="text-muted-foreground shrink-0">Libur IDX:</span>
              <span className="font-medium text-purple-500 shrink-0">
                {s.nextIdxHoliday.days_until === 0 ? "hari ini" : `${s.nextIdxHoliday.days_until}h lagi`}
              </span>
              <span className="text-muted-foreground text-[10px] shrink-0">
                {s.nextIdxHoliday.name}
              </span>
            </div>
          </>
        )}

        {/* Libur bursa lain hari ini */}
        {s.holidays.filter(h => h.days_until === 0 && h.mic_code !== "XIDX").length > 0 && (
          <>
            <div className="w-px h-3 bg-border shrink-0" />
            <div className="flex items-center gap-2 shrink-0">
              <CalendarClock className="w-3 h-3 text-orange-500 shrink-0" />
              <span className="text-orange-500 font-medium shrink-0">
                Libur: {s.holidays.filter(h => h.days_until === 0 && h.mic_code !== "XIDX").map(h => h.mic_code).join(", ")}
              </span>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

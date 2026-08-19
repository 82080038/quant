"use client";

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";

interface UpcomingTask {
  task_id: string;
  name: string;
  next_run_at: string;
  schedule: string;
  time_of_day: string;
  data_dependencies: string[];
  data_ready: boolean;
  is_stale: boolean;
}

interface SchedulerStatus {
  tasks: SchedulerTaskInfo[];
  summary: {
    total_tasks: number;
    succeeded: number;
    failed: number;
    pending: number;
    never_run: number;
    stale: number;
  };
}

interface SchedulerTaskInfo {
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
  last_result: Record<string, unknown> | null;
  is_catchup: boolean;
  last_duration_seconds: number;
}

interface HolidayInfo {
  mic_code: string;
  exchange_name: string;
  date: string;
  name: string;
  days_until: number;
}

interface SchedulerContextValue {
  upcoming: UpcomingTask[];
  running: SchedulerTaskInfo[];
  stale: string[];
  nextTask: UpcomingTask | null;
  countdown: string;
  status: SchedulerStatus | null;
  loading: boolean;
  holidays: HolidayInfo[];
  nextIdxHoliday: HolidayInfo | null;
  refresh: () => void;
}

const SchedulerContext = createContext<SchedulerContextValue | null>(null);

function formatCountdown(target: string): string {
  const now = new Date();
  const targetDate = new Date(target);
  const diffMs = targetDate.getTime() - now.getTime();
  if (diffMs <= 0) return "sekarang";
  const totalMin = Math.floor(diffMs / 60000);
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  const secs = Math.floor((diffMs % 60000) / 1000);
  if (hours > 0) return `${hours}j ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

export function SchedulerProvider({ children }: { children: ReactNode }) {
  const [upcoming, setUpcoming] = useState<UpcomingTask[]>([]);
  const [status, setStatus] = useState<SchedulerStatus | null>(null);
  const [holidays, setHolidays] = useState<HolidayInfo[]>([]);
  const [, setTick] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [upcomingRes, statusRes, holidayRes] = await Promise.all([
        fetch("/api/scheduler/upcoming?hours=12"),
        fetch("/api/scheduler/status"),
        fetch("/api/scheduler/holidays?days=30"),
      ]);
      if (upcomingRes.ok) {
        const data = await upcomingRes.json();
        setUpcoming(data.upcoming || []);
      }
      if (statusRes.ok) {
        const data = await statusRes.json();
        setStatus(data);
      }
      if (holidayRes.ok) {
        const data = await holidayRes.json();
        setHolidays(data.upcoming || []);
      }
    } catch {
      // API not available — silent
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const pollTimer = setInterval(fetchData, 30000); // poll every 30s
    return () => clearInterval(pollTimer);
  }, [fetchData]);

  // Tick every second for countdown updates
  useEffect(() => {
    const tickTimer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(tickTimer);
  }, []);

  const running = status?.tasks.filter(t => t.last_status === "running") || [];
  const stale = status?.tasks.filter(t => t.is_stale).map(t => t.task_id) || [];
  const nextTask = upcoming.length > 0 ? upcoming[0] : null;
  const countdown = nextTask ? formatCountdown(nextTask.next_run_at) : "—";
  const nextIdxHoliday = holidays.find(h => h.mic_code === "XIDX") || null;

  const value: SchedulerContextValue = {
    upcoming,
    running,
    stale,
    nextTask,
    countdown,
    status,
    loading,
    holidays,
    nextIdxHoliday,
    refresh: fetchData,
  };

  return <SchedulerContext.Provider value={value}>{children}</SchedulerContext.Provider>;
}

export function useScheduler() {
  const ctx = useContext(SchedulerContext);
  if (!ctx) throw new Error("useScheduler must be used within SchedulerProvider");
  return ctx;
}

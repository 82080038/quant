"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCallback, useEffect, useState } from "react";

interface Settings {
  risk_per_trade_pct: number;
  atr_multiplier_sl: number;
  risk_reward_ratio: number;
  max_volatility_pct: number;
  telegram_alert_enabled: boolean;
  email_alert_enabled: boolean;
  in_app_alert_enabled: boolean;
  circuit_breaker_alert_enabled: boolean;
  display_timezone: string;
  default_chart_period: string;
}

const DEFAULT_SETTINGS: Settings = {
  risk_per_trade_pct: 1.0,
  atr_multiplier_sl: 1.5,
  risk_reward_ratio: 2.0,
  max_volatility_pct: 50.0,
  telegram_alert_enabled: true,
  email_alert_enabled: false,
  in_app_alert_enabled: true,
  circuit_breaker_alert_enabled: true,
  display_timezone: "Asia/Jakarta",
  default_chart_period: "30d",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const res = await fetch("/api/settings");
      if (res.ok) {
        const data = await res.json();
        setSettings({ ...DEFAULT_SETTINGS, ...data });
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings]);

  const saveSettings = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        const data = await res.json();
        setSaveMsg(`Tersimpan: ${data.saved_to || "ok"}`);
      } else {
        setSaveMsg("Gagal menyimpan settings.");
      }
    } catch {
      setSaveMsg("Tidak bisa terhubung ke API.");
    }
    setSaving(false);
  };

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Pengaturan</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Parameter risiko, notifikasi, dan API key
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Parameter Risiko</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium block mb-1">Risk per Trade (%)</label>
              <input type="number" value={settings.risk_per_trade_pct} min={0.1} max={5} step={0.1}
                onChange={(e) => update("risk_per_trade_pct", parseFloat(e.target.value) || 1.0)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">ATR Multiplier (SL)</label>
              <input type="number" value={settings.atr_multiplier_sl} min={0.5} max={5} step={0.1}
                onChange={(e) => update("atr_multiplier_sl", parseFloat(e.target.value) || 1.5)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Risk-Reward Ratio</label>
              <input type="number" value={settings.risk_reward_ratio} min={1} max={5} step={0.5}
                onChange={(e) => update("risk_reward_ratio", parseFloat(e.target.value) || 2.0)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Max Volatility (%)</label>
              <input type="number" value={settings.max_volatility_pct} min={10} max={100}
                onChange={(e) => update("max_volatility_pct", parseFloat(e.target.value) || 50.0)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Notifikasi</CardTitle></CardHeader>
        <CardContent>
          <div className="space-y-3">
            {([
              { key: "telegram_alert_enabled", label: "Telegram Alert", desc: "Kirim notifikasi via Telegram bot" },
              { key: "email_alert_enabled", label: "Email Alert", desc: "Kirim notifikasi via email" },
              { key: "in_app_alert_enabled", label: "In-App Alert", desc: "Tampilkan notifikasi di aplikasi" },
              { key: "circuit_breaker_alert_enabled", label: "Circuit Breaker Alert", desc: "Notifikasi saat drawdown melewati threshold" },
            ] as const).map((item) => (
              <div key={item.key} className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{item.label}</p>
                  <p className="text-xs text-muted-foreground">{item.desc}</p>
                </div>
                <input
                  type="checkbox"
                  checked={settings[item.key]}
                  onChange={(e) => update(item.key, e.target.checked)}
                  className="w-4 h-4"
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>API Key</CardTitle></CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium block mb-1">Yahoo Finance API (opsional)</label>
              <input type="password" placeholder="••••••••••••"
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Broker API Key</label>
              <input type="password" placeholder="••••••••••••"
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
            </div>
            <p className="text-xs text-muted-foreground">
              API key disimpan di file .env dan tidak pernah di-commit ke git.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Aktivasi Broker Real</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
              <p className="text-xs text-yellow-600 dark:text-yellow-500">
                ⚠️ Aktivasi broker real akan mengaktifkan trading dengan uang sungguhan.
                Pastikan paper trading telah berjalan minimal 30 hari dengan hasil yang memadai.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium block mb-1">Broker</label>
                <select className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm">
                  <option value="">— Pilih Broker —</option>
                  <option value="sinarmas">Sinarmas Sekuritas</option>
                  <option value="bni">BNI Sekuritas</option>
                  <option value="mirae">Mirae Asset Sekuritas</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Environment</label>
                <select className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm">
                  <option value="paper">Paper (simulasi)</option>
                  <option value="live">Live (uang sungguhan)</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Broker Username</label>
                <input type="text" placeholder="Broker account username"
                  className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Broker Password</label>
                <input type="password" placeholder="••••••••••••"
                  className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Broker API Token</label>
                <input type="password" placeholder="••••••••••••"
                  className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Approval Token File</label>
                <input type="text" placeholder="/path/to/approval.token"
                  className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm" />
              </div>
            </div>

            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="w-4 h-4" />
                Saya telah menjalankan paper trading minimal 30 hari
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="w-4 h-4" />
                Saya memahami risiko kehilangan modal
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="w-4 h-4" />
                Saya menyetujui daily loss limit dan max drawdown settings
              </label>
            </div>

            <button
              type="button"
              className="w-full px-4 py-2 rounded-md bg-yellow-600 text-white text-sm font-medium hover:bg-yellow-700 disabled:opacity-50"
            >
              Aktifkan Broker Real
            </button>
            <p className="text-xs text-muted-foreground">
              Aktivasi memerlukan approval token file yang ditandatangani manual.
              Lihat MEGAPLAN.md §6.4 Human-Gate Checklist.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Save button */}
      <div className="flex items-center gap-4">
        <button
          onClick={saveSettings}
          disabled={saving}
          className="px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? "Menyimpan..." : "Simpan Pengaturan"}
        </button>
        {saveMsg && <p className="text-sm text-muted-foreground">{saveMsg}</p>}
      </div>
    </div>
  );
}

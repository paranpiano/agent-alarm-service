import { format } from 'date-fns';

// ── StatCard ──────────────────────────────────────────────────────────────────
interface StatCardProps {
  label: string;
  value: string | number;
  color?: string;
}

export function StatCard({ label, value, color = 'text-white' }: StatCardProps) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 flex flex-col gap-1">
      <span className="text-gray-400 text-sm">{label}</span>
      <span className={`text-2xl font-bold ${color}`}>{value}</span>
    </div>
  );
}

// ── DateRangePicker ───────────────────────────────────────────────────────────
interface DateRangePickerProps {
  startDate: Date;
  endDate: Date;
  onChange: (start: Date, end: Date) => void;
}

const PRESETS = [
  { label: '오늘', days: 0 },
  { label: '3일', days: 2 },
  { label: '7일', days: 6 },
  { label: '30일', days: 29 },
];

export function DateRangePicker({ startDate, endDate, onChange }: DateRangePickerProps) {
  const applyPreset = (days: number) => {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    const start = new Date();
    start.setDate(start.getDate() - days);
    start.setHours(0, 0, 0, 0);
    onChange(start, end);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {PRESETS.map((p) => (
        <button
          key={p.label}
          onClick={() => applyPreset(p.days)}
          className="px-3 py-1 text-sm rounded bg-gray-700 hover:bg-blue-600 text-white transition-colors"
        >
          {p.label}
        </button>
      ))}
      <input
        type="date"
        value={format(startDate, 'yyyy-MM-dd')}
        onChange={(e) => onChange(new Date(e.target.value), endDate)}
        className="px-2 py-1 text-sm rounded bg-gray-700 text-white border border-gray-600"
      />
      <span className="text-gray-400 text-sm">~</span>
      <input
        type="date"
        value={format(endDate, 'yyyy-MM-dd')}
        onChange={(e) => {
          const d = new Date(e.target.value);
          d.setHours(23, 59, 59, 999);
          onChange(startDate, d);
        }}
        className="px-2 py-1 text-sm rounded bg-gray-700 text-white border border-gray-600"
      />
    </div>
  );
}

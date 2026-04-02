import { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, LabelList, Cell, Legend,
} from 'recharts';
import { startOfDay, endOfDay, format, eachDayOfInterval } from 'date-fns';
import { fetchLogs, type LogEntry, type LogStatus } from '../lib';
import { DateRangePicker } from '../components/Shared';

const TOOLTIP_STYLE = { backgroundColor: '#1f2937', border: 'none', color: '#e5e7eb' };
const TICK = { fill: '#9ca3af', fontSize: 11 };
const ALL_EQUIPMENT = ['S520', 'S530', 'S540', 'S810', 'S510', 'S310'];
const EQ_COLORS: Record<string, string> = {
  S520: '#60a5fa', S530: '#34d399', S540: '#f97316',
  S810: '#f43f5e', S510: '#a78bfa', S310: '#facc15',
};

function heatColor(value: number, max: number): string {
  if (value === 0) return '#1f2937';
  const ratio = value / Math.max(max, 1);
  const r = Math.round(239 * ratio + 100 * (1 - ratio));
  const g = Math.round(68 * ratio + 100 * (1 - ratio));
  const b = Math.round(68 * ratio + 100 * (1 - ratio));
  return `rgb(${r},${g},${b})`;
}

export default function Dashboard() {
  const [startDate, setStartDate] = useState(() => startOfDay(new Date()));
  const [endDate, setEndDate] = useState(() => endOfDay(new Date()));
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<LogStatus | 'ALL'>('NG');
  const [eqFilter, setEqFilter] = useState<string>('ALL');
  const [selectedDate, setSelectedDate] = useState<string>('');

  useEffect(() => {
    setLoading(true);
    fetchLogs(startDate, endDate).then(setLogs).finally(() => setLoading(false));
  }, [startDate, endDate]);

  const dateList = useMemo(() =>
    eachDayOfInterval({ start: startDate, end: endDate }).map((d) => format(d, 'yyyy-MM-dd')),
    [startDate, endDate]
  );

  useEffect(() => {
    if (dateList.length > 0) setSelectedDate(dateList[dateList.length - 1]);
  }, [dateList]);

  const filtered = useMemo(() =>
    logs.filter((l) => {
      if (statusFilter !== 'ALL' && l.status !== statusFilter) return false;
      if (eqFilter !== 'ALL' && !l.equipment_data?.[eqFilter]) return false;
      return true;
    }),
    [logs, statusFilter, eqFilter]
  );

  const heatmapData = useMemo(() => {
    const map: Record<string, Record<number, number>> = {};
    dateList.forEach((d) => { map[d] = {}; for (let h = 0; h < 24; h++) map[d][h] = 0; });
    filtered.forEach((l) => {
      const d = l.log_date;
      const h = new Date(l.timestamp).getHours();
      if (map[d]) map[d][h]++;
    });
    return map;
  }, [filtered, dateList]);

  const heatmapMax = useMemo(() =>
    Math.max(1, ...Object.values(heatmapData).flatMap((row) => Object.values(row))),
    [heatmapData]
  );

  const hourlyData = useMemo(() => {
    const row = heatmapData[selectedDate] ?? {};
    return Array.from({ length: 24 }, (_, h) => ({ hour: `${h}시`, count: row[h] ?? 0 }));
  }, [heatmapData, selectedDate]);

  const equipmentNgData = useMemo(() => {
    const map: Record<string, number> = {};
    filtered.forEach((l) => {
      Object.entries(l.equipment_data ?? {}).forEach(([eqId, eq]) => {
        if (eq.ng_items?.length > 0) map[eqId] = (map[eqId] ?? 0) + 1;
      });
    });
    return Object.entries(map).map(([eq, count]) => ({ eq, count }));
  }, [filtered]);

  const trendData = useMemo(() => {
    const dates = eachDayOfInterval({ start: startDate, end: endDate }).map((d) => format(d, 'yyyy-MM-dd'));
    const map: Record<string, Record<string, number>> = {};
    dates.forEach((d) => { map[d] = {}; ALL_EQUIPMENT.forEach((eq) => { map[d][eq] = 0; }); });
    filtered.filter((l) => l.status === 'NG').forEach((l) => {
      Object.entries(l.equipment_data ?? {}).forEach(([eqId, eq]) => {
        if (eq.ng_items?.length > 0 && map[l.log_date]) {
          map[l.log_date][eqId] = (map[l.log_date][eqId] ?? 0) + 1;
        }
      });
    });
    return dates.map((d) => ({ date: d.slice(5), ...map[d] })) as Array<{ date: string } & Record<string, number>>;
  }, [filtered, startDate, endDate]);

  const activeEquipment = useMemo(() =>
    ALL_EQUIPMENT.filter((eq) => trendData.some((row) => (row[eq] as number) > 0)),
    [trendData]
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-white text-xl font-bold">Dashboard</h1>
        <DateRangePicker startDate={startDate} endDate={endDate}
          onChange={(s, e) => { setStartDate(s); setEndDate(e); }} />
      </div>

      {loading && <p className="text-gray-400 text-sm">로딩 중...</p>}

      <div className="flex flex-wrap gap-3 items-center">
        {(['ALL', 'OK', 'NG'] as const).map((s) => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 text-sm rounded transition-colors ${
              statusFilter === s ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}>{s}</button>
        ))}
        <div className="w-px h-5 bg-gray-600" />
        {(['ALL', ...ALL_EQUIPMENT] as const).map((eq) => (
          <button key={eq} onClick={() => setEqFilter(eq)}
            className={`px-3 py-1 text-sm rounded transition-colors ${
              eqFilter === eq ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}>{eq}</button>
        ))}
        <span className="text-gray-500 text-sm">{filtered.length}건</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* 날짜×시간 히트맵 */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-gray-300 text-sm mb-3">날짜 × 시간대 히트맵</h2>
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse w-full">
              <thead>
                <tr>
                  <th className="text-gray-500 pr-2 text-right w-20">날짜</th>
                  {Array.from({ length: 24 }, (_, h) => (
                    <th key={h} className="text-gray-500 text-center w-6 pb-1">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dateList.map((date) => (
                  <tr key={date} onClick={() => setSelectedDate(date)}
                    className={`cursor-pointer ${selectedDate === date ? 'ring-1 ring-blue-400' : ''}`}>
                    <td className={`pr-2 text-right py-0.5 ${selectedDate === date ? 'text-blue-400 font-bold' : 'text-gray-400'}`}>
                      {date.slice(5)}
                    </td>
                    {Array.from({ length: 24 }, (_, h) => {
                      const v = heatmapData[date]?.[h] ?? 0;
                      return (
                        <td key={h} className="w-6 h-5 text-center"
                          style={{ backgroundColor: heatColor(v, heatmapMax) }}
                          title={`${date} ${h}시: ${v}건`}>
                          {v > 0 && <span className="text-white" style={{ fontSize: 9 }}>{v}</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-gray-600 text-xs mt-2">행 클릭 시 우측 차트에 반영</p>
        </div>

        {/* 선택 날짜 시간대별 바 차트 */}
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center gap-3 mb-3">
            <h2 className="text-gray-300 text-sm">시간대별 판정 건수</h2>
            <select value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}
              className="px-2 py-0.5 text-xs rounded bg-gray-700 text-white border border-gray-600">
              {dateList.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={hourlyData} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <XAxis dataKey="hour" tick={TICK} />
              <YAxis tick={TICK} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="count" fill="#ef4444">
                <LabelList dataKey="count" position="top" style={{ fill: '#e5e7eb', fontSize: 10 }}
                  formatter={(v: unknown) => (v as number) > 0 ? String(v) : ''} />
                {hourlyData.map((entry, i) => (
                  <Cell key={i} fill={entry.count > 0 ? '#ef4444' : '#374151'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 장비별 NG 빈도 */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-gray-300 text-sm mb-3">장비별 NG 발생 빈도</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={equipmentNgData} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <XAxis dataKey="eq" tick={TICK} />
              <YAxis tick={TICK} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="count" fill="#f97316">
                <LabelList dataKey="count" position="top" style={{ fill: '#e5e7eb', fontSize: 12 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 장비별 날짜별 NG 트렌드 */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-gray-300 text-sm mb-3">장비별 NG 트렌드 (날짜별)</h2>
          {activeEquipment.length === 0
            ? <p className="text-gray-600 text-sm text-center py-8">NG 데이터가 없습니다.</p>
            : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={trendData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <XAxis dataKey="date" tick={TICK} />
                  <YAxis tick={TICK} allowDecimals={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 12, color: '#9ca3af' }} />
                  {activeEquipment.map((eq) => (
                    <Line key={eq} type="monotone" dataKey={eq}
                      stroke={EQ_COLORS[eq]} dot={{ r: 3 }} strokeWidth={2} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )
          }
        </div>

      </div>
    </div>
  );
}

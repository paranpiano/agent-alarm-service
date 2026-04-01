import { useEffect, useState, useMemo } from 'react';
import {
  useReactTable, getCoreRowModel, getSortedRowModel,
  flexRender, createColumnHelper, type SortingState,
} from '@tanstack/react-table';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';
import { startOfDay, endOfDay } from 'date-fns';
import { fetchLogs, type LogEntry, type LogStatus } from '../lib';
import { DateRangePicker } from '../components/Shared';
import { EquipmentDetail } from '../components/EquipmentDetail';

const TOOLTIP_STYLE = { backgroundColor: '#1f2937', border: 'none', color: '#e5e7eb' };
const TICK = { fill: '#9ca3af', fontSize: 11 };
const col = createColumnHelper<LogEntry>();
const STATUS_COLOR: Record<LogStatus, string> = { OK: 'text-green-400', NG: 'text-red-400' };
const ROW_BG: Record<LogStatus, string> = { OK: '', NG: 'bg-red-950/40' };
const ALL_EQUIPMENT = ['S520', 'S530', 'S540', 'S810', 'S510', 'S310'];
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

export default function LogViewer() {
  const [startDate, setStartDate] = useState(() => startOfDay(new Date()));
  const [endDate, setEndDate] = useState(() => endOfDay(new Date()));
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<LogStatus | 'ALL'>('ALL');
  const [eqFilter, setEqFilter] = useState<string>('ALL');
  const [keyword, setKeyword] = useState('');
  const [sorting, setSorting] = useState<SortingState>([]);
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(10);

  useEffect(() => {
    setLoading(true);
    fetchLogs(startDate, endDate).then(setLogs).finally(() => setLoading(false));
  }, [startDate, endDate]);

  // 필터 변경 시 첫 페이지로
  useEffect(() => { setPageIndex(0); }, [statusFilter, eqFilter, keyword]);

  const filtered = useMemo(() =>
    logs.filter((l) => {
      if (statusFilter !== 'ALL' && l.status !== statusFilter) return false;
      if (eqFilter !== 'ALL' && !l.equipment_data?.[eqFilter]) return false;
      if (keyword && !JSON.stringify(l).toLowerCase().includes(keyword.toLowerCase())) return false;
      return true;
    }),
    [logs, statusFilter, eqFilter, keyword]
  );

  // 정렬 적용
  const sorted = useMemo(() => {
    if (!sorting.length) return filtered;
    const { id, desc } = sorting[0];
    return [...filtered].sort((a, b) => {
      const av = a[id as keyof LogEntry] ?? '';
      const bv = b[id as keyof LogEntry] ?? '';
      return (av < bv ? -1 : av > bv ? 1 : 0) * (desc ? -1 : 1);
    });
  }, [filtered, sorting]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const paginated = useMemo(() =>
    sorted.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize),
    [sorted, pageIndex, pageSize]
  );

  // 처리 시간 트렌드 (filtered 기준 최근 50건)
  const timeTrend = useMemo(() =>
    filtered.slice(0, 50).reverse().map((l, i) => ({ i: i + 1, ms: l.processing_time_ms ?? 0 })),
    [filtered]
  );

  const columns = useMemo(() => [
    col.accessor('timestamp', {
      header: 'Timestamp',
      cell: (i) => <span className="text-gray-300 text-xs">{i.getValue()}</span>,
    }),
    col.accessor('status', {
      header: 'Status',
      cell: (i) => <span className={`font-bold text-sm ${STATUS_COLOR[i.getValue()]}`}>{i.getValue()}</span>,
    }),
    col.accessor('image_name', {
      header: 'Image',
      cell: (i) => <span className="text-gray-400 text-xs">{i.getValue()}</span>,
    }),
    col.accessor('processing_time_ms', {
      header: 'Time (ms)',
      cell: (i) => <span className="text-gray-300 text-xs">{i.getValue()}</span>,
    }),
    col.accessor('reason', {
      header: 'Reason',
      cell: (i) => (
        <span className="text-gray-400 text-xs truncate max-w-xs block" title={i.getValue()}>
          {i.getValue()}
        </span>
      ),
    }),
  ], []);

  const table = useReactTable({
    data: paginated,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    manualSorting: true,
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-white text-xl font-bold">Log Viewer</h1>
        <DateRangePicker startDate={startDate} endDate={endDate}
          onChange={(s, e) => { setStartDate(s); setEndDate(e); }} />
      </div>

      {/* 필터 */}
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
        <div className="w-px h-5 bg-gray-600" />
        <input type="text" placeholder="키워드 검색..." value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="px-3 py-1 text-sm rounded bg-gray-700 text-white border border-gray-600 w-48" />
        <span className="text-gray-500 text-sm">{filtered.length}건</span>
      </div>

      {loading && <p className="text-gray-400 text-sm">로딩 중...</p>}

      {/* 테이블 */}
      <div className="overflow-x-auto rounded-lg border border-gray-700">
        <table className="w-full text-left">
          <thead className="bg-gray-700">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th key={h.id} onClick={h.column.getToggleSortingHandler()}
                    className="px-4 py-2 text-gray-300 text-xs font-semibold cursor-pointer select-none hover:text-white">
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {h.column.getIsSorted() === 'asc' ? ' ↑' : h.column.getIsSorted() === 'desc' ? ' ↓' : ''}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} onClick={() => setSelected(row.original)}
                className={`border-t border-gray-700 cursor-pointer hover:bg-gray-700/50 ${ROW_BG[row.original.status]}`}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {!loading && paginated.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500 text-sm">
                  데이터가 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 페이징 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-gray-400 text-sm">페이지당</span>
          <select value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPageIndex(0); }}
            className="px-2 py-1 text-sm rounded bg-gray-700 text-white border border-gray-600">
            {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <span className="text-gray-400 text-sm">건</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setPageIndex(0)} disabled={pageIndex === 0}
            className="px-2 py-1 text-sm rounded bg-gray-700 text-gray-300 disabled:opacity-30 hover:bg-gray-600">«</button>
          <button onClick={() => setPageIndex((p) => Math.max(0, p - 1))} disabled={pageIndex === 0}
            className="px-2 py-1 text-sm rounded bg-gray-700 text-gray-300 disabled:opacity-30 hover:bg-gray-600">‹</button>
          <span className="text-gray-400 text-sm px-2">
            {pageIndex + 1} / {totalPages}
          </span>
          <button onClick={() => setPageIndex((p) => Math.min(totalPages - 1, p + 1))} disabled={pageIndex >= totalPages - 1}
            className="px-2 py-1 text-sm rounded bg-gray-700 text-gray-300 disabled:opacity-30 hover:bg-gray-600">›</button>
          <button onClick={() => setPageIndex(totalPages - 1)} disabled={pageIndex >= totalPages - 1}
            className="px-2 py-1 text-sm rounded bg-gray-700 text-gray-300 disabled:opacity-30 hover:bg-gray-600">»</button>
        </div>
      </div>

      {/* 처리 시간 트렌드 */}
      <div className="bg-gray-800 rounded-lg p-4">
        <h2 className="text-gray-300 text-sm mb-3">처리 시간 트렌드 (최근 50건)</h2>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={timeTrend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <XAxis dataKey="i" tick={TICK} />
            <YAxis tick={TICK} unit="ms" width={50} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${v}ms`, '처리시간']} />
            <Line type="monotone" dataKey="ms" stroke="#a78bfa" dot={false} strokeWidth={1.5} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {selected && <EquipmentDetail log={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

import { format } from 'date-fns';

export type LogStatus = 'OK' | 'NG';

export interface EquipmentEntry {
  identified: boolean;
  ng_items: string[];
  color_reasoning?: string;
  curing_oven?: number[];
  preheating_oven?: number[];
  cooling_1_line?: number[];
  cooling_2_line?: number[];
  wait_counts?: number[];
  stations?: unknown;
}

export interface LogEntry {
  log_date: string;
  request_id: string;
  timestamp: string;
  status: LogStatus;
  reason: string;
  image_name: string;
  processing_time_ms: number;
  equipment_data: Record<string, EquipmentEntry>;
}

const API_URL = import.meta.env.VITE_API_URL as string;

async function fetchByDate(date: string): Promise<LogEntry[]> {
  const res = await fetch(`${API_URL}?date=${date}&limit=500`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  const data = await res.json();
  return (data.logs ?? []) as LogEntry[];
}

export async function fetchLogs(startDate: Date, endDate: Date): Promise<LogEntry[]> {
  const dates: string[] = [];
  const cur = new Date(startDate);
  while (cur <= endDate) {
    dates.push(format(cur, 'yyyy-MM-dd'));
    cur.setDate(cur.getDate() + 1);
  }
  const results = await Promise.all(dates.map(fetchByDate));
  return results.flat().sort((a, b) => b.timestamp.localeCompare(a.timestamp));
}

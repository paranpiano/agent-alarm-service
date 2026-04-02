import type { LogEntry } from '../lib';

interface Props {
  log: LogEntry;
  onClose: () => void;
}

const NUMERIC_FIELDS = ['curing_oven', 'preheating_oven', 'cooling_1_line', 'cooling_2_line', 'wait_counts'] as const;

export function EquipmentDetail({ log, onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-gray-800 rounded-xl w-full max-w-2xl max-h-[80vh] overflow-y-auto p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-white font-bold text-lg">{log.timestamp}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">✕</button>
        </div>

        <div className="mb-3">
          <span className={`px-2 py-1 rounded text-sm font-bold ${
            log.status === 'OK' ? 'bg-green-700 text-green-100' : 'bg-red-700 text-red-100'
          }`}>{log.status}</span>
          <p className="text-gray-300 text-sm mt-2">{log.reason}</p>
        </div>

        {Object.entries(log.equipment_data ?? {}).map(([eqId, eq]) => (
          <div key={eqId} className="mb-4 border border-gray-700 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-white font-semibold">{eqId}</span>
              {eq.ng_items?.length > 0 && (
                <span className="text-xs bg-red-800 text-red-200 px-2 py-0.5 rounded">NG</span>
              )}
            </div>
            {eq.ng_items?.length > 0 && (
              <ul className="mb-2">
                {eq.ng_items.map((item, i) => (
                  <li key={i} className="text-red-400 text-sm">• {item}</li>
                ))}
              </ul>
            )}
            {NUMERIC_FIELDS.map((field) => {
              const vals = eq[field];
              if (!vals?.length) return null;
              return (
                <div key={field} className="mb-1">
                  <span className="text-gray-400 text-xs">{field}: </span>
                  <span className="text-gray-300 text-xs">[{vals.join(', ')}]</span>
                </div>
              );
            })}
            {eq.color_reasoning && (
              <p className="text-gray-500 text-xs mt-1 italic">{eq.color_reasoning}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

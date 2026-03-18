import type { ClassifyResult } from '../api/types';
import './ResultTable.css';

interface Props {
  results: ClassifyResult[];
  onCodeClick: (code: string) => void;
}

export default function ResultTable({ results, onCodeClick }: Props) {
  if (results.length === 0) return null;

  return (
    <div className="result-table-wrap">
      {results.map((r, i) => (
        <div
          key={r.hsk_code}
          className="result-card"
          onClick={() => onCodeClick(r.hsk_code)}
          style={{ animationDelay: `${i * 0.06}s` }}
        >
          <div className="result-rank">
            <span className="rank-num">{r.rank}</span>
          </div>

          <div className="result-body">
            <div className="result-header">
              <code className="result-code">{r.hsk_code}</code>
              <div className="confidence-wrap">
                <div className="confidence-bar">
                  <div
                    className="confidence-fill"
                    style={{
                      width: `${r.confidence * 100}%`,
                      background: r.confidence > 0.7
                        ? 'linear-gradient(90deg, #22c55e, #4ade80)'
                        : r.confidence > 0.4
                          ? 'linear-gradient(90deg, #f59e0b, #fbbf24)'
                          : 'linear-gradient(90deg, #ef4444, #f87171)',
                    }}
                  />
                </div>
                <span className="confidence-value">{(r.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="result-names">
              <span className="name-kr">{r.name_kr}</span>
              {r.name_en && <span className="name-en">{r.name_en}</span>}
            </div>

            <p className="result-reason">{r.reason}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

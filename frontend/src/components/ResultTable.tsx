import type { ClassifyResult } from '../api/types';

interface Props {
  results: ClassifyResult[];
  onCodeClick: (code: string) => void;
}

export default function ResultTable({ results, onCodeClick }: Props) {
  if (results.length === 0) return null;

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 16 }}>
      <thead>
        <tr>
          <th>순위</th>
          <th>HSK 코드</th>
          <th>품목명</th>
          <th>신뢰도</th>
          <th>선정 사유</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr key={r.hsk_code} onClick={() => onCodeClick(r.hsk_code)} style={{ cursor: 'pointer' }}>
            <td>{r.rank}</td>
            <td style={{ fontFamily: 'monospace' }}>{r.hsk_code}</td>
            <td>{r.name_kr}{r.name_en ? ` (${r.name_en})` : ''}</td>
            <td>
              <div style={{ background: '#eee', borderRadius: 4, overflow: 'hidden', width: 100 }}>
                <div
                  style={{
                    width: `${r.confidence * 100}%`,
                    background: r.confidence > 0.7 ? '#4caf50' : r.confidence > 0.4 ? '#ff9800' : '#f44336',
                    height: 20,
                    textAlign: 'center',
                    color: '#fff',
                    fontSize: 12,
                    lineHeight: '20px',
                  }}
                >
                  {(r.confidence * 100).toFixed(0)}%
                </div>
              </div>
            </td>
            <td>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

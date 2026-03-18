import { useState } from 'react';
import { searchHsk, getHskCode } from '../api/client';
import type { HskCodeDetail } from '../api/types';
import HskTree from '../components/HskTree';

export default function BrowsePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<HskCodeDetail[]>([]);
  const [selected, setSelected] = useState<HskCodeDetail | null>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    const data = await searchHsk(query);
    setResults(data.results);
    setSelected(null);
  };

  const handleSelect = async (code: string) => {
    const detail = await getHskCode(code);
    setSelected(detail);
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 24 }}>
      <h1>HSK 코드 탐색</h1>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="코드 또는 품목명 검색"
          style={{ flex: 1, padding: 8 }}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button onClick={handleSearch} style={{ padding: '8px 24px' }}>검색</button>
      </div>

      <div style={{ display: 'flex', gap: 24, marginTop: 16 }}>
        <div style={{ flex: 1 }}>
          {results.map((r) => (
            <div key={r.code} onClick={() => handleSelect(r.code)} style={{ padding: 8, cursor: 'pointer', borderBottom: '1px solid #eee' }}>
              <code>{r.code}</code> {r.name_kr}
            </div>
          ))}
        </div>
        {selected && (
          <div style={{ flex: 1, border: '1px solid #ddd', padding: 16, borderRadius: 8 }}>
            <h3>{selected.name_kr}</h3>
            <p>코드: <code>{selected.code}</code></p>
            {selected.name_en && <p>영문: {selected.name_en}</p>}
            {selected.description && <p>{selected.description}</p>}
            {selected.children.length > 0 && (
              <>
                <h4>하위 코드</h4>
                <HskTree node={selected} onSelect={handleSelect} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

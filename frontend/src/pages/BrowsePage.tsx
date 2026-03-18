import { useState } from 'react';
import { searchHsk, getHskCode } from '../api/client';
import type { HskCodeDetail } from '../api/types';
import HskTree from '../components/HskTree';
import './BrowsePage.css';

export default function BrowsePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<HskCodeDetail[]>([]);
  const [selected, setSelected] = useState<HskCodeDetail | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    const data = await searchHsk(query);
    setResults(data.results);
    setSelected(null);
    setSearched(true);
  };

  const handleSelect = async (code: string) => {
    const detail = await getHskCode(code);
    setSelected(detail);
  };

  return (
    <div className="browse-page">
      <section className="browse-header">
        <h1 className="browse-title">HSK 코드 탐색</h1>
        <p className="browse-desc">품목명 또는 코드를 검색하여 HSK 분류 체계를 탐색합니다.</p>
      </section>

      <div className="search-bar">
        <svg className="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input
          className="search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="코드 또는 품목명 검색 (예: 배터리, 반도체, 8507)"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button className="search-btn" onClick={handleSearch}>검색</button>
      </div>

      <div className="browse-content">
        <div className="results-list">
          {searched && results.length === 0 && (
            <div className="no-results">검색 결과가 없습니다</div>
          )}
          {results.map((r, i) => (
            <div
              key={r.code}
              className={`browse-item ${selected?.code === r.code ? 'active' : ''}`}
              onClick={() => handleSelect(r.code)}
              style={{ animationDelay: `${i * 0.03}s` }}
            >
              <code className="browse-code">{r.code}</code>
              <span className="browse-name">{r.name_kr}</span>
              <span className="browse-level">L{r.level}</span>
            </div>
          ))}
        </div>

        {selected && (
          <div className="detail-panel">
            <div className="detail-header">
              <code className="detail-code">{selected.code}</code>
              <span className="detail-level">Level {selected.level}</span>
            </div>
            <h2 className="detail-name">{selected.name_kr}</h2>
            {selected.name_en && <p className="detail-name-en">{selected.name_en}</p>}
            {selected.description && <p className="detail-desc">{selected.description}</p>}

            {selected.parent_code && (
              <div className="detail-parent">
                <span className="detail-meta-label">상위 코드</span>
                <button className="parent-link" onClick={() => handleSelect(selected.parent_code!)}>
                  {selected.parent_code}
                </button>
              </div>
            )}

            {selected.children.length > 0 && (
              <div className="detail-children">
                <span className="detail-meta-label">하위 코드 ({selected.children.length})</span>
                <div className="children-list">
                  <HskTree node={selected} onSelect={handleSelect} />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

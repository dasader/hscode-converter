import React, { useState, useEffect } from 'react';
import axios from 'axios';
import * as XLSX from 'xlsx';
import { classifyStream } from '../api/client';
import type { ClassifyResponse } from '../api/types';
import ResultTable from '../components/ResultTable';
import BatchTab from '../components/BatchTab';
import './ClassifyPage.css';

export default function ClassifyPage() {
  const [activeTab, setActiveTab] = useState<'single' | 'batch'>('single');
  const [description, setDescription] = useState('');
  const [topN, setTopN] = useState(5);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<ClassifyResponse | null>(null);
  const [error, setError] = useState('');
  const [pipelineStep, setPipelineStep] = useState<string | null>(null);
  const [dataStatus, setDataStatus] = useState<{ state: string; message: string } | null>(null);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const { data } = await axios.get('/api/v1/data/status');
        setDataStatus(data);
        if (data.state !== 'ready' && data.state !== 'error' && data.state !== 'no_data') {
          setTimeout(checkStatus, 3000);
        }
      } catch {
        setTimeout(checkStatus, 3000);
      }
    };
    checkStatus();
  }, []);

  const isReady = dataStatus?.state === 'ready';
  const charCount = description.length;

  const handleSubmit = async () => {
    if (description.trim().length < 10) {
      setError('기술 설명은 최소 10자 이상이어야 합니다');
      return;
    }
    setLoading(true);
    setError('');
    setResponse(null);
    setPipelineStep(null);
    try {
      const result = await classifyStream(
        { description, top_n: topN },
        (step) => setPipelineStep(step),
      );
      setResponse(result);
    } catch (e: any) {
      setError(e.message || '분류 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
      setPipelineStep(null);
    }
  };

  const filteredResults = response
    ? response.results.filter(r => r.confidence * 100 >= confidenceThreshold)
    : null;

  const sliderPct = confidenceThreshold;
  const [copied, setCopied] = useState(false);

  const handleCopyAllCodes = async () => {
    if (!filteredResults || filteredResults.length === 0) return;
    const codes = filteredResults.map(r => r.hsk_code.replace(/[.\-\s]/g, '')).join(', ');
    await navigator.clipboard.writeText(codes);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExcelDownload = () => {
    if (!response || !filteredResults || filteredResults.length === 0) return;
    const wb = XLSX.utils.book_new();

    // 분석 결과 시트
    const resultRows = filteredResults.map(r => ({
      '순위': r.rank,
      'HS코드': r.hsk_code,
      '품목명(한글)': r.name_kr,
      '품목명(영문)': r.name_en || '',
      '신뢰도(%)': Math.round(r.confidence * 100),
      '판단 근거': r.reason,
    }));
    const wsResult = XLSX.utils.json_to_sheet(resultRows);
    // 컬럼 너비 설정
    wsResult['!cols'] = [
      { wch: 6 }, { wch: 16 }, { wch: 30 }, { wch: 30 }, { wch: 10 }, { wch: 50 },
    ];
    XLSX.utils.book_append_sheet(wb, wsResult, '분류 결과');

    // 분석 요약 시트
    const summaryRows = [
      { '항목': '기술 설명', '내용': description },
      { '항목': '추출 키워드', '내용': response.keywords_extracted.join(', ') },
      { '항목': '처리 시간', '내용': `${(response.processing_time_ms / 1000).toFixed(1)}초` },
      { '항목': '결과 수', '내용': `${filteredResults.length}건` },
      { '항목': '최소 신뢰도 필터', '내용': `${confidenceThreshold}%` },
    ];
    const wsSummary = XLSX.utils.json_to_sheet(summaryRows);
    wsSummary['!cols'] = [{ wch: 18 }, { wch: 80 }];
    XLSX.utils.book_append_sheet(wb, wsSummary, '분석 요약');

    XLSX.writeFile(wb, `HS코드_분류결과_${new Date().toISOString().slice(0, 10)}.xlsx`);
  };

  return (
    <div className="classify-page">
      {/* Hero section */}
      <section className="hero-section">
        <div className="hero-badge">R&D Technology Classification</div>
        <h1 className="hero-title">
          기술 설명에서<br />
          <span className="hero-accent">HS 코드</span>를 찾아드립니다
        </h1>
        <p className="hero-desc">
          연구개발 기술을 자연어로 입력하면, AI가 관련 HSK 10자리 코드를 분석하여 제안합니다.
        </p>
      </section>

      {/* Status banner */}
      {dataStatus && !isReady && (
        <div className={`status-banner status-${dataStatus.state}`}>
          <div className="status-icon">
            {(dataStatus.state === 'loading' || dataStatus.state === 'embedding') && (
              <span className="status-spinner" />
            )}
            {dataStatus.state === 'error' && <span>!</span>}
            {dataStatus.state === 'no_data' && <span>?</span>}
          </div>
          <div className="status-text">
            <strong>{dataStatus.state === 'loading' ? '데이터 로드 중' : dataStatus.state === 'embedding' ? '임베딩 생성 중' : dataStatus.state === 'error' ? '오류 발생' : '데이터 없음'}</strong>
            <span>{dataStatus.message}</span>
          </div>
        </div>
      )}

      {/* Tab selector */}
      <div className="tab-selector">
        <button className={`tab-btn ${activeTab === 'single' ? 'active' : ''}`} onClick={() => setActiveTab('single')}>단건 분류</button>
        <button className={`tab-btn ${activeTab === 'batch' ? 'active' : ''}`} onClick={() => setActiveTab('batch')}>배치 분류</button>
      </div>

      {activeTab === 'single' ? (
        <>
          {/* Input section */}
          <section className="input-section">
            <div className="input-card">
              <div className="input-header">
                <label className="input-label">기술 설명</label>
                <span className="char-count">{charCount} / 2,000</span>
              </div>
              <textarea
                className="input-textarea"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="분석할 R&D 기술을 설명해주세요...&#10;&#10;예: 리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술"
                rows={6}
                maxLength={2000}
              />
              <div className="input-footer">
                <div className="topn-control">
                  <label className="topn-label">결과 수</label>
                  <div className="topn-selector">
                    {[3, 5, 10, 15, 20].map(n => (
                      <button
                        key={n}
                        className={`topn-btn ${topN === n ? 'active' : ''}`}
                        onClick={() => setTopN(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="confidence-control">
                  <label className="topn-label">최소 신뢰도</label>
                  <input
                    type="range"
                    className="confidence-slider"
                    min={0}
                    max={100}
                    step={10}
                    value={confidenceThreshold}
                    onChange={(e) => setConfidenceThreshold(Number(e.target.value))}
                    style={{ '--slider-pct': `${sliderPct}%` } as React.CSSProperties}
                  />
                  <span className="confidence-value">{confidenceThreshold}%</span>
                </div>

                <button
                  className={`submit-btn ${loading ? 'loading' : ''}`}
                  onClick={handleSubmit}
                  disabled={loading || !isReady}
                >
                  {loading ? (
                    <>
                      <span className="submit-spinner" />
                      분석 중...
                    </>
                  ) : (
                    <>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
                      </svg>
                      분류하기
                    </>
                  )}
                </button>
              </div>
            </div>
          </section>

          {/* Error */}
          {error && (
            <div className="error-msg">{error}</div>
          )}

          {/* Pipeline indicator */}
          {loading && (() => {
            const steps = ['keyword_extraction', 'vector_search', 'reranking'] as const;
            const labels = { keyword_extraction: '키워드 추출', vector_search: '벡터 검색', reranking: '리랭킹' };
            const currentIdx = pipelineStep ? steps.indexOf(pipelineStep as typeof steps[number]) : -1;
            return (
              <div className="pipeline-indicator">
                <div className="pipeline-steps">
                  {steps.map((step, i) => (
                    <React.Fragment key={step}>
                      {i > 0 && <div className={`pipeline-line${i <= currentIdx ? ' done' : ''}`} />}
                      <div className={`pipeline-step${i === currentIdx ? ' active' : ''}${i < currentIdx ? ' done' : ''}`}>
                        <div className="step-dot" />
                        <span>{labels[step]}</span>
                      </div>
                    </React.Fragment>
                  ))}
                </div>
                <p className="pipeline-note">AI가 기술 설명을 분석하고 있습니다...</p>
              </div>
            );
          })()}

          {/* Results */}
          {response && filteredResults && (
            <section className="results-section">
              <div className="results-meta">
                <div className="meta-item">
                  <span className="meta-label">추출 키워드</span>
                  <div className="keyword-tags">
                    {response.keywords_extracted.map((kw, i) => (
                      <span key={i} className="keyword-tag">{kw}</span>
                    ))}
                  </div>
                </div>
                <div className="meta-actions">
                  <div className="meta-stat">
                    <span className="stat-value">{(response.processing_time_ms / 1000).toFixed(1)}s</span>
                    <span className="stat-label">처리 시간</span>
                  </div>
                  <button className="copy-codes-btn" onClick={handleCopyAllCodes}>
                    {copied ? (
                      <>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                        복사됨
                      </>
                    ) : (
                      <>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="0"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                        HS코드 복사
                      </>
                    )}
                  </button>
                  <button className="export-excel-btn" onClick={handleExcelDownload}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    엑셀 다운로드
                  </button>
                </div>
              </div>
              <ResultTable results={filteredResults} onCodeClick={(code) => alert(`상세 보기: ${code}`)} />
            </section>
          )}
        </>
      ) : (
        <BatchTab isReady={isReady} />
      )}
    </div>
  );
}

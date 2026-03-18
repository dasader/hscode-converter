import { useState, useRef, useEffect, useCallback } from 'react';
import {
  downloadTemplate, uploadBatch, subscribeBatchProgress,
  downloadBatchResult, retryBatchFailed,
} from '../api/client';
import type { BatchProgressEvent } from '../api/types';
import './BatchTab.css';

const MODEL_OPTIONS = [
  { value: 'chatgpt-5.4-nano', label: 'GPT-5.4 Nano (빠름)' },
  { value: 'chatgpt-5.4-mini', label: 'GPT-5.4 Mini (균형)' },
  { value: 'chatgpt-5.4',      label: 'GPT-5.4 (정확)' },
];

interface Props {
  isReady: boolean;
}

type FilterMode = 'topn' | 'confidence';
type Phase = 'idle' | 'uploading' | 'processing' | 'complete';

export default function BatchTab({ isReady }: Props) {
  const [filterMode, setFilterMode] = useState<FilterMode>('topn');
  const [topN, setTopN] = useState(5);
  const [confidenceValue, setConfidenceValue] = useState(70);
  const [model, setModel] = useState('chatgpt-5.4-mini');
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ completed: 0, failed: 0, total: 0, percent: 0 });
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanupSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => () => cleanupSSE(), [cleanupSSE]);

  const handleTemplate = async () => {
    const blob = await downloadTemplate();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'HSCode_배치분류_템플릿.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileSelect = (selected: File | null) => {
    if (selected && selected.name.endsWith('.xlsx')) {
      setFile(selected);
      setError('');
    } else if (selected) {
      setError('.xlsx 파일만 지원합니다');
    }
  };

  const connectSSE = (jId: string) => {
    cleanupSSE();
    const es = subscribeBatchProgress(jId);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      const data: BatchProgressEvent = JSON.parse(event.data);
      if (data.type === 'progress') {
        setProgress({
          completed: data.completed ?? 0, failed: data.failed ?? 0,
          total: data.total ?? 0, percent: data.percent ?? 0,
        });
      } else if (data.type === 'complete') {
        setProgress({
          completed: data.completed ?? 0, failed: data.failed ?? 0,
          total: data.total ?? 0, percent: 100,
        });
        setPhase('complete');
        cleanupSSE();
      }
    };
  };

  const handleUpload = async () => {
    if (!file) return;
    setPhase('uploading');
    setError('');
    try {
      const threshold = filterMode === 'confidence' ? confidenceValue : null;
      const result = await uploadBatch(file, topN, threshold, model);
      setJobId(result.job_id);
      setProgress({ completed: 0, failed: 0, total: result.total_items, percent: 0 });
      setPhase('processing');
      setStartTime(Date.now());
      connectSSE(result.job_id);
    } catch (e: any) {
      setError(e.response?.data?.detail || '업로드 중 오류가 발생했습니다');
      setPhase('idle');
    }
  };

  const handleDownload = async () => {
    if (!jobId) return;
    const blob = await downloadBatchResult(jobId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${file?.name?.replace('.xlsx', '') || 'batch'}_결과.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRetry = async () => {
    if (!jobId) return;
    await retryBatchFailed(jobId);
    setPhase('processing');
    setStartTime(Date.now());
    connectSSE(jobId);
  };

  const getETA = () => {
    if (!startTime || progress.percent <= 0) return '';
    const elapsed = (Date.now() - startTime) / 1000;
    const remaining = (elapsed / progress.percent) * (100 - progress.percent);
    if (remaining < 60) return `약 ${Math.ceil(remaining)}초 남음`;
    return `약 ${Math.ceil(remaining / 60)}분 남음`;
  };

  return (
    <div className="batch-tab">
      {/* Config Card */}
      <div className="batch-config-card">
        <div className="batch-config-header">
          <span className="batch-config-label">배치 설정</span>
        </div>
        <div className="batch-config-body">
          <div className="batch-field">
            <span className="batch-field-label">필터링</span>
            <div className="filter-toggle">
              <button className={filterMode === 'topn' ? 'active' : ''} onClick={() => setFilterMode('topn')}>상위 N개</button>
              <button className={filterMode === 'confidence' ? 'active' : ''} onClick={() => setFilterMode('confidence')}>신뢰도 기준</button>
            </div>
          </div>
          <div className="batch-field">
            <span className="batch-field-label">{filterMode === 'topn' ? '결과 수' : '최소 신뢰도(%)'}</span>
            <input
              type="number"
              className="batch-input"
              min={filterMode === 'topn' ? 1 : 0}
              max={filterMode === 'topn' ? 20 : 100}
              step={filterMode === 'topn' ? 1 : 5}
              value={filterMode === 'topn' ? topN : confidenceValue}
              onChange={(e) => filterMode === 'topn' ? setTopN(Number(e.target.value)) : setConfidenceValue(Number(e.target.value))}
            />
          </div>
          <div className="batch-field">
            <span className="batch-field-label">모델</span>
            <select className="model-selector" value={model} onChange={(e) => setModel(e.target.value)}>
              {MODEL_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Upload */}
      {phase === 'idle' && (
        <>
          {!file ? (
            <div
              className={`upload-zone ${dragOver ? 'dragover' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFileSelect(e.dataTransfer.files[0]); }}
            >
              <input ref={fileInputRef} type="file" accept=".xlsx" onChange={(e) => handleFileSelect(e.target.files?.[0] || null)} />
              <div className="upload-icon-wrap">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <div className="upload-title">엑셀 파일을 드래그하거나 클릭하여 업로드</div>
              <div className="upload-desc">.xlsx 형식, 최대 500건</div>
            </div>
          ) : (
            <div className="file-preview">
              <div className="file-info">
                <div className="file-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </div>
                <div className="file-meta">
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{(file.size / 1024).toFixed(1)} KB</span>
                </div>
              </div>
              <button className="remove-file" onClick={() => setFile(null)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          )}
          <div className="batch-actions">
            <button className="template-btn" onClick={handleTemplate}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              템플릿 다운로드
            </button>
            <button className="upload-btn" onClick={handleUpload} disabled={!file || !isReady}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="13 17 18 12 13 7" /><polyline points="6 17 11 12 6 7" />
              </svg>
              배치 분류 시작
            </button>
          </div>
        </>
      )}

      {/* Progress */}
      {(phase === 'uploading' || phase === 'processing') && (
        <div className="progress-section">
          <div className="progress-header">
            <span className="progress-title">{phase === 'uploading' ? '업로드 중' : '처리 중'}</span>
            <div className="progress-stats">
              <span className="success">{progress.completed} 성공</span>
              <span className="fail">{progress.failed} 실패</span>
              <span>/ {progress.total}</span>
            </div>
          </div>
          <div className="progress-body">
            <div className="progress-percent">
              {progress.percent.toFixed(1)}<span>%</span>
            </div>
            <div className="progress-bar-track">
              <div className="progress-bar-fill" style={{ width: `${progress.percent}%` }} />
            </div>
            <div className="progress-eta">{getETA()}</div>
          </div>
        </div>
      )}

      {/* Result */}
      {phase === 'complete' && (
        <div className="result-section">
          <div className="result-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div className="result-summary">
            배치 분류가 완료되었습니다
          </div>
          <div className="result-detail">
            <span className="result-success">{progress.completed}건 성공</span>
            {progress.failed > 0 && <> · <span className="result-fail">{progress.failed}건 실패</span></>}
            {' '}/ 전체 {progress.total}건
          </div>
          <div className="result-actions">
            <button className="download-btn" onClick={handleDownload}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              결과 엑셀 다운로드
            </button>
            {progress.failed > 0 && (
              <button className="retry-btn" onClick={handleRetry}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
                실패 건 재시도 ({progress.failed}건)
              </button>
            )}
          </div>
        </div>
      )}

      {error && <div className="error-msg">{error}</div>}
    </div>
  );
}

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
      <div className="batch-config">
        <div className="batch-field">
          <label>필터링 모드</label>
          <div className="filter-toggle">
            <button className={filterMode === 'topn' ? 'active' : ''} onClick={() => setFilterMode('topn')}>상위 N개</button>
            <button className={filterMode === 'confidence' ? 'active' : ''} onClick={() => setFilterMode('confidence')}>신뢰도 기준</button>
          </div>
        </div>
        <div className="batch-field">
          <label>{filterMode === 'topn' ? '결과 수' : '최소 신뢰도(%)'}</label>
          {filterMode === 'topn' ? (
            <input type="number" className="batch-input" min={1} max={20} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
          ) : (
            <input type="number" className="batch-input" min={0} max={100} step={5} value={confidenceValue} onChange={(e) => setConfidenceValue(Number(e.target.value))} />
          )}
        </div>
        <div className="batch-field">
          <label>모델</label>
          <select className="model-selector" value={model} onChange={(e) => setModel(e.target.value)}>
            {MODEL_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </div>
      </div>

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
              <div className="upload-icon">+</div>
              <div className="upload-title">엑셀 파일을 드래그하거나 클릭하여 업로드</div>
              <div className="upload-desc">.xlsx 형식, 최대 500건</div>
            </div>
          ) : (
            <div className="file-preview">
              <div className="file-info">
                <span className="file-name">{file.name}</span>
                <span className="file-count">{(file.size / 1024).toFixed(1)} KB</span>
              </div>
              <button className="remove-file" onClick={() => setFile(null)}>x</button>
            </div>
          )}
          <div className="batch-actions">
            <button className="template-btn" onClick={handleTemplate}>템플릿 다운로드</button>
            <button className="upload-btn" onClick={handleUpload} disabled={!file || !isReady || phase !== 'idle'}>배치 분류 시작</button>
          </div>
        </>
      )}

      {(phase === 'uploading' || phase === 'processing') && (
        <div className="progress-section">
          <div className="progress-header">
            <span className="progress-title">{phase === 'uploading' ? '업로드 중...' : '처리 중...'}</span>
            <div className="progress-stats">
              <span className="success">성공 {progress.completed}</span>
              <span className="fail">실패 {progress.failed}</span>
              <span>/ 전체 {progress.total}</span>
            </div>
          </div>
          <div className="progress-percent">{progress.percent.toFixed(1)}%</div>
          <div className="progress-bar-container">
            <div className="progress-bar-fill" style={{ width: `${progress.percent}%` }} />
          </div>
          <div className="progress-eta">{getETA()}</div>
        </div>
      )}

      {phase === 'complete' && (
        <div className="result-section">
          <div className="result-summary">
            처리 완료: <strong>{progress.completed}건</strong> 성공, <strong>{progress.failed}건</strong> 실패
          </div>
          <div className="result-actions">
            <button className="download-btn" onClick={handleDownload}>결과 엑셀 다운로드</button>
            {progress.failed > 0 && (
              <button className="retry-btn" onClick={handleRetry}>실패 건 재시도 ({progress.failed}건)</button>
            )}
          </div>
        </div>
      )}

      {error && <div className="error-msg">{error}</div>}
    </div>
  );
}

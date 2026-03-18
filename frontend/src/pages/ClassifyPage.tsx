import { useState } from 'react';
import { classify } from '../api/client';
import type { ClassifyResponse } from '../api/types';
import ResultTable from '../components/ResultTable';

export default function ClassifyPage() {
  const [description, setDescription] = useState('');
  const [topN, setTopN] = useState(5);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState('');
  const [response, setResponse] = useState<ClassifyResponse | null>(null);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (description.trim().length < 10) {
      setError('기술 설명은 최소 10자 이상이어야 합니다');
      return;
    }
    setLoading(true);
    setError('');
    setResponse(null);
    setStep('분류 처리 중...');
    try {
      const result = await classify({ description, top_n: topN });
      setResponse(result);
    } catch (e: any) {
      setError(e.response?.data?.detail || '분류 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
      setStep('');
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 24 }}>
      <h1>HSCode Connector</h1>
      <p>R&D 기술 설명을 입력하면 관련 HSK 코드를 찾아드립니다.</p>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="기술 설명을 입력하세요 (예: 리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술)"
        rows={5}
        style={{ width: '100%', fontSize: 14, padding: 8 }}
        maxLength={2000}
      />

      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 16 }}>
        <label>
          Top N: {topN}
          <input
            type="range"
            min={1}
            max={20}
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            style={{ marginLeft: 8 }}
          />
        </label>
        <button onClick={handleSubmit} disabled={loading} style={{ padding: '8px 24px' }}>
          {loading ? step : '분류하기'}
        </button>
      </div>

      {error && <p style={{ color: 'red', marginTop: 8 }}>{error}</p>}

      {response && (
        <>
          <p style={{ marginTop: 16, color: '#666' }}>
            추출된 키워드: {response.keywords_extracted.join(', ')} |
            처리 시간: {response.processing_time_ms}ms
          </p>
          <ResultTable results={response.results} onCodeClick={(code) => alert(`상세 보기: ${code}`)} />
        </>
      )}
    </div>
  );
}

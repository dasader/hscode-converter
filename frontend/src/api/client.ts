import axios from 'axios';
import type { ClassifyRequest, ClassifyResponse, HskCodeDetail, HskSearchResult, BatchUploadResponse, BatchJob } from './types';

const api = axios.create({ baseURL: '/api/v1' });

export async function classify(request: ClassifyRequest): Promise<ClassifyResponse> {
  const { data } = await api.post<ClassifyResponse>('/classify', request);
  return data;
}

export function classifyStream(
  request: ClassifyRequest,
  onStep: (step: string) => void,
): Promise<ClassifyResponse> {
  return new Promise((resolve, reject) => {
    fetch('/api/v1/classify/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }).then(res => {
      if (!res.ok) {
        res.json().then(err => reject(new Error(err.detail || '분류 중 오류가 발생했습니다'))).catch(() => reject(new Error('분류 중 오류가 발생했습니다')));
        return;
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const read = (): void => {
        reader.read().then(({ done, value }) => {
          if (done) return;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop()!;
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const parsed = JSON.parse(line.slice(6));
            if (parsed.type === 'step') onStep(parsed.step);
            else if (parsed.type === 'result') resolve(parsed.data);
          }
          read();
        }).catch(reject);
      };
      read();
    }).catch(reject);
  });
}

export async function getHskCode(code: string): Promise<HskCodeDetail> {
  const { data } = await api.get<HskCodeDetail>(`/hsk/${code}`);
  return data;
}

export async function searchHsk(q: string, limit = 20): Promise<HskSearchResult> {
  const { data } = await api.get<HskSearchResult>('/hsk/search', { params: { q, limit } });
  return data;
}

export async function downloadTemplate(): Promise<Blob> {
  const { data } = await api.get('/batch/template', { responseType: 'blob' });
  return data;
}

export async function uploadBatch(
  file: File,
  topN: number,
  confidenceThreshold: number | null,
): Promise<BatchUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('top_n', String(topN));
  if (confidenceThreshold !== null) {
    formData.append('confidence_threshold', String(confidenceThreshold / 100));
  }
  const { data } = await api.post<BatchUploadResponse>('/batch/upload', formData);
  return data;
}

export function subscribeBatchProgress(jobId: string): EventSource {
  return new EventSource(`/api/v1/batch/${jobId}/progress`);
}

export async function downloadBatchResult(jobId: string): Promise<Blob> {
  const { data } = await api.get(`/batch/${jobId}/download`, { responseType: 'blob' });
  return data;
}

export async function retryBatchFailed(jobId: string): Promise<{ retried: number }> {
  const { data } = await api.post(`/batch/${jobId}/retry`);
  return data;
}

export async function listBatchJobs(): Promise<{ jobs: BatchJob[] }> {
  const { data } = await api.get('/batch/jobs');
  return data;
}

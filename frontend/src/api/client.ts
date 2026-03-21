import axios from 'axios';
import type { ClassifyRequest, ClassifyResponse, HskCodeDetail, HskSearchResult, BatchUploadResponse, BatchJob } from './types';

const api = axios.create({ baseURL: '/api/v1' });

export async function classify(request: ClassifyRequest): Promise<ClassifyResponse> {
  const { data } = await api.post<ClassifyResponse>('/classify', request);
  return data;
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

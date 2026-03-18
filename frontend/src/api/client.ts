import axios from 'axios';
import type { ClassifyRequest, ClassifyResponse, HskCodeDetail, HskSearchResult } from './types';

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

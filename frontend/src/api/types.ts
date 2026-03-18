export interface ClassifyRequest {
  description: string;
  top_n: number;
  model?: string;
}

export interface ClassifyResult {
  rank: number;
  hsk_code: string;
  name_kr: string;
  name_en: string | null;
  confidence: number;
  reason: string;
}

export interface ClassifyResponse {
  results: ClassifyResult[];
  keywords_extracted: string[];
  processing_time_ms: number;
}

export interface HskCodeDetail {
  code: string;
  formatted_code: string;
  name_kr: string;
  name_en: string | null;
  level: number;
  parent_code: string | null;
  description: string | null;
  children: HskCodeDetail[];
}

export interface HskSearchResult {
  results: HskCodeDetail[];
  total: number;
}

export interface BatchUploadResponse {
  job_id: string;
  total_items: number;
  status: string;
}

export interface BatchJob {
  job_id: string;
  file_name: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  top_n: number;
  confidence_threshold: number | null;
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface BatchProgressEvent {
  type: 'progress' | 'item_done' | 'complete' | 'heartbeat';
  completed?: number;
  failed?: number;
  total?: number;
  percent?: number;
  row_index?: number;
  status?: string;
  hsk_code_1?: string;
  confidence_1?: number;
  error?: string;
}

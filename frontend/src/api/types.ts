export interface ClassifyRequest {
  description: string;
  top_n: number;
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

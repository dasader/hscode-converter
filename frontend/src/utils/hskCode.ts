/** 숫자 HSK 코드를 표시 형식(8507.60-1000)으로 변환한다. 백엔드 format_code와 동일 규칙. */
export function formatHskCode(code: string): string {
  code = code.trim();
  if (code.length <= 2) return code;
  if (code.length === 4) return `${code.slice(0, 2)}.${code.slice(2)}`;
  if (code.length === 6) return `${code.slice(0, 4)}.${code.slice(4)}`;
  if (code.length >= 8) return `${code.slice(0, 4)}.${code.slice(4, 6)}-${code.slice(6)}`;
  return code;
}

/** 표시 형식 코드에서 구분자(. - 공백)를 제거해 raw 숫자 코드로 되돌린다. */
export function stripHskCode(code: string): string {
  return code.replace(/[.\-\s]/g, '');
}

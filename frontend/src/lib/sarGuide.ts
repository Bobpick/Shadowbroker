export const SAR_GUIDE_EVENT = 'sb:sar-guide-request';

export interface SarGuideDetail {
  lat?: number;
  lng?: number;
  openAoiEditor?: boolean;
}

export function requestSarGuide(detail?: SarGuideDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<SarGuideDetail>(SAR_GUIDE_EVENT, { detail: detail ?? {} }));
}
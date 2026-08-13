export type OnboardingScrollMode = 'none' | 'bottom' | 'auto' | 'preserve';

export interface ReviewScrollAnchor {
  proposalId: string;
  viewportTop: number;
}

function proposalElement(container: HTMLElement, proposalId: string): HTMLElement | null {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-proposal-id]'))
    .find((element) => element.dataset['proposalId'] === proposalId) || null;
}

export function captureReviewScrollAnchor(
  container: HTMLElement | undefined,
  proposalId: string,
): ReviewScrollAnchor | null {
  if (!container) return null;
  const element = proposalElement(container, proposalId);
  return element ? { proposalId, viewportTop: element.getBoundingClientRect().top } : null;
}

export function restoreReviewScrollAnchor(
  container: HTMLElement | undefined,
  anchor: ReviewScrollAnchor | null | undefined,
): boolean {
  if (!container || !anchor) return false;
  const element = proposalElement(container, anchor.proposalId);
  if (!element) return false;
  const delta = element.getBoundingClientRect().top - anchor.viewportTop;
  if (Math.abs(delta) > 0.5) container.scrollTop += delta;
  return true;
}

export function isNearScrollBottom(container: HTMLElement | undefined, threshold = 120): boolean {
  if (!container) return false;
  return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
}

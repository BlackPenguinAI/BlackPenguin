import {
  captureReviewScrollAnchor,
  isNearScrollBottom,
  restoreReviewScrollAnchor,
} from './review-scroll-anchor';

describe('review scroll anchor', () => {
  it('restores the same proposal to its previous viewport position', () => {
    const container = document.createElement('div');
    const proposal = document.createElement('div');
    proposal.dataset['proposalId'] = 'proposal-1';
    container.appendChild(proposal);
    container.scrollTop = 300;

    let proposalTop = 180;
    proposal.getBoundingClientRect = () => ({ top: proposalTop } as DOMRect);
    const anchor = captureReviewScrollAnchor(container, 'proposal-1');
    proposalTop = 245;

    expect(restoreReviewScrollAnchor(container, anchor)).toBe(true);
    expect(container.scrollTop).toBe(365);
  });

  it('does nothing when the proposal is no longer rendered', () => {
    const container = document.createElement('div');
    expect(restoreReviewScrollAnchor(container, {
      proposalId: 'missing', viewportTop: 100,
    })).toBe(false);
    expect(container.scrollTop).toBe(0);
  });

  it('only considers the viewport near the bottom within the threshold', () => {
    const container = document.createElement('div');
    Object.defineProperties(container, {
      scrollHeight: { value: 1000 },
      clientHeight: { value: 400 },
    });
    container.scrollTop = 490;
    expect(isNearScrollBottom(container, 120)).toBe(true);
    container.scrollTop = 300;
    expect(isNearScrollBottom(container, 120)).toBe(false);
  });
});

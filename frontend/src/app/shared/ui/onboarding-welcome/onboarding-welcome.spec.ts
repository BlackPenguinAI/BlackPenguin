import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { normalizeOnboardingUrl, OnboardingWelcomeComponent } from './onboarding-welcome';

describe('OnboardingWelcomeComponent URL entry', () => {
  it('adds HTTPS to www and bare public hostnames before validation', () => {
    expect(normalizeOnboardingUrl('www.fouquetsmiami.com')).toBe('https://www.fouquetsmiami.com');
    expect(normalizeOnboardingUrl('fouquetsmiami.com/residences')).toBe('https://fouquetsmiami.com/residences');
  });

  it('emits the normalized URL instead of rejecting a missing scheme', () => {
    const component = new OnboardingWelcomeComponent();
    const emitted = vi.fn();
    component.continueWithUrl.subscribe(emitted);
    component.url = 'www.fouquetsmiami.com';

    component.submit();

    expect(component.valid).toBe(true);
    expect(component.url).toBe('https://www.fouquetsmiami.com');
    expect(emitted).toHaveBeenCalledWith('https://www.fouquetsmiami.com');
  });

  it('continues to reject unsupported URL schemes', () => {
    const component = new OnboardingWelcomeComponent();
    component.url = 'javascript:alert(1)';
    component.submit();
    expect(component.valid).toBe(false);
  });
});

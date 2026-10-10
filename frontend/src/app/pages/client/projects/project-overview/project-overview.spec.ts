import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { ProjectOverviewComponent } from './project-overview';

describe('ProjectOverviewComponent presentation', () => {
  it('forces the embedded Google Map controls to English', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'admin' });
    const sanitizer = { bypassSecurityTrustResourceUrl: (value: string) => value };
    const component = new ProjectOverviewComponent(
      { snapshot: { paramMap: { get: () => 'project-1' } } } as never,
      {} as never,
      { detectChanges: () => undefined } as never,
      sanitizer as never,
    );

    const url = (component as any).buildMapUrl({
      location: { address: '5000 Biscayne Blvd, Miami, FL', latitude: null, longitude: null },
    });

    expect(url).toContain('output=embed');
    expect(url).toContain('hl=en');
    expect(url).toContain('5000%20Biscayne');
  });

  it('uses the backend-normalized location instead of rebuilding duplicate context', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'admin' });
    const component = new ProjectOverviewComponent({} as never, {} as never, {} as never, {} as never);
    component.overview = {
      address: '5000 Biscayne Blvd, Miami, United States', city: 'Miami', country: 'United States',
      location: { address: '5000 Biscayne Blvd, Miami, United States', latitude: null, longitude: null },
    } as never;

    expect(component.locationLabel).toBe('5000 Biscayne Blvd, Miami, United States');
  });
});

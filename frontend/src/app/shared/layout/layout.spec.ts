import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it } from 'vitest';
import { LayoutComponent } from './layout';

describe('LayoutComponent identity', () => {
  it('shows server-backed name, role and company', () => {
    const component = new LayoutComponent(
      { events: of(), navigate: () => undefined } as any,
      { getMyProfile: () => of({ first_name: 'Taylor', last_name: 'Morgan', role: 'sales', company_name: 'Acme Homes' }) } as any,
      { use: () => undefined } as any,
      { detectChanges: () => undefined } as any,
    );
    component.ngOnInit();
    expect(component.displayName).toBe('Taylor Morgan');
    expect(component.roleLabel).toBe('Sales');
    expect(component.identityScope).toBe('Acme Homes');
  });
});

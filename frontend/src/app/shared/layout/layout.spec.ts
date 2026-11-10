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
      { get: () => of({ count: 0 }) } as any,
    );
    component.ngOnInit();
    expect(component.displayName).toBe('Taylor Morgan');
    expect(component.roleLabel).toBe('Sales');
    expect(component.identityScope).toBe('Acme Homes');
  });
});

 it('uses a contained workspace only for Project onboarding routes',()=>{
   const router={url:'/app/projects/project/onboarding',events:of(),navigate:()=>undefined};
   const c=new LayoutComponent(router as any,{} as any,{use:()=>undefined} as any,{detectChanges:()=>undefined} as any,{} as any);
   expect(c.isProjectOnboarding).toBe(true);
   router.url='/app/projects/project/onboarding/?task=location';expect(c.isProjectOnboarding).toBe(true);
   for(const url of ['/app/projects','/app/dashboard','/app/schedule','/app/projects/project']){router.url=url;expect(c.isProjectOnboarding).toBe(false);}
 });

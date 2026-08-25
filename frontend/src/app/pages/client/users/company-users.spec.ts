import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { CompanyUsersComponent } from './company-users';

describe('CompanyUsersComponent', () => {
  it('requires matching passwords before adding a user', () => {
    const component = new CompanyUsersComponent({} as any, {} as any, {} as any);
    component.invite = {
      first_name: 'Ana', last_name: 'Sales', email: 'ana@example.com', role: 'sales',
      password: '1234', is_active: true,
    };
    component.repeatPassword = 'wrong';
    expect(component.formValid).toBe(false);
    component.repeatPassword = '1234';
    expect(component.formValid).toBe(true);
  });
});

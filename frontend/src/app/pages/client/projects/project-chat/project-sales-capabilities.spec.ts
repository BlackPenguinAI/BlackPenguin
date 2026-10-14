import { describe, expect, it } from 'vitest';

import { ProjectAssignment, ProjectSalesCandidate } from './project-onboarding.models';
import { availableProjectSalesCandidates, companyAdministratorSalesCandidate } from './project-sales-capabilities';

describe('Project Sales capabilities', () => {
  const users: ProjectSalesCandidate[] = [
    { id: 'admin-1', email: 'admin@example.com', role: 'admin', is_active: true },
    { id: 'sales-1', email: 'sales@example.com', role: 'sales', is_active: true },
    { id: 'sales-disabled', email: 'disabled@example.com', role: 'sales', is_active: false },
  ];

  it('offers the active Company administrator without requiring another Sales user', () => {
    expect(companyAdministratorSalesCandidate(users, [])?.id).toBe('admin-1');
    expect(availableProjectSalesCandidates(users, []).map((item) => item.id)).toEqual(['admin-1', 'sales-1']);
  });

  it('does not offer an administrator already assigned to the Project Sales team', () => {
    const assignments = [{
      id: 'assignment-1', project_id: 'project-1', user_id: 'admin-1', responsibility: 'sales',
      is_primary: true, routing_weight: 100, accepts_new_leads: true, is_active: true,
      email: 'admin@example.com', first_name: 'Company', last_name: 'Administrator',
    }] as ProjectAssignment[];
    expect(companyAdministratorSalesCandidate(users, assignments)).toBeUndefined();
    expect(availableProjectSalesCandidates(users, assignments).map((item) => item.id)).toEqual(['sales-1']);
  });
});

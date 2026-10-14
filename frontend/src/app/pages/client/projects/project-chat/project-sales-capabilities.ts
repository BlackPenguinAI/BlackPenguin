import { ProjectAssignment, ProjectSalesCandidate } from './project-onboarding.models';

export function availableProjectSalesCandidates(
  users: ProjectSalesCandidate[],
  assignments: ProjectAssignment[],
): ProjectSalesCandidate[] {
  const assigned = new Set(
    assignments
      .filter((item) => item.responsibility === 'sales' && item.is_active)
      .map((item) => item.user_id),
  );
  return users.filter(
    (item) => (item.role === 'admin' || item.role === 'sales') && item.is_active && !assigned.has(item.id),
  );
}

export function companyAdministratorSalesCandidate(
  users: ProjectSalesCandidate[],
  assignments: ProjectAssignment[],
): ProjectSalesCandidate | undefined {
  return availableProjectSalesCandidates(users, assignments).find((item) => item.role === 'admin');
}

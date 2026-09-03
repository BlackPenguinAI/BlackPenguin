import { of, throwError } from 'rxjs';

import { CompaniesPageComponent } from './companies-page';

describe('CompaniesPageComponent company deletion', () => {
  const unavailableDetail = {
    code: 'FIREBASE_ADMIN_DELETE_UNAVAILABLE',
    message: 'Firebase cleanup must be confirmed.',
    can_confirm_manual_cleanup: true,
  };

  function setup() {
    const companyService = {
      deleteCompany: vi.fn(),
      getCompanies: vi.fn(() => of([])),
      getPlans: vi.fn(() => of([])),
    };
    const toast = { showError: vi.fn(), showSuccess: vi.fn() };
    const changeDetector = { detectChanges: vi.fn() };
    const component = new CompaniesPageComponent(
      companyService as never,
      toast as never,
      {} as never,
      changeDetector as never,
    );
    component.openDeleteModal('company-1');
    return { component, companyService, toast };
  }

  it('requires a second confirmation when automatic Firebase cleanup is unavailable', () => {
    const { component, companyService, toast } = setup();
    companyService.deleteCompany.mockReturnValue(throwError(() => ({
      status: 409,
      error: { detail: unavailableDetail },
    })));

    component.confirmDelete();

    expect(companyService.deleteCompany).toHaveBeenCalledWith('company-1', false);
    expect(component.showDeleteModal).toBe(true);
    expect(component.manualFirebaseCleanupRequired).toBe(true);
    expect(component.deleteWarningMessage).toBe(unavailableDetail.message);
    expect(toast.showError).not.toHaveBeenCalled();
  });

  it('deletes locally only after the administrator confirms manual Firebase cleanup', () => {
    const { component, companyService, toast } = setup();
    component.manualFirebaseCleanupRequired = true;
    companyService.deleteCompany.mockReturnValue(of({ firebase_cleanup: 'confirmed_manual' }));

    component.confirmDelete();

    expect(companyService.deleteCompany).toHaveBeenCalledWith('company-1', true);
    expect(component.showDeleteModal).toBe(false);
    expect(component.manualFirebaseCleanupRequired).toBe(false);
    expect(toast.showSuccess).toHaveBeenCalledWith('Company removed successfully.');
  });

  it('keeps the dialog open when deletion fails for an unrelated reason', () => {
    const { component, companyService, toast } = setup();
    companyService.deleteCompany.mockReturnValue(throwError(() => ({
      status: 502,
      error: { detail: 'Firebase bridge unavailable.' },
    })));

    component.confirmDelete();

    expect(component.showDeleteModal).toBe(true);
    expect(toast.showError).toHaveBeenCalledWith('Firebase bridge unavailable.');
  });
});

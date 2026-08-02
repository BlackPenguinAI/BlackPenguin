import { ComponentFixture, TestBed } from '@angular/core/testing';

import { LegalCompliancePage } from './legal-compliance-page';

describe('LegalCompliancePage', () => {
  let component: LegalCompliancePage;
  let fixture: ComponentFixture<LegalCompliancePage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LegalCompliancePage],
    }).compileComponents();

    fixture = TestBed.createComponent(LegalCompliancePage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

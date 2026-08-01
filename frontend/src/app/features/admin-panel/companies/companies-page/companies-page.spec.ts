import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CompaniesPage } from './companies-page';

describe('CompaniesPage', () => {
  let component: CompaniesPage;
  let fixture: ComponentFixture<CompaniesPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompaniesPage],
    }).compileComponents();

    fixture = TestBed.createComponent(CompaniesPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

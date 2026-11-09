import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PlansPageComponent as PlansPage } from './plans-page';

describe('PlansPage', () => {
  let component: PlansPage;
  let fixture: ComponentFixture<PlansPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlansPage],
    }).compileComponents();

    fixture = TestBed.createComponent(PlansPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

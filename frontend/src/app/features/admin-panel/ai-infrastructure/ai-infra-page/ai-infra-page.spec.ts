import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AiInfraPage } from './ai-infra-page';

describe('AiInfraPage', () => {
  let component: AiInfraPage;
  let fixture: ComponentFixture<AiInfraPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AiInfraPage],
    }).compileComponents();

    fixture = TestBed.createComponent(AiInfraPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

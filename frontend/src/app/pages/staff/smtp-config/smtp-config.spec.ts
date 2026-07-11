import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SmtpConfig } from './smtp-config';

describe('SmtpConfig', () => {
  let component: SmtpConfig;
  let fixture: ComponentFixture<SmtpConfig>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SmtpConfig],
    }).compileComponents();

    fixture = TestBed.createComponent(SmtpConfig);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

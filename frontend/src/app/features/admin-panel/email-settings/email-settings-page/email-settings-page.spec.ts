import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EmailSettingsPage } from './email-settings-page';

describe('EmailSettingsPage', () => {
  let component: EmailSettingsPage;
  let fixture: ComponentFixture<EmailSettingsPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EmailSettingsPage],
    }).compileComponents();

    fixture = TestBed.createComponent(EmailSettingsPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

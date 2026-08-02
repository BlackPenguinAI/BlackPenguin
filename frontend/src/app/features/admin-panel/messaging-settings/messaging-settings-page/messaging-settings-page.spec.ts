import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MessagingSettingsPage } from './messaging-settings-page';

describe('MessagingSettingsPage', () => {
  let component: MessagingSettingsPage;
  let fixture: ComponentFixture<MessagingSettingsPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MessagingSettingsPage],
    }).compileComponents();

    fixture = TestBed.createComponent(MessagingSettingsPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

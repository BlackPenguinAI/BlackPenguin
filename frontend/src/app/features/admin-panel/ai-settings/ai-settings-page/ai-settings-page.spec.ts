import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AiSettingsPage } from './ai-settings-page';

describe('AiSettingsPage', () => {
  let component: AiSettingsPage;
  let fixture: ComponentFixture<AiSettingsPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AiSettingsPage],
    }).compileComponents();

    fixture = TestBed.createComponent(AiSettingsPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

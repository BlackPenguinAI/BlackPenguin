import { ComponentFixture, TestBed } from '@angular/core/testing';

import { LegalEditor } from './legal-editor';

describe('LegalEditor', () => {
  let component: LegalEditor;
  let fixture: ComponentFixture<LegalEditor>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LegalEditor],
    }).compileComponents();

    fixture = TestBed.createComponent(LegalEditor);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

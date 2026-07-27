import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ProjectChat } from './project-chat';

describe('ProjectChat', () => {
  let component: ProjectChat;
  let fixture: ComponentFixture<ProjectChat>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProjectChat],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectChat);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

import { HttpClientTestingModule } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { ProjectChatComponent } from './project-chat';


describe('ProjectChatComponent', () => {
  let component: ProjectChatComponent;
  let fixture: ComponentFixture<ProjectChatComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProjectChatComponent, HttpClientTestingModule, RouterTestingModule],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => 'project-1' } } },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectChatComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should wait for state before showing onboarding UI', () => {
    expect(component.initialState).toBe('loading');
    expect(component.showWelcome).toBe(false);
  });
});

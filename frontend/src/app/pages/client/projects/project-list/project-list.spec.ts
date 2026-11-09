import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { API_V1_URL } from '../../../../core/config/api.config';
import { ToastService } from '../../../../core/services/toast';
import { ProjectListComponent } from './project-list';

describe('ProjectListComponent', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProjectListComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ToastService,
          useValue: { showError: vi.fn(), showSuccess: vi.fn() },
        },
      ],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the canonical collection URL with a trailing slash', () => {
    const fixture = TestBed.createComponent(ProjectListComponent);
    fixture.detectChanges();

    const request = http.expectOne(`${API_V1_URL}/projects/`);
    expect(request.request.method).toBe('GET');
    request.flush([]);
  });

  it('creates an onboarding draft and navigates to the returned chat URL', () => {
    const fixture = TestBed.createComponent(ProjectListComponent);
    const component = fixture.componentInstance;
    const navigate=vi.spyOn(TestBed.inject(Router),'navigateByUrl').mockResolvedValue(true);

    component.createProject();

    const request = http.expectOne(`${API_V1_URL}/projects/drafts`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({});
    request.flush({ id: 'project-1', onboarding_url:'/app/projects/project-1/onboarding' });
    expect(navigate).toHaveBeenCalledWith('/app/projects/project-1/onboarding');
  });
});

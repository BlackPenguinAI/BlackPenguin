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

  it('opens the welcome screen without creating a project', () => {
    const fixture = TestBed.createComponent(ProjectListComponent);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture.componentInstance.createProject();
    http.expectNone(request => request.method === 'POST');
    expect(navigate).toHaveBeenCalledWith('/app/projects/new');
  });
});

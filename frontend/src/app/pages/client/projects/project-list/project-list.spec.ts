import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

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

  it('creates projects through the canonical collection URL', () => {
    const fixture = TestBed.createComponent(ProjectListComponent);
    const component = fixture.componentInstance;
    component.newProject = { name: 'Demo', address: 'Av. Demo 123', city: 'Lima' };

    component.createProject();

    const request = http.expectOne(`${API_V1_URL}/projects/`);
    expect(request.request.method).toBe('POST');
    request.flush({ id: 'project-1', ...component.newProject });
  });
});

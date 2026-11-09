import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { API_V1_URL } from '../../../../core/config/api.config';
import { ProjectNewComponent } from './project-new';

describe('ProjectNewComponent deliberate onboarding start', () => {
  let http: HttpTestingController;
  let navigate: ReturnType<typeof vi.spyOn>;
  const create = () => TestBed.createComponent(ProjectNewComponent);
  beforeEach(async () => {
    sessionStorage.clear();
    await TestBed.configureTestingModule({imports:[ProjectNewComponent], providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([])]}).compileComponents();
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router),'navigateByUrl').mockResolvedValue(true);
  });
  afterEach(() => { http.verify(); sessionStorage.clear(); TestBed.resetTestingModule(); });

  it('renders the welcome page without creating any backend entity', () => {
    const fixture = create(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-onboarding-welcome')).toBeTruthy();
    http.expectNone(() => true);
  });
  it('normalizes the URL and creates only when Continue is submitted', async () => {
    const component = create().componentInstance;
    component.start('www.example.com/homes');
    const request = http.expectOne(`${API_V1_URL}/projects/start`);
    expect(request.request.body.initial_url).toBe('https://www.example.com/homes');
    expect(request.request.body.skip_website).toBe(false);
    expect(request.request.body.client_request_id).toMatch(/^[\da-f-]{36}$/);
    request.flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
    await Promise.resolve();
    expect(navigate).toHaveBeenCalledWith('/app/projects/one/onboarding');
    expect(component.busy).toBe(false);
  });
  it('starts without a website only after the explicit skip choice', () => {
    create().componentInstance.start(null);
    const request = http.expectOne(`${API_V1_URL}/projects/start`);
    expect(request.request.body.initial_url).toBe(null);
    expect(request.request.body.skip_website).toBe(true);
    request.flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
  });
  it.each(['','not a website','ftp://example.com'])('rejects an invalid URL: %s', url => {
    const component = create().componentInstance; component.start(url);
    http.expectNone(() => true);
    expect(component.errorMessage).toContain('valid HTTP');
  });
  it('ignores double clicks while the start is pending', () => {
    const component = create().componentInstance;
    component.start(null); component.start(null);
    http.expectOne(`${API_V1_URL}/projects/start`).flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
  });
  it('reuses the retry key after a lost response and after page recreation', () => {
    const first = create().componentInstance; first.start(null);
    const request = http.expectOne(`${API_V1_URL}/projects/start`);
    const key = request.request.body.client_request_id;
    request.flush('Unavailable',{status:503,statusText:'Unavailable'});
    expect(first.busy).toBe(false);
    const second = create().componentInstance; second.start(null);
    const retry = http.expectOne(`${API_V1_URL}/projects/start`);
    expect(retry.request.body.client_request_id).toBe(key);
    retry.flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
  });
  it('retains the key if navigation fails after the server saved the project', async () => {
    navigate.mockResolvedValue(false);
    const component = create().componentInstance; component.start(null);
    const first = http.expectOne(`${API_V1_URL}/projects/start`);
    const key = first.request.body.client_request_id;
    first.flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
    await Promise.resolve();
    expect(component.errorMessage).toContain('Retry');
    component.start(null);
    const retry = http.expectOne(`${API_V1_URL}/projects/start`);
    expect(retry.request.body.client_request_id).toBe(key);
    retry.flush({id:'one',onboarding_url:'/app/projects/one/onboarding'});
  });
});

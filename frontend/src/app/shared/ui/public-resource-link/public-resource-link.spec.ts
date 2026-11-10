import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PublicResourceLinkComponent } from './public-resource-link';

afterEach(() => { TestBed.resetTestingModule(); vi.unstubAllGlobals(); });

describe('Public resource links', () => {
  it('opens the server URL directly in a new tab and exposes the copy action', async () => {
    const fixture = TestBed.createComponent(PublicResourceLinkComponent);
    fixture.componentRef.setInput('url', 'https://blackpenguin.ai/api/v1/projects/resources/asset/signature');
    fixture.componentRef.setInput('label', 'Open public PDF');
    fixture.detectChanges();
    const links = fixture.nativeElement.querySelectorAll('a');
    expect(links.length).toBe(2);
    expect(links[0].textContent).toContain('Open public PDF');
    expect(links[0].getAttribute('href')).toContain('/resources/asset/signature');
    expect(links[0].target).toBe('_blank');
    expect(links[0].rel).toContain('noopener');
    expect(fixture.nativeElement.textContent).toContain('opens without signing in');
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    await fixture.componentInstance.copy();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledWith(links[0].href);
    expect(fixture.nativeElement.textContent).toContain('Link copied');
  });

  it('retains a selectable URL when clipboard permission is denied', async () => {
    const fixture = TestBed.createComponent(PublicResourceLinkComponent);
    fixture.componentRef.setInput('url', 'https://example.com/approved');
    fixture.detectChanges();
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    await fixture.componentInstance.copy();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.address').textContent).toContain('https://example.com/approved');
    expect(fixture.nativeElement.querySelector('[role="status"]').textContent).toContain('Select and copy');
    expect(fixture.nativeElement.querySelector('button').disabled).toBe(false);
  });

  it('removes links and copied status when a resource is revoked', async () => {
    const fixture = TestBed.createComponent(PublicResourceLinkComponent);
    fixture.componentRef.setInput('url', 'https://example.com/approved');
    fixture.detectChanges();
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    await fixture.componentInstance.copy();
    fixture.componentRef.setInput('url', null);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('a')).toBeNull();
    expect(fixture.componentInstance.copied).toBe(false);
  });
});

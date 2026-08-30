import { DOCUMENT } from '@angular/common';
import { Inject, Injectable } from '@angular/core';
import { Meta, Title } from '@angular/platform-browser';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class SeoMetaService {
  private readonly publicPages: Record<string, { title: string; description: string }> = {
    '/': { title: 'Black Penguin AI | Autonomous Real Estate Lead Conversion', description: 'Black Penguin helps real estate developers qualify Meta leads, continue conversations by SMS, route appointments and prepare Sales teams with traceable AI intelligence.' },
    '/legal/privacy': { title: 'Privacy Policy | Black Penguin AI', description: 'Learn how Black Penguin AI handles personal information, lead data and platform usage.' },
    '/legal/terms': { title: 'Terms and Conditions | Black Penguin AI', description: 'Review the terms governing use of the Black Penguin AI platform.' },
  };
  constructor(private router: Router, private title: Title, private meta: Meta, @Inject(DOCUMENT) private document: Document) {}
  start(): void {
    this.apply(this.router.url.split('?')[0]);
    this.router.events.pipe(filter(event => event instanceof NavigationEnd)).subscribe(event => this.apply((event as NavigationEnd).urlAfterRedirects.split('?')[0]));
  }
  private apply(path: string): void {
    const page = this.publicPages[path];
    const canonical = this.document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (page) {
      this.title.setTitle(page.title); this.meta.updateTag({ name: 'description', content: page.description }); this.meta.updateTag({ name: 'robots', content: 'index,follow,max-image-preview:large' });
      if (canonical) canonical.href = `https://blackpenguin.ai${path === '/' ? '/' : path}`;
    } else {
      this.meta.updateTag({ name: 'robots', content: 'noindex,nofollow' });
      if (canonical) canonical.href = 'https://blackpenguin.ai/';
    }
  }
}

import { ChangeDetectorRef, Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-public-resource-link',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div *ngIf="url" class="resource-link">
      <div class="actions">
        <a [href]="url" target="_blank" rel="noopener noreferrer">{{ label }}</a>
        <button type="button" (click)="copy()" [disabled]="copying">{{ copied ? 'Link copied' : 'Copy link' }}</button>
      </div>
      <p class="hint">Public link · opens without signing in</p>
      <a class="address" [href]="url" target="_blank" rel="noopener noreferrer">{{ url }}</a>
      <p *ngIf="message" role="status" class="hint">{{ message }}</p>
    </div>
  `,
  styles: [`:host{display:block;min-width:0;width:100%}.resource-link{margin-top:.75rem;min-width:0}.actions{display:flex;flex-wrap:wrap;gap:.5rem}.actions a,button{display:inline-flex;align-items:center;min-height:2.5rem;padding:.5rem .75rem;border:1px solid #ffffff30;border-radius:.6rem;color:#f5c84b;background:#101010;font-size:.75rem;font-weight:600;cursor:pointer}button:disabled{opacity:.5}.actions a:focus-visible,button:focus-visible,.address:focus-visible{outline:2px solid #f5c84b;outline-offset:3px}.hint{margin:.5rem 0;color:#aaa;font-size:.7rem}.address{display:block;overflow-wrap:anywhere;color:#bbb;font-size:.7rem;text-decoration:underline}`],
})
export class PublicResourceLinkComponent implements OnChanges {
  @Input() url: string | null | undefined = null;
  @Input() label = 'Open public resource';
  copied = false;
  copying = false;
  message = '';
  constructor(private readonly cdr: ChangeDetectorRef) {}
  ngOnChanges(): void { this.copied = false; this.message = ''; }
  async copy(): Promise<void> {
    if (!this.url || this.copying) return;
    const url = this.url;
    this.copying = true;
    this.message = '';
    try {
      await navigator.clipboard.writeText(url);
      if (this.url === url) { this.copied = true; this.message = 'Public link copied.'; }
    } catch {
      this.copied = false;
      this.message = 'Could not copy automatically. Select and copy the link below the buttons.';
    } finally {
      this.copying = false;
      this.cdr.markForCheck();
    }
  }
}

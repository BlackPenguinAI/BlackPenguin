import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';

/** Collapsing never destroys projected controls or the local draft. */
@Component({selector:'app-review-card',standalone:true,template:`
  <section class="rounded-xl border border-white/10 p-3">
    <button type="button" class="w-full text-left" [attr.aria-expanded]="expanded" (click)="expanded=!expanded">
      <span class="block font-medium">{{title}} · {{status}}</span>
      <span class="mt-1 block whitespace-pre-line text-xs text-gray-400">{{summary}}</span>
      <span class="mt-2 block text-xs text-secondary">{{expanded ? 'Collapse review' : 'Expand / edit review'}}</span>
    </button>
    <div [hidden]="!expanded" class="mt-3"><ng-content></ng-content></div>
  </section>`})
export class ReviewCardComponent implements OnChanges {
  @Input() title='Review'; @Input() status='Pending'; @Input() summary='';
  @Input() complete=false; @Input() revision:unknown;
  expanded=true;
  ngOnChanges(changes:SimpleChanges):void {
    if(changes['complete'] || changes['revision']) this.expanded=!this.complete;
  }
}

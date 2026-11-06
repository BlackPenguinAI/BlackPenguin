import { Component, Input, OnInit, Output, EventEmitter, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../core/config/api.config';
import { ConfigureLaterComponent, DeferredCards } from './configure-later/configure-later';

@Component({selector:'app-onboarding-location',standalone:true,imports:[CommonModule,FormsModule,ConfigureLaterComponent],template:
`<section class="rounded-xl border border-white/20 p-4 space-y-3" data-testid="location-editor">
<h3>Country, city and timezone</h3><p class="text-xs text-gray-400">{{options?.source}}. Suggestions are not approved automatically.</p>
<app-configure-later [scope]="scope" [entityId]="entityId" card="field:country" label="Country, city and timezone" [draft]="{country:country,city:city,timezone:timezone}" [blocked]="busy" [records]="records" (saved)="deferred.emit($event)"></app-configure-later>
<label class="block">Country<select class="secure-input w-full" [(ngModel)]="country" (ngModelChange)="countryChanged()"><option value="">Choose country</option><option *ngFor="let item of options?.countries" [value]="item.code">{{item.name}}</option></select></label>
<label class="block">City<input class="secure-input w-full" [(ngModel)]="city" (ngModelChange)="cityChanged()" [attr.list]="'location-cities-'+entityId" placeholder="Choose a suggested city or enter another city"><datalist [id]="'location-cities-'+entityId"><option *ngFor="let item of cities" [value]="item.city"></option></datalist></label>
<label class="block">IANA timezone<select class="secure-input w-full" [(ngModel)]="timezone"><option value="">Choose timezone (required if the city is ambiguous)</option><option *ngFor="let zone of zones" [value]="zone">{{zone}}</option></select></label>
<p class="text-xs text-gray-400">Other cities are supported: enter the city and explicitly choose its timezone. Existing appointments will not move. Project changes require profile approval.</p>
<button type="button" class="structured-primary" (click)="save()" [disabled]="busy || !country || !city.trim() || !timezone">Confirm location</button>
<p role="status">{{message}}</p></section>`})
export class OnboardingLocationComponent implements OnInit {
 @Input() scope:'company'|'project'='project'; @Input() entityId='';
 @Input() records:DeferredCards={};
 @Output() deferred=new EventEmitter<DeferredCards>();
 @Output() saved=new EventEmitter<void>();
 options:any=null;country='';city='';timezone='';busy=false;message='';
 constructor(private http:HttpClient,private cdr:ChangeDetectorRef){}
 get url(){return API_V1_URL+'/onboarding-editor/'+this.scope+'/'+encodeURIComponent(this.entityId)+'/location';}
 ngOnInit(){if(this.entityId)this.http.get<any>(this.url).subscribe({next:v=>{this.options=v;const draft=this.records['field:country']?.draft;for(const key of ['country','city','timezone'] as const)this[key]=typeof draft?.[key]==='string' ? draft[key] : String(v[key] || '');this.cdr.markForCheck();},error:()=>{this.message='Could not load location suggestions. Retry by reopening this review.';this.cdr.markForCheck();}});}
 get cities():Array<any>{return (this.options?.cities || []).filter((i:any)=>i.country===this.country);}
 get zones():string[]{return [...new Set<string>(this.cities.map(i=>i.timezone))].sort();}
 countryChanged(){this.city='';this.timezone='';}
 cityChanged(){const match=[...new Set<string>(this.cities.filter(i=>i.city.toLocaleLowerCase()===this.city.toLocaleLowerCase()).map(i=>i.timezone))];this.timezone=match.length===1?match[0]:'';}
 save(){if(this.busy)return;this.busy=true;this.message='';this.http.post<any>(this.url,{country:this.country,city:this.city.trim(),timezone:this.timezone}).subscribe({next:v=>{this.busy=false;this.message=v.message;this.saved.emit();this.cdr.markForCheck();},error:e=>{this.busy=false;this.message=typeof e.error?.detail==='string'?e.error.detail:'Location was not saved. Please retry; your selection remains.';this.cdr.markForCheck();}});}
}


import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, Input, OnChanges, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Subscription } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({selector:'app-agent-context',standalone:true,imports:[CommonModule,FormsModule],
  templateUrl:'./agent-context.html',styleUrl:'./agent-context.scss'})
export class AgentContextComponent implements OnChanges,OnDestroy {
  @Input() conversationId='';
  @Input() meetingId='';
  @Input() context:any=null;
  @Input() canManage=false;
  data:any=null;error='';notice='';loading=false;retrying=false;note='';
  private generation=0;private request?:Subscription;private action?:Subscription;private timer?:ReturnType<typeof setInterval>;
  constructor(private http:HttpClient,private cdr?:ChangeDetectorRef){}
  ngOnChanges():void {
    this.generation++;this.request?.unsubscribe();this.action?.unsubscribe();if(this.timer)clearInterval(this.timer);
    this.data=this.context;this.error='';this.notice='';this.note='';this.retrying=false;this.loading=false;
    if(!this.context&&(this.conversationId||this.meetingId)){this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}
  }
  ngOnDestroy():void{this.generation++;this.request?.unsubscribe();this.action?.unsubscribe();if(this.timer)clearInterval(this.timer);}
  refresh():void{
    if(this.context||(!this.conversationId&&!this.meetingId)||this.loading)return;
    this.loading=true;const version=this.generation;
    const path=this.meetingId?`meetings/${encodeURIComponent(this.meetingId)}`:`conversations/${encodeURIComponent(this.conversationId)}`;
    this.request=this.http.get<any>(`${API_V1_URL}/sales-agent/${path}/operational-context`).subscribe({next:d=>{
      if(version!==this.generation)return;this.data=d;this.loading=false;this.error='';this.cdr?.markForCheck();
    },error:()=>{if(version!==this.generation)return;this.loading=false;this.error='Context could not be loaded. Check access and refresh.';this.cdr?.markForCheck();}});
  }
  utc(value:string|undefined):string|undefined{return value&&!/[zZ]$|[+-]\d\d:\d\d$/.test(value)?value+'Z':value;}
  label(value:any):string{return String(value||'unknown').replaceAll('_',' ');}
  canRetry(effect:any):boolean{return this.canManage&&!this.data?.scope_limited&&!!this.conversationId&&['review','retry','failed','waiting_connection','waiting_new_calendar','waiting_old_connection','pending'].includes(effect.status);}
  retry(effect:any):void{
    if(!this.canRetry(effect)||this.retrying||this.note.trim().length<3)return;
    const kind=effect.kind==='replacement_calendar'?'replacement':effect.kind.startsWith('cancellation_')?'cancellation':'booking';
    const version=this.generation;this.retrying=true;this.error='';
    this.action=this.http.post(`${API_V1_URL}/sales-agent/conversations/${encodeURIComponent(this.conversationId)}/effects/retry`,{
      kind,operation_id:effect.id,note:this.note.trim()}).subscribe({next:()=>{if(version!==this.generation)return;this.retrying=false;this.notice='Queued for recheck. A retry does not mean synchronization has succeeded.';this.refresh();this.cdr?.markForCheck();},error:()=>{if(version!==this.generation)return;this.retrying=false;this.error='The effect could not be retried. Refresh and review its current state or permissions.';this.cdr?.markForCheck();}});
  }
}

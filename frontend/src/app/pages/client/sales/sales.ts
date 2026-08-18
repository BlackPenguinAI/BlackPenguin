import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { forkJoin } from 'rxjs';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({selector:'app-sales',standalone:true,imports:[CommonModule,FormsModule,RouterModule],templateUrl:'./sales.html',styleUrls:['./sales.scss']})
export class SalesComponent implements OnInit {
  projects:any[]=[]; meetings:any[]=[]; leads:any[]=[]; brokers:any[]=[]; projectId='';
  loading=true; saving=false; selected:any=null; month=new Date(); error=''; success='';
  role=localStorage.getItem('bp_role')||''; settingsOpen=false; availabilitySaving=false;
  timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'; startTime='09:00'; endTime='17:00';
  weekdays=[true,true,true,true,true,false,false];
  calendarProvider='google'; calendarId=''; calendarStatus='not_connected'; calendarSaving=false;
  readonly dayLabels=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

  constructor(private http:HttpClient,private cdr:ChangeDetectorRef){}

  ngOnInit():void {
    this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe({
      next:rows=>{this.projects=rows;this.projectId=rows.find(p=>p.is_demo)?.id||rows[0]?.id||'';this.reload();},
      error:()=>{this.loading=false;this.error='Projects could not be loaded.';this.cdr.markForCheck();},
    });
    if(this.role==='sales') this.loadSchedulingSettings();
  }

  reload():void {
    if(!this.projectId){this.loading=false;return;}
    this.loading=true; this.error='';
    forkJoin({
      meetings:this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/meetings`),
      leads:this.http.get<any[]>(`${API_V1_URL}/sales/projects/${this.projectId}/leads-report`),
      brokers:this.http.get<any[]>(`${API_V1_URL}/brokers/${this.projectId}/brokers`),
    }).subscribe({
      next:data=>{this.meetings=data.meetings;this.leads=data.leads;this.brokers=data.brokers;this.selected=this.meetings[0]||null;this.loading=false;this.cdr.markForCheck();},
      error:()=>{this.loading=false;this.error='Sales calendar data could not be loaded.';this.cdr.markForCheck();},
    });
  }

  loadSchedulingSettings():void {
    forkJoin({
      availability:this.http.get<any[]>(`${API_V1_URL}/sales/availability/me`),
      calendars:this.http.get<any[]>(`${API_V1_URL}/sales/calendar-connections/me`),
    }).subscribe({next:data=>{
      if(data.availability.length){
        this.timezone=data.availability[0].timezone; this.startTime=data.availability[0].start_time; this.endTime=data.availability[0].end_time;
        this.weekdays=this.dayLabels.map((_,index)=>data.availability.some(item=>item.weekday===index&&item.is_active));
      }
      const connection=data.calendars[0];
      if(connection){this.calendarProvider=connection.provider;this.calendarId=connection.calendar_id||'';this.calendarStatus=connection.status;}
      this.cdr.markForCheck();
    }});
  }

  saveAvailability():void {
    if(this.availabilitySaving||!this.weekdays.some(Boolean)||this.endTime<=this.startTime)return;
    this.availabilitySaving=true; this.error='';
    const windows=this.weekdays.map((active,weekday)=>({weekday,start_time:this.startTime,end_time:this.endTime,is_active:active})).filter(item=>item.is_active);
    this.http.put(`${API_V1_URL}/sales/availability/me`,{timezone:this.timezone,windows}).subscribe({
      next:()=>{this.availabilitySaving=false;this.success='Availability saved. The agent can now offer verified slots.';this.cdr.markForCheck();},
      error:err=>{this.availabilitySaving=false;this.error=err.error?.detail||'Availability could not be saved.';this.cdr.markForCheck();},
    });
  }

  saveCalendarConnection():void {
    if(!this.calendarId.trim()||this.calendarSaving)return;
    this.calendarSaving=true; this.error='';
    this.http.put<any>(`${API_V1_URL}/sales/calendar-connections/me`,{provider:this.calendarProvider,calendar_id:this.calendarId.trim()}).subscribe({
      next:row=>{this.calendarSaving=false;this.calendarStatus=row.status;this.success='Calendar is ready for simulation. OAuth dispatch remains disabled.';this.cdr.markForCheck();},
      error:err=>{this.calendarSaving=false;this.error=err.error?.detail||'Calendar configuration could not be saved.';this.cdr.markForCheck();},
    });
  }

  get days():Date[]{const start=new Date(this.month.getFullYear(),this.month.getMonth(),1);const grid=new Date(start);grid.setDate(1-start.getDay());return Array.from({length:42},(_,i)=>new Date(grid.getFullYear(),grid.getMonth(),grid.getDate()+i));}
  meetingsFor(day:Date):any[]{return this.meetings.filter(m=>new Date(m.meeting_time).toDateString()===day.toDateString());}
  move(delta:number):void{this.month=new Date(this.month.getFullYear(),this.month.getMonth()+delta,1);}
  save():void{
    if(!this.selected)return;this.saving=true;this.error='';
    this.http.put<any>(`${API_V1_URL}/sales/meetings/${this.selected.id}`,{broker_id:this.selected.broker_id||null,status:this.selected.status,confirmation_status:this.selected.confirmation_status}).subscribe({
      next:row=>{Object.assign(this.selected,row);this.saving=false;this.success='Meeting updated.';this.cdr.markForCheck();},
      error:err=>{this.saving=false;this.error=err.error?.detail||'Meeting could not be updated.';this.cdr.markForCheck();},
    });
  }
  count(status:string):number{return this.meetings.filter(m=>m.status===status).length;}
}

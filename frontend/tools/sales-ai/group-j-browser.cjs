// Isolated browser acceptance: mock every API and block external traffic.
const {chromium}=require('playwright');const fs=require('fs');const path=require('path');
(async()=>{
 const origin=process.env.BP_BROWSER_URL||'http://127.0.0.1:4180';if(!['127.0.0.1','localhost'].includes(new URL(origin).hostname))throw Error('Local preview required');
 const browser=await chromium.launch({headless:true,executablePath:process.env.BP_CHROME||undefined});
 const results=[];
 async function scenario(width,mode){
  const ctx=await browser.newContext({viewport:{width,height:1050},timezoneId:'UTC'});const page=await ctx.newPage();page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const now=new Date().toISOString(),future=new Date(Date.now()+86400000).toISOString();let resumed=false,manual=false,retried=false,failContext=mode==='agent';
  const incident={id:'case',reason:'REPEATED_ABUSE',evidence:'Continued personal abuse after warning',status:'open',created_at:now};
  const row={id:'conversation',lead_id:'lead',project_id:'project',channel:'sms',provider:'telnyx',stage:'active',automation_level:2,is_paused:true,pause_reason:'Human intervention: Personal abuse continued',can_resume:true,updated_at:now,lead_name:'QA test lead',phone:'+15550100001',funnel_stage:'contacted',pipeline_stage:'S09_HANDOFF',agent_status:'human_control',project_name:'QA development',project_timezone:'America/Lima',last_message:'Sales review required',last_message_at:now,intervention_cases:[incident]};
  const data={version:'sales-operational-context/1.0',scope_limited:false,chat:{status:'paused',pause_reason:row.pause_reason,cadence:'stopped',cadence_reason:'booked'},execution:{new_engine_selected:true,new_flow_enabled:true,project_ready:true,job_status:'completed'},current_interest:{project_name:'QA development',property:'Loft'},appointments:[{id:'visit',project_name:'QA development',property_type_name:'Studio',starts_at_utc:future,status:'confirmed',specialist_name:'QA Sales',duration_minutes:45,address:'100 Test St',calendar_status:'failed'}],effects:[{id:'booking-op',kind:'booking',meeting_id:'visit',status:'review',attempts:5,last_error:'RuntimeError',next_attempt_at:future}],waits:[{id:'wait',project_name:'QA development',property:'Loft',date_from:'2026-11-10',date_until:'2026-11-20',timezone:'America/Lima',channel:'sms',status:'review',last_error:'ProviderOutcomeUnknown',next_check_at:future}],tasks:[{id:'t',topic:'materials',status:'blocked',blocked_reason:'Needs approved file'}],proposals:[{id:'p',kind:'replacement',project_name:'QA development',property:'Loft',starts_at:future,status:'awaiting_exact_confirmation',expires_at:future}],interventions:[incident],moderation:[{id:'m',category:'harassment',disposition:'pause',evidence:incident.evidence,warning_accepted_at:now}],trace:{engine:'sales-active/1.0',model:'test/offline',run_status:'completed',last_message_status:'sent',configuration:{version:2},language_validation:{output_language:'en'},action_policy:{held_topics:[]}}};
  const messages=[{id:'message',direction:'inbound',role:'user',channel:'sms',content:incident.evidence,status:'received',created_at:now}];
  await page.addInitScript(role=>{localStorage.setItem('bp_token','offline.'+btoa(JSON.stringify({exp:Math.floor(Date.now()/1000)+3600}))+'.offline');localStorage.setItem('bp_role',role);},mode==='monitor'?'superadmin':'admin');
  await page.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url()),p=url.pathname;
   if(p.includes('/api/v1/')){
    let reply=[];
    if(p.endsWith('/users/me'))reply={role:mode==='monitor'?'superadmin':'admin',first_name:'QA',last_name:'Administrator',company_name:'QA Company'};
    else if(p.endsWith('/notifications/unread-count'))reply={count:0};
    else if(p.includes('/monitor/companies'))reply={items:[{id:'company',name:'QA Company'}],has_more:false};
    else if(p.includes('/monitor/projects'))reply=[{id:'project',name:'QA development'}];
    else if(p.includes('/monitor/leads'))reply={items:[{id:'lead',name:'QA test lead'}],has_more:false};
    else if(p.includes('/monitor/conversations/conversation'))reply={messages,dialogue_events:[{revision:1,kind:'prepared',payload_json:{result:'validated'}}],delivery_statuses:[],is_paused:row.is_paused,pause_reason:row.pause_reason,has_more:false,next_cursor:'message',operational_context:data};
    else if(p.includes('/monitor/conversations'))reply=[{id:'conversation',channel:'sms',provider:'telnyx'}];
    else if(p.endsWith('/operational-context')){
      if(failContext){failContext=false;return route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Synthetic retryable outage"}'});}
      reply=data;
    }
    else if(p.endsWith('/sales-agent/conversations'))reply=[row];
    else if(p.endsWith('/effects/retry')){retried=true;data.effects[0].status='pending';reply={status:'queued_for_recheck'};}
    else if(p.endsWith('/action')){const body=req.postDataJSON();if(body.action==='resume'){resumed=true;row.is_paused=false;row.pause_reason=null;incident.status='false_positive';incident.resolution={note:body.review_note,reviewer_name:'QA administrator',at:now};data.chat.status='open';data.chat.pause_reason=null;}else{row.is_paused=true;row.pause_reason='Manual control active';data.chat.status='paused';data.chat.pause_reason=row.pause_reason;}reply=row;}
    else if(p.endsWith('/manual-message')){manual=true;messages.push({id:'manual',direction:'outbound',role:'human',channel:'sms',content:req.postDataJSON().content,status:'sent',created_at:now});reply=messages.at(-1);}
    else if(p.endsWith('/messages'))reply=messages;
    else if(p.includes('/sales/schedule'))reply={meetings:[{id:'visit',lead_id:'lead',lead_name:'QA test lead',project_id:'project',project_name:'QA development',project_timezone:'UTC',meeting_time:future,duration_minutes:45,status:'confirmed',assigned_sales_user_id:'sales',visit_address:'100 Test St',attachments:[]}],availability:[],availability_blocks:[],sales_users:[{id:'sales',first_name:'QA',last_name:'Sales',role:'sales'}],timezone:'UTC'};
    else if(p.replace(/\/$/,'').endsWith('/projects'))reply=[{id:'project',name:'QA development',timezone:'UTC'}];
    else if(p.endsWith('/sales/leads/lead'))reply={id:'lead',full_name:'QA test lead',chat_messages:[]};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(reply)});
   }
   return url.origin===origin?route.continue():route.abort();
  });
  await page.goto(origin+(mode==='monitor'?'/monitor':mode==='schedule'?'/app/schedule':'/app/agent'));
  if(mode==='monitor'){
    await page.getByLabel('Company',{exact:true}).selectOption('company');await page.getByLabel('Project',{exact:true}).selectOption('project');await page.getByLabel('Lead',{exact:true}).selectOption('lead');await page.getByLabel('Conversation / channel').selectOption('conversation');
  }else if(mode==='schedule'){
    await page.getByRole('button',{name:/appointments/i}).first().click();
    await page.locator('.meeting-block').filter({hasText:'QA test lead'}).first().click();
  }
  const region=page.getByRole('region',{name:'Agent operational context'});await region.waitFor();
  if(mode==='agent'){
    await region.getByRole('alert').waitFor();await region.getByRole('button',{name:'Refresh',exact:true}).click();
  }
  await region.getByText('Loft',{exact:true}).first().waitFor();await region.getByText(/QA development · Studio/).waitFor();
  await region.getByText(/Synchronization and receipts/).click();await region.getByText(/RuntimeError/).waitFor();
  await region.getByText(/Availability requests/).click();await region.getByText('Review the provider receipt before any new contact; automatic resend is stopped.').waitFor();
  if(mode==='agent'){
    await region.getByPlaceholder('Explain what was reviewed').fill('Reviewed saved Calendar binding');await region.getByRole('button',{name:'Retry failed synchronization'}).click();await region.getByText(/Queued for recheck/).waitFor();
    await page.getByPlaceholder('Explain the review or why this was a false positive').fill('Reviewed current message with the lead');await page.getByRole('button',{name:'False positive · resume AI'}).click();
    await region.getByRole('button',{name:'Refresh',exact:true}).click();await region.getByText('Chat: open',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Take manual control'}).click();await page.getByPlaceholder(/Send a manual SMS/).fill('A staff member is reviewing your visit.');await page.getByPlaceholder(/Send a manual SMS/).press('Enter');
    await page.getByText('A staff member is reviewing your visit.',{exact:true}).waitFor();
    if(!resumed||!manual||!retried)throw Error('Missing action evidence');
  }else if(await region.getByRole('button',{name:'Retry failed synchronization'}).count())throw Error('Read only context exposed an action');
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw Error('Horizontal page overflow '+mode+' '+width);
  if(errors.length)throw Error(errors.join('\n'));
  if(process.env.BP_QA_DIR){fs.mkdirSync(process.env.BP_QA_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.BP_QA_DIR,`group-j-${mode}-${width}.png`),fullPage:true});}
  results.push({surface:mode,width,status:'passed',resumed,manual,retried});await ctx.close();
 }
 try{for(const width of [1440,390])for(const mode of ['agent','schedule','monitor'])await scenario(width,mode);console.log(JSON.stringify({status:'passed',api:'MOCKED',external_traffic:'BLOCKED',results},null,2));}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

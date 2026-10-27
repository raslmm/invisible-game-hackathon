(function(){
"use strict";
var $=function(id){return document.getElementById(id);};
var E={},ids="matchSelect personaSelect favoriteTeamSelect focusPlayerSelect languageSelect speedSelect playButton resetButton homeTeam awayTeam homeInitials awayInitials subjectTeam clockValue matchState eventsSeen alertsSeen dangerCount eventShare riskSignal pitchWindowLabel currentEventLabel eventPlayerLabel pitchMarkers chartGrid chartBars storyModePill storyEmpty storyContent storyCategory storyClock storyHeadline storyBody storyWhy factRow evidenceCount evidenceList traceList feedCount eventFeed playerSignalList recapPanel recapHeadline recapSummary recapChapters recapNote recapPlayerNames exportButton providerBadge broadcastChyronBtn chyronModal closeChyronBtn chyronTag chyronMinute chyronTitle chyronDesc chyronEventsCount".split(" ");
ids.forEach(function(id){E[id]=$(id);});
var S={bundle:null,matches:[],playing:false,finished:false,index:-1,clock:0,timer:null,source:null,insight:null,token:0,focusEvent:null,liveWindow:null,recap:null};
function clock(n){n=Math.max(0,Math.floor(Number(n)||0));return String(Math.floor(n/60)).padStart(2,"0")+":"+String(n%60).padStart(2,"0");}
function txt(id,value){if(E[id])E[id].textContent=value;}
function api(path,body){return fetch(path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{}).then(function(r){return r.json().catch(function(){return {};}).then(function(data){if(!r.ok)throw Error(data.error||"Request failed");return data;});});}
function option(value,label){var o=document.createElement("option");o.value=value;o.textContent=label;return o;}
function requestPreferences(){return {match_id:S.bundle.match.match_id,persona:E.personaSelect.value,language:E.languageSelect.value,favorite_team:E.favoriteTeamSelect.value,focus_player_id:E.focusPlayerSelect.value||null};}
function modeLabel(){return E.personaSelect.options[E.personaSelect.selectedIndex].text.toUpperCase();}
function reset(){
 if(S.timer)clearTimeout(S.timer);if(S.source)S.source.close();S.source=null;S.timer=null;S.playing=false;S.finished=false;S.index=-1;S.clock=0;S.insight=null;S.focusEvent=null;S.liveWindow=null;S.recap=null;S.token++;E.exportButton.disabled=true;
 if(E.chyronModal)E.chyronModal.hidden=true;
 E.recapPanel.hidden=true;E.storyEmpty.hidden=false;E.storyContent.hidden=true;E.storyHeadline.textContent="—";E.storyBody.textContent="—";E.storyWhy.textContent="—";E.evidenceList.replaceChildren();E.traceList.replaceChildren();
 E.eventFeed.replaceChildren();var blank=document.createElement("div");blank.className="feed-empty";blank.textContent="Events will appear here as they arrive.";E.eventFeed.appendChild(blank);
 E.playerSignalList.replaceChildren();var p=document.createElement("p");p.textContent="Player event involvement will appear during replay.";E.playerSignalList.appendChild(p);
 status("READY TO REPLAY");render();playLabel();
}
function status(value){var n=E.matchState.querySelector("span:last-child");if(n)n.textContent=value;E.matchState.classList.toggle("is-live",value==="LIVE SIMULATION");}
function playLabel(){var n=E.playButton.querySelector("[data-i18n]");n.textContent=S.playing?"Pause replay":(S.index>=0&&!S.finished?"Resume replay":"Play replay");E.playButton.querySelector(".play-icon").textContent=S.playing?"Ⅱ":"▶";}
function loadBundle(id){
 if(S.timer)clearTimeout(S.timer);if(S.source)S.source.close();S.playing=false;
 return api("/api/matches/"+encodeURIComponent(id)+"/metadata").then(function(b){
  S.bundle={match:b.match,players:b.players,events:[],analysis:{windows:[],insights:[]}};
  txt("homeTeam",b.match.home_team);txt("awayTeam",b.match.away_team);txt("homeInitials",b.match.home_team.split(/\s+/).map(function(x){return x[0];}).join("").slice(0,2));txt("awayInitials",b.match.away_team.split(/\s+/).map(function(x){return x[0];}).join("").slice(0,2));txt("subjectTeam",b.match.subject_team);
  E.favoriteTeamSelect.replaceChildren(option(b.match.subject_team,b.match.subject_team),option(b.match.opponent_team,b.match.opponent_team));E.favoriteTeamSelect.value=b.match.subject_team;
  E.focusPlayerSelect.replaceChildren();b.players.slice().sort(function(a,c){return (a.team_name===b.match.subject_team?-1:1)-(c.team_name===b.match.subject_team?-1:1)||a.player_name.localeCompare(c.player_name);}).forEach(function(p){E.focusPlayerSelect.appendChild(option(p.player_id,p.player_name+" · "+p.position));});
  if(E.focusPlayerSelect.options.length)E.focusPlayerSelect.selectedIndex=0;
  document.getElementById("pitchSvg").setAttribute("aria-label","Synthetic event locations for "+b.match.home_team+" v "+b.match.away_team);
  reset();
 });
}
function observed(){return S.bundle&&S.index>=0?S.bundle.events.slice(0,S.index+1):[];}
function svg(tag,attrs,text){var n=document.createElementNS("http://www.w3.org/2000/svg",tag);Object.keys(attrs||{}).forEach(function(k){n.setAttribute(k,attrs[k]);});if(text!==undefined)n.textContent=text;return n;}
function renderPitch(events){
 E.pitchMarkers.replaceChildren();events.slice(-72).forEach(function(ev,i,a){var x=32+Number(ev.x)*5.76,y=32+(100-Number(ev.y))*3.26,op=Math.max(.24,.92-(a.length-i)*.009);if(ev.is_dangerous_turnover)E.pitchMarkers.appendChild(svg("circle",{cx:x,cy:y,r:7,fill:"none",stroke:"#f07968","stroke-width":1.5,opacity:op}));E.pitchMarkers.appendChild(svg("circle",{cx:x,cy:y,r:ev.event_id===S.focusEvent?5:3.3,fill:ev.is_subject_team?"#d9f66b":"#83c9ec",stroke:ev.event_id===S.focusEvent?"white":"rgba(9,18,12,.8)","stroke-width":ev.event_id===S.focusEvent?2:1,opacity:op}));});
}
function renderChart(windows){
 E.chartGrid.replaceChildren();E.chartBars.replaceChildren();var l=46,r=585,top=24,bottom=213;
 [0,.25,.5,.75,1].forEach(function(v){var y=bottom-v*(bottom-top);E.chartGrid.appendChild(svg("line",{x1:l,y1:y,x2:r,y2:y,class:"chart-gridline"}));E.chartGrid.appendChild(svg("text",{x:8,y:y+3,class:"chart-axis-small"},String(Math.round(v*100))));});
 E.chartGrid.appendChild(svg("text",{x:8,y:13,class:"chart-axis-small"},"SIGNAL"));
 var slot=(r-l)/Math.max(windows.length,1);
 windows.forEach(function(w,i){var done=w.window_end_seconds<=S.clock,score=done?Number(w.risk_score||0):0,h=done?Math.max(3,score*(bottom-top)):5,width=Math.min(48,slot*.55),x=l+i*slot+(slot-width)/2,y=bottom-h,kind=!done?"unknown":(w.persistent_risk?"persistent":(w.transient_spike?"transient":"quiet"));
  var bar=svg("rect",{x:x,y:y,width:width,height:h,rx:4,class:done?"chart-bar "+kind:"chart-bar chart-unknown",opacity:done?1:.42});bar.appendChild(svg("title",{},done?"Window "+(i+1)+" · signal "+score.toFixed(2):"Window "+(i+1)+" · not played"));E.chartBars.appendChild(bar);
  if(done)E.chartBars.appendChild(svg("text",{x:x+width/2,y:Math.max(top-4,y-6),class:"chart-value-label"},score.toFixed(2)));
  E.chartBars.appendChild(svg("text",{x:x+width/2,y:bottom+19,class:"chart-axis-label","text-anchor":"middle"},String(i*15)));E.chartBars.appendChild(svg("text",{x:x+width/2,y:bottom+33,class:"chart-axis-small","text-anchor":"middle"},"MIN"));
 });
}
function renderFeed(events){
 E.eventFeed.replaceChildren();events.slice(-6).reverse().forEach(function(ev){var row=document.createElement("div");row.className="feed-row";var time=document.createElement("span");time.className="feed-time";time.textContent=clock(ev.timestamp_seconds);var dot=document.createElement("i");dot.className="feed-type-dot"+(ev.is_dangerous_turnover?" danger":(ev.is_subject_team?" subject":""));var main=document.createElement("span");main.className="feed-main";var title=document.createElement("strong");title.textContent=ev.event_type.replaceAll("_"," ");var detail=document.createElement("small");var p=S.bundle.players.find(function(x){return x.player_id===ev.player_id;});detail.textContent=(p?p.player_name:ev.player_id)+" · "+ev.pitch_zone.replaceAll("_"," ");main.append(title,detail);var team=document.createElement("span");team.className="feed-team-tag";team.textContent=ev.is_subject_team?"SUB":"OPP";row.append(time,dot,main,team);E.eventFeed.appendChild(row);});
 if(!events.length){var blank=document.createElement("div");blank.className="feed-empty";blank.textContent="Events will appear here as they arrive.";E.eventFeed.appendChild(blank);}txt("feedCount",events.length+" OBSERVED");
}
function renderPlayers(events){
 E.playerSignalList.replaceChildren();var map=new Map();events.filter(function(e){return e.is_subject_team;}).forEach(function(e){var p=map.get(e.player_id)||{n:0,d:0,row:null};p.n++;p.d+=e.is_dangerous_turnover?1:0;p.row=S.bundle.players.find(function(x){return x.player_id===e.player_id;})||p.row;map.set(e.player_id,p);});
 var list=Array.from(map.values()).sort(function(a,b){return b.d-a.d||b.n-a.n;}).slice(0,3);
 if(!list.length){var msg=document.createElement("p");msg.textContent="Player event involvement will appear during replay.";E.playerSignalList.appendChild(msg);return;}
 list.forEach(function(x,i){var row=document.createElement("div");row.className="player-row";var rank=document.createElement("span");rank.className="player-rank";rank.textContent=String(i+1).padStart(2,"0");var name=document.createElement("span");name.className="player-name";name.textContent=x.row?x.row.player_name:"—";var pos=document.createElement("span");pos.className="player-position";pos.textContent=x.row?x.row.position:"";name.appendChild(pos);var count=document.createElement("span");count.className="player-count";count.textContent=x.n+" events · "+x.d+" dangerous turnovers";row.append(rank,name,count);E.playerSignalList.appendChild(row);});
}
function renderMetrics(events,windows){
 var done=windows.filter(function(w){return w.window_end_seconds<=S.clock;}),alerts=done.filter(function(w){return !!w.insight;});
 txt("eventsSeen",String(events.length));txt("alertsSeen",String(alerts.length));txt("dangerCount",String(events.filter(function(e){return e.is_subject_team&&e.is_dangerous_turnover;}).length));
 var share=S.liveWindow?S.liveWindow.subject_event_share:(done.length?done[done.length-1].subject_event_share:null);txt("eventShare",share===null||share===undefined?"—":Math.round(Number(share)*100)+"%");
 txt("riskSignal",S.liveWindow?"~"+Number(S.liveWindow.risk_score).toFixed(2):(done.length?Number(done[done.length-1].risk_score).toFixed(2):"—"));
 txt("pitchWindowLabel",S.liveWindow?"WINDOW "+(Math.floor(S.liveWindow.window_start_seconds/900)+1)+" · LIVE":(done.length?"WINDOWS COMPLETE · "+done.length:"WAITING FOR REPLAY"));E.riskSignal.title=S.liveWindow?"Provisional score for the current, incomplete window.":"Latest completed-window rule score.";txt("clockValue",clock(S.clock));
 if(events.length){var ev=events[events.length-1],p=S.bundle.players.find(function(x){return x.player_id===ev.player_id;});txt("currentEventLabel",ev.event_type.replaceAll("_"," ").toUpperCase()+" · "+ev.pitch_zone.replaceAll("_"," "));txt("eventPlayerLabel",(p?p.player_name:ev.player_id)+" · "+ev.team_name);}else{txt("currentEventLabel","Waiting for the first event");txt("eventPlayerLabel","—");}
 renderChart(windows);renderPitch(events);
}
function fact(label,value){var c=document.createElement("span");c.className="fact-chip";c.appendChild(document.createTextNode(label+" "));var b=document.createElement("b");b.textContent=value;c.appendChild(b);E.factRow.appendChild(c);}
function displayStory(p){
 var f=p.facts,s=p.presentation;E.storyEmpty.hidden=true;E.storyContent.hidden=false;E.storyCategory.textContent=f.category==="persistent_defensive_risk"?"REPEATED EXPOSURE":"TRANSIENT DANGER";E.storyCategory.classList.toggle("transient-tag",f.category!=="persistent_defensive_risk");txt("storyClock","MATCH CLOCK · "+f.window_label);txt("storyHeadline",s.headline);txt("storyBody",s.story);txt("storyWhy",s.why_now);E.factRow.replaceChildren();fact("DANGEROUS",String(f.dangerous_turnovers));fact("OPP. ENTRIES",String(f.opponent_attacking_entries));fact("5-MIN RECURRENCE",f.risk_subwindows+" / 3");fact("RECOVERY INDEX",Number(f.average_recovery_speed).toFixed(2));fact("DEFENSIVE COVER",Number(f.average_defensive_cover).toFixed(1));
 txt("evidenceCount",String(p.evidence_event_ids.length));E.evidenceList.replaceChildren();p.evidence_events.forEach(function(ev){var b=document.createElement("button");b.className="evidence-chip";b.type="button";b.title="Show source event on pitch";b.textContent=clock(ev.timestamp_seconds)+" · "+ev.player_name+" · "+ev.event_type;b.addEventListener("click",function(){S.focusEvent=ev.event_id;renderPitch(observed());document.getElementById("pitchSvg").scrollIntoView({behavior:"smooth",block:"center"});});E.evidenceList.appendChild(b);});
 if(E.chyronTitle){E.chyronTag.textContent=f.category==="persistent_defensive_risk"?"TACTICAL EXPOSURE ALERT":"TRANSIENT DANGER";E.chyronMinute.textContent=f.window_label;E.chyronTitle.textContent=s.headline;E.chyronDesc.textContent=s.story;E.chyronEventsCount.textContent=p.evidence_event_ids.length+" VERIFIED EVENTS";}
 E.traceList.replaceChildren();p.trace.stages.forEach(function(stage){var row=document.createElement("span");row.className="trace-stage";var name=document.createElement("b");name.textContent=stage.agent;row.append(name,document.createTextNode(" · "+stage.status.replaceAll("_"," ")+" · "+stage.elapsed_ms+"ms"));E.traceList.appendChild(row);});
 if(p.trace.editorial_guard){var guard=p.trace.editorial_guard;var guardRow=document.createElement("span");guardRow.className="trace-stage trace-guard";var gName=document.createElement("b");gName.textContent=guard.agent;guardRow.append(gName,document.createTextNode(" · "+guard.status.replaceAll("_"," ")+" · "+guard.compliance_status));E.traceList.appendChild(guardRow);}
 if(p.trace.end_to_overlay_ms!==undefined){var timing=document.createElement("span");timing.className="trace-stage";var label=document.createElement("b");label.textContent="EVENT → OVERLAY";timing.append(label,document.createTextNode(" · "+p.trace.end_to_overlay_ms+"ms"));E.traceList.appendChild(timing);}
 E.storyModePill.textContent=modeLabel();
}
function narrative(){
 if(!S.bundle||!S.insight)return;var token=++S.token,requestedAt=performance.now();E.storyModePill.textContent=modeLabel();
 var body=requestPreferences();body.insight_id=S.insight.insight_id;
 api("/api/narrative",body).then(function(p){if(token===S.token){p.trace.end_to_overlay_ms=Math.round(performance.now()-requestedAt);displayStory(p);}}).catch(function(){if(token===S.token){E.storyEmpty.hidden=false;E.storyContent.hidden=true;E.storyEmpty.querySelector("strong").textContent="Narrative workflow unavailable."; }});
}
function render(){
 if(!S.bundle)return;var events=observed(),windows=S.bundle.analysis.windows;renderMetrics(events,windows);renderFeed(events);renderPlayers(events);
 var alerts=windows.filter(function(w){return w.window_end_seconds<=S.clock&&w.insight;});
 if(alerts.length){var latest=alerts[alerts.length-1].insight;if(!S.insight||latest.insight_id!==S.insight.insight_id){S.insight=latest;narrative();}}
}
function recap(){
 if(!S.bundle||!S.finished)return;S.recap=null;E.exportButton.disabled=true;E.recapPanel.hidden=false;txt("recapHeadline",E.languageSelect.value==="es"?"Preparando el resumen…":"Building recap…");
 api("/api/recap",requestPreferences()).then(function(r){S.recap=r;E.exportButton.disabled=false;txt("recapHeadline",r.headline);txt("recapSummary",r.summary);E.recapChapters.replaceChildren();
 if(!r.chapters.length){var empty=document.createElement("p");empty.className="feed-empty";empty.textContent="No alerts were raised by the synthetic rules.";E.recapChapters.appendChild(empty);}
 r.chapters.forEach(function(c){var card=document.createElement("article");card.className="recap-chapter";var h=document.createElement("b");h.textContent=c.presentation.headline;var p=document.createElement("p");p.textContent=c.presentation.story+" · "+c.evidence_event_ids.length+" cited events";card.append(h,p);E.recapChapters.appendChild(card);});
 txt("recapNote",r.synthetic_data_note);txt("recapPlayerNames","Most involved players: "+r.players.map(function(p){return p.player_name+" ("+p.event_count+")";}).join(" · "));
 }).catch(function(){txt("recapHeadline","Recap could not be generated. Try again.");});
}
function mergeWindows(windows){
 var known=new Set(S.bundle.analysis.windows.map(function(w){return w.window_start_seconds;}));
 windows.forEach(function(w){if(!known.has(w.window_start_seconds)){known.add(w.window_start_seconds);S.bundle.analysis.windows.push(w);}});
 S.bundle.analysis.windows.sort(function(a,b){return a.window_start_seconds-b.window_start_seconds;});
 S.bundle.analysis.insights=S.bundle.analysis.windows.filter(function(w){return !!w.insight;}).map(function(w){return w.insight;});
}
function finish(){
 S.playing=false;S.finished=true;S.timer=null;S.source=null;S.liveWindow=null;
 var ws=S.bundle.analysis.windows;S.clock=ws.length?ws[ws.length-1].window_end_seconds:S.clock;
 status("REPLAY COMPLETE");playLabel();render();recap();
}
function openStream(){
 var from=S.bundle.events.length;
 var url="/api/matches/"+encodeURIComponent(S.bundle.match.match_id)+"/stream?from="+from+"&speed="+(Number(E.speedSelect.value)||120);
 S.source=new EventSource(url);
 S.source.onmessage=function(message){
  var data;try{data=JSON.parse(message.data);}catch(error){console.error("Bad replay message",error);return;}
  if(data.message_type==="replay_update"){
   S.bundle.events.push(data.event);S.index=S.bundle.events.length-1;S.clock=data.event.timestamp_seconds;S.liveWindow=data.live_window||null;mergeWindows(data.completed_windows||[]);render();
  }else if(data.message_type==="match_complete"){
   mergeWindows(data.completed_windows||[]);S.bundle.analysis.player_summaries=data.player_summaries||[];S.source.close();S.source=null;finish();
  }
 };
 S.source.onerror=function(){
  if(!S.playing||!S.source)return;
  if(S.source.readyState===EventSource.CLOSED){S.source=null;S.playing=false;status("STREAM INTERRUPTED · RESUME AVAILABLE");playLabel();}
 };
}
function toggle(){
 if(!S.bundle)return;
 if(S.playing){S.playing=false;if(S.source)S.source.close();S.source=null;status("READY TO REPLAY");playLabel();return;}
 if(S.finished)reset();S.playing=true;status("LIVE SIMULATION");playLabel();openStream();
}
function download(){
 if(!S.bundle||!S.recap||!S.finished)return;
 var payload={schema_version:"invisible-game.submission-export.v1",exported_at:new Date().toISOString(),match:S.bundle.match,events:S.bundle.events,analysis:S.bundle.analysis,overlay_messages:S.recap.chapters.map(function(c){return c.overlay;}),recap:S.recap};
 var blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=S.bundle.match.match_id+"-invisible-game.json";document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(url);},1000);
}
function error(e){console.error(e);txt("providerBadge","Could not load local match service.");E.storyEmpty.hidden=false;E.storyEmpty.querySelector("strong").textContent="Could not load match data. Check that the local server is running.";}
function init(){
 E.playButton.addEventListener("click",toggle);E.resetButton.addEventListener("click",reset);E.exportButton.addEventListener("click",download);
 if(E.broadcastChyronBtn&&E.chyronModal){E.broadcastChyronBtn.addEventListener("click",function(){if(!S.insight)return;E.chyronModal.hidden=!E.chyronModal.hidden;});}
 if(E.closeChyronBtn&&E.chyronModal){E.closeChyronBtn.addEventListener("click",function(){E.chyronModal.hidden=true;});}
 E.matchSelect.addEventListener("change",function(){loadBundle(E.matchSelect.value).catch(error);});
 E.languageSelect.addEventListener("change",function(){if(S.insight)narrative();if(S.finished)recap();});
 [E.personaSelect,E.favoriteTeamSelect,E.focusPlayerSelect].forEach(function(c){c.addEventListener("change",function(){E.storyModePill.textContent=modeLabel();if(S.insight)narrative();if(S.finished)recap();});});
 api("/api/health").then(function(h){E.providerBadge.textContent=h.provider.model_ready?"Azure AI Foundry · "+h.provider.model_deployment:"Local workflow · offline ready";}).catch(function(){});
 api("/api/matches").then(function(r){S.matches=r.matches||[];E.matchSelect.replaceChildren();S.matches.forEach(function(m){E.matchSelect.appendChild(option(m.match_id,m.match_id+" · "+m.home_team+" v "+m.away_team+" — "+m.scenario_title));});if(!S.matches.length)throw Error("No match data");var chosen=S.matches.some(function(m){return m.match_id==="IGM001";})?"IGM001":S.matches[0].match_id;E.matchSelect.value=chosen;return loadBundle(chosen);}).catch(error);
}
document.addEventListener("DOMContentLoaded",init);
})();

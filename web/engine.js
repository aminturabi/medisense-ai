// MediSense JS engine - mirrors medisense/engine.py so the web UI also
// works as a pure static page (no server). Same rules, same templates.
const FREQ_PER_DAY = {OD:1, BD:2, BID:2, TDS:3, TID:3, QID:4, HS:1, SOS:0, PRN:0};
const FREQ_TIMES = {
  OD:{en:["morning"],ur:["صبح"],ps:["سهار"]},
  BD:{en:["morning","night"],ur:["صبح","رات"],ps:["سهار","شپه"]},
  BID:{en:["morning","night"],ur:["صبح","رات"],ps:["سهار","شپه"]},
  TDS:{en:["morning","afternoon","night"],ur:["صبح","دوپہر","رات"],ps:["سهار","غرمه","شپه"]},
  TID:{en:["morning","afternoon","night"],ur:["صبح","دوپہر","رات"],ps:["سهار","غرمه","شپه"]},
  QID:{en:["morning","midday","evening","night"],ur:["صبح","دوپہر","شام","رات"],ps:["سهار","غرمه","ماښام","شپه"]},
  HS:{en:["night, before sleeping"],ur:["رات سونے سے پہلے"],ps:["شپه له خوب مخکې"]},
  SOS:{en:["only when needed"],ur:["صرف ضرورت پڑنے پر"],ps:["یوازې کله چې اړتیا وي"]},
  PRN:{en:["only when needed"],ur:["صرف ضرورت پڑنے پر"],ps:["یوازې کله چې اړتیا وي"]}
};
const DISCLAIMER = {
  en:"Note: This explanation is for understanding only and does not replace your doctor's advice.",
  ur:"نوٹ: یہ وضاحت صرف سمجھنے کے لیے ہے اور آپ کے ڈاکٹر کے مشورے کا متبادل نہیں ہے۔",
  ps:"یادونه: دا تشریح یوازې د پوهیدو لپاره ده او ستاسو د ډاکټر مشورې ځای نه نیسي۔"};
const EMERGENCY = {
  en:"URGENT: One of your results is in the danger range. Go to the nearest hospital emergency now, or call Rescue 1122.",
  ur:"فوری: آپ کا ایک نتیجہ خطرے کی حد میں ہے۔ فوراً قریبی ہسپتال کی ایمرجنسی جائیں، یا ریسکیو 1122 پر کال کریں۔",
  ps:"بیړني: ستاسو یوه پایله د خطر په حد کې ده. سمدستي نږدې روغتون ایمرجنسي ته لاړ شئ، یا ریسکیو ۱۱۲۲ ته زنګ ووهئ۔"};
const UNVERIFIED = {
  en:"This item could not be verified automatically. Please confirm it directly with your doctor or pharmacist.",
  ur:"اس چیز کی خودکار تصدیق نہیں ہو سکی۔ براہ کرم اس کی تصدیق براہِ راست اپنے ڈاکٹر یا فارماسسٹ سے کریں۔",
  ps:"دا شی په اتومات ډول تصدیق نه شو. مهرباني وکړئ دا مستقیم له خپل ډاکټر یا درمل جوړونکي څخه تصدیق کړئ۔"};

function ratio(a,b){a=a.toLowerCase();b=b.toLowerCase();
  const m=a.length,n=b.length,dp=Array.from({length:m+1},(_,i)=>[i,...Array(n).fill(0)]);
  for(let j=0;j<=n;j++)dp[0][j]=j;
  for(let i=1;i<=m;i++)for(let j=1;j<=n;j++)
    dp[i][j]=Math.min(dp[i-1][j]+1,dp[i][j-1]+1,dp[i-1][j-1]+(a[i-1]===b[j-1]?0:1));
  return 1-dp[m][n]/Math.max(m,n);}
function redact(text){return text.replace(/\b\d{5}-\d{7}-\d\b/g,"[CNIC HIDDEN]")
  .replace(/\+\d{1,3}[-\s]?\d{3,5}[-\s]?\d{4,7}\b/g,"[PHONE HIDDEN]")
  .replace(/\b(?:\+92|0)3\d{2}[-\s]?\d{7}\b/g,"[PHONE HIDDEN]")
  .replace(/\b\d{10}\b/g,"[PHONE HIDDEN]")
  .replace(/\bMRN[:\s]*[A-Z0-9-]{4,}\b/gi,"[MRN]");}
function escRe(s){return s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");}

const BLOOD_COUNT_KEYS=new Set(["hemoglobin","wbc","platelets","rbc"]);
function isUrineReport(text){const low=text.toLowerCase();return low.includes("urine")&&(low.includes("hpf")||low.includes("microscopic")||low.includes("pus cell"));}
function parseLabs(text,D){
  const out=[];
  const urineCtx=isUrineReport(text);
  for(const lab of D.labs){
    if(urineCtx&&BLOOD_COUNT_KEYS.has(lab.key))continue;
    for(const alias of lab.aliases){
      const m=text.match(new RegExp(escRe(alias)+"\\s*[:\\-]?\\s*(\\d[\\d,]*\\.?\\d*)","i"));
      if(m){
        const rest=text.slice(m.index+m[0].length,m.index+m[0].length+10);
        if(/^\s*[-\u2013]\s*\d/.test(rest)||/hpf/i.test(rest))break;
        const v=parseFloat(m[1].replace(/,/g,""));
        // Decimal-drop sanity check: beyond-human values are OCR decimal
        // errors (6.5 read as 65) - flag them, never fire an emergency.
        if(lab.plausible_max!=null&&v>lab.plausible_max){
          out.push({...lab,value:v,status:"suspect_decimal",suspect_decimal:true,normal_text:`${lab.normal_low} - ${lab.normal_high} ${lab.unit}`});
          break;}
        let s="normal";
        if(lab.critical_low!==null&&v<lab.critical_low)s="critical_low";
        else if(lab.critical_high!==null&&v>lab.critical_high)s="critical_high";
        else if(v<lab.normal_low)s="low"; else if(v>lab.normal_high)s="high";
        out.push({...lab,value:v,status:s,suspect_decimal:false,normal_text:`${lab.normal_low} - ${lab.normal_high} ${lab.unit}`});
        break;}
    }}
  return out;}

function parseMeds(text,D){
  const meds=[],unverified=[],seen=new Set();
  const re=/(?:Tab\.?|Cap\.?|Syp\.?|Tablet|Capsule)?\s*([A-Z][A-Za-z\-+]{2,30})\s+(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)\b(?:[^A-Za-z0-9]{0,6}(OD|BD|BID|TDS|TID|QID|HS|SOS|PRN))?(?:[^0-9]{0,20}?(\d+)\s*(?:days?))?/gi;
  let m;
  while((m=re.exec(text))!==null){
    const raw=m[1],key=raw.toLowerCase(); if(seen.has(key))continue; seen.add(key);
    if(D.labs.some(l=>l.aliases.some(a=>a.toLowerCase()===key)))continue; // lab analyte line, not a medicine
    const strength=parseFloat(m[2]),unit=m[3].toLowerCase(),freq=(m[4]||"").toUpperCase(),days=m[5]?parseInt(m[5]):null;
    let best=null,score=0;
    for(const d of D.drugs)for(const c of [d.generic,...d.brands]){const r=ratio(raw,c);if(r>score){best=d;score=r;}}
    if(!best||score<0.80){unverified.push({raw_name:raw,strength,unit,requires_pharmacist_verification:true});continue;}
    const mg=strength*(unit==="g"?1000:unit==="mcg"?0.001:1);
    const per=FREQ_PER_DAY[freq]||0;
    meds.push({name_as_written:raw,generic:best.generic,match_score:Math.round(score*100)/100,
      strength,unit,frequency:freq||null,days,daily_mg:per?mg*per:null,max_daily_mg:best.max_daily_mg,
      purpose_en:best.purpose_en,purpose_ur:best.purpose_ur,purpose_ps:best.purpose_ps,
      precaution_en:best.precaution_en,precaution_ur:best.precaution_ur,precaution_ps:best.precaution_ps,
      requires_pharmacist_verification:false});
  }
  return [meds,unverified];}

function safetyChecks(meds,labs,D){
  const alerts=[];
  for(const med of meds)if(med.daily_mg!==null&&med.daily_mg>med.max_daily_mg)
    alerts.push({type:"max_dose",severity:"severe",drug:med.generic,
      message_en:`${med.generic}: the written dose is ${med.daily_mg} mg per day, which is more than the maximum ${med.max_daily_mg} mg per day in the reference list. Do NOT take it this way - confirm with your doctor or pharmacist first.`,
      message_ur:`${med.generic}: لکھی گئی خوراک روزانہ ${med.daily_mg} ملی گرام ہے، جو حوالہ فہرست میں زیادہ سے زیادہ ${med.max_daily_mg} ملی گرام سے زیادہ ہے۔ اس طرح نہ لیں - پہلے اپنے ڈاکٹر یا فارماسسٹ سے تصدیق کریں۔`,
      message_ps:`${med.generic}: لیکل شوی خوراک هره ورځ ${med.daily_mg} ملي ګرام دی، کوم چې د مرجع په لست کې له اعظمي ${med.max_daily_mg} ملي ګرام څخه ډېر دی. داسې یې مه اخلئ - لومړی له ډاکټر یا درمل جوړونکي څخه تصدیق وکړئ۔`});
  const gens=new Set(meds.map(x=>x.generic));
  for(const r of D.interactions)if(gens.has(r.a)&&gens.has(r.b))
    alerts.push({type:"interaction",severity:r.severity,drug:`${r.a} + ${r.b}`,message_en:r.message_en,message_ur:r.message_ur,message_ps:r.message_ps});
  for(const lab of labs){
    if(lab.status==="critical_low"||lab.status==="critical_high")
      alerts.push({type:"panic_lab",severity:"emergency",drug:lab.name,message_en:`${lab.name} is ${lab.value} ${lab.unit} - this is in the DANGER range.`,message_ur:"",message_ps:""});
    else if(lab.status==="suspect_decimal")
      alerts.push({type:"decimal_check",severity:"moderate",drug:lab.name,
        message_en:`${lab.name} was read as ${lab.value} ${lab.unit} - that is more than a human body can have, so the reading probably dropped a decimal point (did it mean ${lab.value/10}?). Please check this number in the text above and fix it. No emergency alert has been raised for it.`,
        message_ur:`${lab.name} ${lab.value} ${lab.unit} پڑھا گیا ہے - یہ انسانی جسم میں ممکن حد سے زیادہ ہے، اس لیے غالباً عشاریہ (decimal point) چھوٹ گیا ہے (کیا اس کا مطلب ${lab.value/10} تھا؟)۔ براہ کرم اوپر والے متن میں یہ نمبر چیک کر کے درست کریں۔ اس کے لیے کوئی ایمرجنسی الرٹ نہیں لگایا گیا۔`,
        message_ps:`${lab.name} ${lab.value} ${lab.unit} لوستل شوی - دا د انسان په بدن کې له ممکن حد څخه ډېر دی، نو شاید عشاریه (decimal point) پاتې شوې وي (ایا مطلب یې ${lab.value/10} و؟). مهرباني وکړئ دا شمېره په پورته متن کې وګورئ او سمه یې کړئ. د دې لپاره کوم بیړنی خبرتیا نه ده ورکړل شوې۔`});}
  return alerts;}

function explain(meds,labs,unverified,alerts,lang){
  const lines=[];
  if(alerts.some(a=>a.severity==="emergency"))lines.push(EMERGENCY[lang]);
  for(const a of alerts)if(a.severity!=="emergency"&&a["message_"+lang])lines.push("⚠ "+a["message_"+lang]);
  for(const med of meds){
    const name=med.name_as_written.toLowerCase()!==med.generic.toLowerCase()?`${med.generic} (${med.name_as_written})`:med.generic;
    lines.push(`${name}: ${med["purpose_"+lang]}`);
    if(med.frequency){const t=FREQ_TIMES[med.frequency][lang];
      if(lang==="en")lines.push(`Take 1 tablet (${med.strength} ${med.unit}) at these times: ${t.join(" and ")}${med.days?` for ${med.days} days`:""}. ${med.precaution_en}`);
      else if(lang==="ur")lines.push(`1 گولی (${med.strength} ${med.unit}) ان اوقات میں لیں: ${t.join("، ")}${med.days?`، ${med.days} دن تک`:""}۔ ${med.precaution_ur}`);
      else lines.push(`۱ ګولۍ (${med.strength} ${med.unit}) په دې وختونو کې واخلئ: ${t.join("، ")}${med.days?`، د ${med.days} ورځو لپاره`:""}۔ ${med.precaution_ps}`);}}
  const SW={normal:{en:"Normal",ur:"نارمل",ps:"نورمال"},high:{en:"High",ur:"زیادہ",ps:"لوړ"},low:{en:"Low",ur:"کم",ps:"ټیټ"},
    critical_high:{en:"DANGEROUSLY HIGH",ur:"خطرناک حد تک زیادہ",ps:"په خطرناکه کچه لوړ"},critical_low:{en:"DANGEROUSLY LOW",ur:"خطرناک حد تک کم",ps:"په خطرناکه کچه ټیټ"},
    suspect_decimal:{en:"PLEASE CHECK THE NUMBER",ur:"براہ کرم نمبر چیک کریں",ps:"مهرباني وکړئ شمېره وګورئ"}};
  for(const lab of labs){
    if(lab.status==="suspect_decimal"){
      if(lang==="en")lines.push(`${lab.name}: The value read was ${lab.value} ${lab.unit} - this looks like a reading mistake (a decimal point may be missing, for example ${lab.value/10}). Please check the printed report and fix the number in the text above.`);
      else if(lang==="ur")lines.push(`${lab.name}: پڑھی گئی قیمت ${lab.value} ${lab.unit} ہے - یہ پڑھنے کی غلطی لگتی ہے (عشاریہ چھوٹ گیا ہوگا، مثلاً ${lab.value/10})۔ براہ کرم چھپی ہوئی رپورٹ دیکھ کر اوپر والے متن میں نمبر درست کریں۔`);
      else lines.push(`${lab.name}: لوستل شوې بیه ${lab.value} ${lab.unit} ده - دا د لوستلو تېروتنه ښکاري (شاید عشاریه پاتې وي، لکه ${lab.value/10}). مهرباني وکړئ چاپ شوی راپور وګورئ او په پورته متن کې شمېره سمه کړئ۔`);
      continue;}
    if(lang==="en")lines.push(`${lab.name}: Your result is ${lab.value} ${lab.unit}. Normal is ${lab.normal_text}. Result: ${SW[lab.status].en}. This test measures ${lab.measures_en}.`);
    else if(lang==="ur")lines.push(`${lab.name}: آپ کا نتیجہ ${lab.value} ${lab.unit} ہے۔ نارمل حد ${lab.normal_text} ہے۔ نتیجہ: ${SW[lab.status].ur}۔ یہ ٹیسٹ ${lab.measures_ur} کو ناپتا ہے۔`);
    else lines.push(`${lab.name}: ستاسو پایله ${lab.value} ${lab.unit} ده. نورمال حد ${lab.normal_text} دی. پایله: ${SW[lab.status].ps}۔ دا ټیسټ ${lab.measures_ps} اندازه کوي۔`);}
  for(const u of unverified)lines.push(`${u.raw_name} ${u.strength} ${u.unit}: ${UNVERIFIED[lang]}`);
  lines.push(DISCLAIMER[lang]);
  return lines;}

function analyzeLocal(raw){
  const D=window.MEDISENSE_DATA,text=redact(raw||"");
  const labs=parseLabs(text,D),[meds,unverified]=parseMeds(text,D);
  const alerts=safetyChecks(meds,labs,D);
  return {medications:meds,
    lab_results:labs.map(l=>({name:l.name,value:l.value,unit:l.unit,status:l.status,normal_text:l.normal_text,suspect_decimal:!!l.suspect_decimal})),
    unverified_items:unverified,alerts,
    emergency:alerts.some(a=>a.severity==="emergency"),
    requires_pharmacist_verification:unverified.length>0,
    explanations:{en:explain(meds,labs,unverified,alerts,"en"),ur:explain(meds,labs,unverified,alerts,"ur"),ps:explain(meds,labs,unverified,alerts,"ps")}};
}

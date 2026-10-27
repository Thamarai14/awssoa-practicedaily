"""Generate 50 AWS SAA-C03 practice questions, build a self-contained HTML test,
and email it as an attachment. Run daily via GitHub Actions (see workflow)."""
import json
import os
import random
import re
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

# Real exam weights: 28 / 26 / 24 / 22 -> 14 + 13 + 12 + 11 = 50 questions
DOMAINS = [
    ("Design Resilient Architectures", 14, [
        "Multi-AZ and multi-Region design", "Auto Scaling and ELB", "SQS/SNS/EventBridge decoupling",
        "Route 53 routing policies and failover", "RDS Multi-AZ and Aurora", "Backup, DR strategies (pilot light, warm standby)",
        "S3 replication and versioning", "Lambda and serverless resilience", "EFS/EBS durability", "API Gateway and Step Functions"]),
    ("Design Secure Architectures", 13, [
        "IAM roles, policies, permission boundaries", "AWS Organizations and SCPs", "KMS and encryption at rest/in transit",
        "VPC security groups, NACLs, endpoints", "Secrets Manager vs Parameter Store", "WAF, Shield, GuardDuty",
        "S3 bucket policies and Block Public Access", "Cognito and federation/SSO", "CloudTrail and Config", "PrivateLink and VPC peering"]),
    ("Design High-Performing Architectures", 12, [
        "CloudFront and Global Accelerator", "ElastiCache and DAX", "EBS volume types and instance store",
        "DynamoDB capacity, GSI, streams", "Aurora and RDS read replicas", "Kinesis and data ingestion",
        "Athena, Glue, Redshift analytics", "Transit Gateway and Direct Connect", "EC2 instance families and placement groups", "EFS vs FSx options"]),
    ("Design Cost-Optimized Architectures", 11, [
        "S3 storage classes and lifecycle", "EC2 pricing: On-Demand, Reserved, Savings Plans, Spot", "Right-sizing and Compute Optimizer",
        "Data transfer costs and NAT gateway alternatives", "Serverless vs always-on cost", "Cost Explorer, Budgets, tagging",
        "RDS/Aurora Serverless cost choices", "EBS snapshot and volume cost", "Glacier retrieval options", "CloudFront cost reduction"]),
]


def extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


def valid(q) -> bool:
    try:
        opts, ans = q["options"], q["answer"]
        return (
            isinstance(q["question"], str) and isinstance(q["explanation"], str)
            and len(opts) in (4, 5) and all(isinstance(o, str) for o in opts)
            and len(ans) in (1, 2) and all(isinstance(a, int) and 0 <= a < len(opts) for a in ans)
            and len(set(ans)) == len(ans)
        )
    except (KeyError, TypeError):
        return False


def generate(client, domain: str, n: int, topics: list[str], seed: str):
    focus = ", ".join(random.sample(topics, 6))
    prompt = f"""Write {n} NEW, realistic AWS Certified Solutions Architect - Associate (SAA-C03) exam-style
scenario questions for the domain "{domain}". Seed for variety: {seed}.
Emphasise these areas (spread across them): {focus}.
Rules:
- About 15% should be "choose TWO" (5 options, answer has 2 indices). The rest: 4 options, 1 answer.
- Scenarios in 2-4 sentences with exam keywords (e.g. most cost-effective, least operational overhead, highly available).
- Plausible distractors; randomise the position of the correct answer.
- explanation: 2-3 sentences on why the answer is right and why the key distractors are wrong.
- Technically accurate for current AWS services.
Return ONLY a JSON array of exactly {n} objects:
{{"question": str, "options": [str, ...], "answer": [0-based int, ...], "explanation": str}}"""
    last_err = None
    for _ in range(3):
        try:
            msg = client.messages.create(
                model=MODEL, max_tokens=12000, temperature=1.0,
                messages=[{"role": "user", "content": prompt}],
            )
            items = [q for q in extract_json(msg.content[0].text) if valid(q)]
            if len(items) >= n - 1:
                for q in items:
                    q["domain"] = domain
                return items[:n]
            last_err = f"only {len(items)} valid questions"
        except Exception as e:  # retry on API or JSON errors
            last_err = e
    raise RuntimeError(f"Generation failed for {domain}: {last_err}")


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SAA-C03 Daily Practice - __DATE__</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--bd:#d0d0d0;--ok:#1b7f3b;--bad:#b3261e;--mut:#666}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--bd:#3a3d44;--ok:#4cc26e;--bad:#ff6b61;--mut:#9aa}}
body{font-family:system-ui,sans-serif;max-width:820px;margin:0 auto;padding:16px;line-height:1.5;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center;z-index:5}
.q{border:1px solid var(--bd);border-radius:10px;padding:12px 14px;margin:14px 0}
.q.ok{border-color:var(--ok)}.q.bad{border-color:var(--bad)}
label{display:block;padding:6px 8px;border-radius:6px;cursor:pointer}
label.right{background:rgba(76,194,110,.18)}
.ex{margin-top:8px;color:var(--mut);font-size:.92em}
.tag{font-size:.75em;color:var(--mut)}
button{font:inherit;padding:10px 20px;border-radius:8px;border:0;background:#2563eb;color:#fff;cursor:pointer}
#res{font-size:1.1em;margin:12px 0;font-weight:600}
</style></head><body>
<header><div><b>SAA-C03 Practice</b> <span class="tag">__DATE__ - 50 questions</span></div><div id="t">100:00</div></header>
<div id="qs"></div>
<button onclick="submitQuiz()">Submit test</button>
<div id="res"></div>
<script>
const Q=__DATA__;
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const root=document.getElementById('qs');
Q.forEach((q,i)=>{
  const multi=q.answer.length>1, d=document.createElement('div');
  d.className='q'; d.id='q'+i;
  d.innerHTML='<div class="tag">'+esc(q.domain)+'</div><p><b>'+(i+1)+'.</b> '+esc(q.question)+(multi?' <em>(Choose TWO)</em>':'')+'</p>'
    +q.options.map((o,j)=>'<label><input type="'+(multi?'checkbox':'radio')+'" name="q'+i+'" value="'+j+'"> '+esc(o)+'</label>').join('')
    +'<div class="ex"></div>';
  root.appendChild(d);
});
let left=100*60, done=false;
const tick=setInterval(()=>{
  left--; const m=Math.floor(left/60), s=left%60;
  document.getElementById('t').textContent=m+':'+String(s).padStart(2,'0');
  if(left<=0) submitQuiz();
},1000);
function submitQuiz(){
  if(done) return; done=true; clearInterval(tick);
  let score=0; const byDomain={};
  Q.forEach((q,i)=>{
    const sel=[...document.querySelectorAll('input[name=q'+i+']:checked')].map(x=>+x.value).sort();
    const ans=[...q.answer].sort(), ok=JSON.stringify(sel)===JSON.stringify(ans);
    byDomain[q.domain]=byDomain[q.domain]||[0,0]; byDomain[q.domain][1]++;
    if(ok){score++; byDomain[q.domain][0]++;}
    const d=document.getElementById('q'+i); d.classList.add(ok?'ok':'bad');
    d.querySelectorAll('label').forEach((l,j)=>{ if(ans.includes(j)) l.classList.add('right'); l.querySelector('input').disabled=true; });
    d.querySelector('.ex').textContent=(ok?'Correct. ':'Incorrect. ')+q.explanation;
  });
  const pct=Math.round(score/Q.length*100);
  document.getElementById('res').innerHTML='Score: '+score+'/'+Q.length+' ('+pct+'%)<br><span class="tag">'
    +Object.entries(byDomain).map(([k,v])=>esc(k)+': '+v[0]+'/'+v[1]).join(' | ')+'</span>';
  window.scrollTo({top:0,behavior:'smooth'});
}
</script></body></html>"""


def build_html(questions, date_str: str) -> str:
    data = json.dumps(questions, ensure_ascii=False).replace("</", "<\\/")
    return HTML.replace("__DATE__", date_str).replace("__DATA__", data)


def send_mail(path: Path, date_str: str):
    user = os.getenv("GMAIL_USER")
    pwd = os.getenv("GMAIL_APP_PASSWORD")
    to = os.getenv("TO_EMAIL", user)
    if not (user and pwd and to):
        print("Email env vars missing - skipping send.")
        return
    msg = EmailMessage()
    msg["Subject"] = f"Your daily AWS SAA-C03 test - {date_str} (50 questions)"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(
        f"Hi,\n\nYour 50-question SAA-C03 practice test for {date_str} is attached.\n\n"
        "How to take it:\n"
        "1. Download the attached .html file.\n"
        "2. Open it in Chrome/Edge/Safari (not the mail preview).\n"
        "3. Finish in 100 minutes, submit, then review the explanations.\n\n"
        "Target: 80%+ consistently before booking the real exam.\n"
    )
    msg.add_attachment(path.read_bytes(), maintype="text", subtype="html", filename=path.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"Sent to {to}")


def main():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now.strftime("%Y-%m-%d")
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    questions = []
    for name, n, topics in DOMAINS:
        questions += generate(client, name, n, topics, seed=f"{date_str}-{random.randint(1000, 9999)}")
    random.shuffle(questions)
    out = Path("out")
    out.mkdir(exist_ok=True)
    path = out / f"saa-c03-practice-{date_str}.html"
    path.write_text(build_html(questions, date_str), encoding="utf-8")
    print(f"Built {len(questions)} questions -> {path}")
    send_mail(path, date_str)


if __name__ == "__main__":
    sys.exit(main())

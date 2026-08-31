#!/usr/bin/env python3
"""
Interactive HTML ATS Comparison Dashboard:
- Total Points for each resume = sum(category_weight * is_present)
- Relative Score Delta = (improved_points - baseline_points) / baseline_points * 100%
- SHA-256 API response caching (.affinda_cache/)
- Gemini 3.6 Flash SDET Semantic Classifier (sdet_skill_taxonomy.json)
- Automatic noise filtering (quarantining parser artifacts)
- Interactive [Ignore] checkboxes with real-time JS recalculation & localStorage persistence
"""

import urllib.request
import json
import hashlib
import os
import uuid
import sys
import ssl
from pathlib import Path

from config import AFFINDA_API_KEY, GEMINI_API_KEY, get_cache_dir, PROJECT_ROOT

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

BASE_URL = "https://api.us1.affinda.com/v3"
COLLECTION_ID = "sVbXvfpU"
CACHE_DIR = get_cache_dir()
TAXONOMY_FILE = PROJECT_ROOT / "sdet_skill_taxonomy.json"

DOCS = {
    "baseline": {
        "id": "1AqF9a4sGk9B_N4RIXe4vjFez52YEYZA6",
        "name": "Baseline Resume",
        "filename": "baseline_resume.pdf"
    },
    "improved": {
        "id": "1TshOr8vt_NgOTz-K18sYaismGn4CJeHcGB5W1_GSVNI",
        "name": "Improved Resume",
        "filename": "improved_resume.pdf"
    }
}

def fetch_pdf_bytes(doc_id):
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=pdf"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        return resp.read()

def compute_payload_hash(pdf_bytes, filename, collection_id):
    h = hashlib.sha256()
    h.update(pdf_bytes)
    h.update(filename.encode('utf-8'))
    h.update(collection_id.encode('utf-8'))
    return h.hexdigest()

def call_affinda_with_cache(pdf_bytes, filename):
    if not AFFINDA_API_KEY:
        raise ValueError("AFFINDA_API_KEY is not set. Please add it to your .env file or environment.")
        
    payload_hash = compute_payload_hash(pdf_bytes, filename, COLLECTION_ID)
    cache_file = CACHE_DIR / f"affinda_{payload_hash}.json"
    
    if os.path.exists(cache_file):
        print(f"   ⚡ [CACHE HIT] Loaded from .affinda_cache/affinda_{payload_hash[:12]}...json")
        with open(cache_file, "r") as f:
            return json.load(f)
            
    print(f"   🌐 [API CALL] Calling Affinda API (Hash: {payload_hash[:12]}...)...")
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="collection"\r\n\r\n'.encode())
    body.extend(f"{COLLECTION_ID}\r\n".encode())
    
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.extend(b"Content-Type: application/pdf\r\n\r\n")
    body.extend(pdf_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    
    req = urllib.request.Request(f"{BASE_URL}/documents", data=body, headers={
        "Authorization": f"Bearer {AFFINDA_API_KEY}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json"
    })
    
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        res_data = json.loads(resp.read().decode())
        
    with open(cache_file, "w") as f:
        json.dump(res_data, f, indent=2)
    print(f"   💾 Saved response to .affinda_cache/affinda_{payload_hash[:12]}...json")
    
    return res_data

def extract_candidate_target_role(base_data, imp_data):
    """Dynamically extracts the dominant target role from parsed resume work experience or profession."""
    for d in [imp_data.get("data", {}), base_data.get("data", {})]:
        work_exp = d.get("workExperience", [])
        if work_exp and work_exp[0].get("jobTitle"):
            return work_exp[0].get("jobTitle")
        if d.get("profession"):
            return d.get("profession")
    return "Software Development Engineer"

def get_or_classify_taxonomy(all_skill_names, target_role="Software Development Engineer"):
    """Loads or generates role-specific skill taxonomy cache using Gemini Flash."""
    import re
    role_slug = re.sub(r'[^a-zA-Z0-9]+', '_', target_role.lower()).strip('_')
    taxonomy_file = CACHE_DIR / f"taxonomy_{role_slug}.json"
    
    taxonomy = {}
    if taxonomy_file.exists():
        with open(taxonomy_file, "r") as f:
            taxonomy = json.load(f)
            
    unclassified = [s for s in all_skill_names if s not in taxonomy]
    if not unclassified:
        return taxonomy
        
    print(f"🤖 Classifying {len(unclassified)} new skills for target role '{target_role}' via Gemini 3.6 Flash...")
    prompt = f"""You are an expert ATS & Technical Recruiting Classifier for {target_role} roles.

Classify each of the following raw skill strings extracted by an ATS resume parser into EXACTLY ONE of these four categories based on their relevance and importance to a {target_role}:
1. "HARD_TECH": Specific programming languages, tools, frameworks, databases, cloud infrastructure, libraries, APIs, and domain-specific hard technical tools relevant to a {target_role}.
2. "QA_METHODOLOGY": Core engineering practices, architecture patterns, domain methodologies, and design standards (e.g. testing architectures, BDD/TDD, system design, data modeling, framework design, code quality strategies).
3. "PROCESS_LEADERSHIP": Team leadership, Agile/Scrum processes, cross-functional operations, security/compliance, triage, mentoring, and incident management.
4. "PARSER_NOISE": Generic resume filler words, conversational non-technical English verbs/nouns, vague phrases, or obvious parser hallucinations/artifacts (e.g. Table Setting, Collaboration, Social Media, Website Management, Adoptions, Execution Time, Reliability, Planning).

Skills to classify:
{json.dumps(unclassified, indent=2)}

Return ONLY a valid JSON object:
{{
  "skill_name": {{
    "category": "HARD_TECH" | "QA_METHODOLOGY" | "PROCESS_LEADERSHIP" | "PARSER_NOISE",
    "reason": "short explanation in context of a {target_role}"
  }}
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
            new_classifications = json.loads(text_content)
            
        for k, v in new_classifications.items():
            taxonomy[k] = v
            
        with open(taxonomy_file, "w") as f:
            json.dump(taxonomy, f, indent=2)
        print(f"   💾 Saved adaptive taxonomy to .cache/taxonomy_{role_slug}.json")
    except Exception as e:
        print(f"   ⚠️ Gemini classification notice: {e}. Defaulting new skills to PARSER_NOISE.")
        for s in unclassified:
            taxonomy[s] = {"category": "PARSER_NOISE", "reason": "Unclassified fallback"}
    return taxonomy

CATEGORY_WEIGHTS = {
    "HARD_TECH": 4.0,           # Hard tech, tools, frameworks, languages
    "QA_METHODOLOGY": 3.0,      # Testing practices, architecture, test types
    "PROCESS_LEADERSHIP": 2.0,  # Leadership, SDLC, triage, incident management
    "PARSER_NOISE": 0.0         # Quarantined noise
}

def generate_html_report(base_data, imp_data, output_filepath):
    b = base_data.get("data", {})
    i = imp_data.get("data", {})
    
    target_role = extract_candidate_target_role(base_data, imp_data)
    print(f"🎯 Target Candidate Role Detected: '{target_role}'")
    
    b_skills = {s["name"]: s for s in b.get("skills", []) if s.get("name")}
    i_skills = {s["name"]: s for s in i.get("skills", []) if s.get("name")}
    all_skill_names = sorted(list(set(b_skills.keys()).union(set(i_skills.keys()))))
    
    taxonomy = get_or_classify_taxonomy(all_skill_names, target_role=target_role)
    
    less_rep = []
    more_rep = []
    other_rep = []
    noise_items = []
    
    cat_pts = {
        "ALL": {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0},
        "HARD_TECH": {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0},
        "QA_METHODOLOGY": {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0},
        "PROCESS_LEADERSHIP": {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0}
    }
    
    for name in all_skill_names:
        in_b = name in b_skills
        in_i = name in i_skills
        bs = b_skills.get(name, {})
        is_ = i_skills.get(name, {})
        
        tax_info = taxonomy.get(name, {})
        cat = tax_info.get("category", "PARSER_NOISE")
        reason = tax_info.get("reason", "")
        weight = CATEGORY_WEIGHTS.get(cat, 0.0)
        
        b_months = bs.get("numberOfMonths")
        i_months = is_.get("numberOfMonths")
        
        b_disp = f"{b_months} mos" if b_months is not None else ("Yes" if in_b else "No")
        i_disp = f"{i_months} mos" if i_months is not None else ("Yes" if in_i else "No")
        b_last = bs.get("lastUsed") or "-"
        i_last = is_.get("lastUsed") or "-"
        
        row_data = {
            "name": name,
            "category": cat,
            "reason": reason,
            "weight": weight,
            "in_b": in_b,
            "in_i": in_i,
            "b_months": b_months,
            "i_months": i_months,
            "base_disp": b_disp,
            "imp_disp": i_disp,
            "base_last": b_last,
            "imp_last": i_last
        }
        
        if cat == "PARSER_NOISE":
            noise_items.append(row_data)
        else:
            if in_b:
                cat_pts["ALL"]["b"] += weight
                cat_pts["ALL"]["b_cnt"] += 1
            if in_i:
                cat_pts["ALL"]["i"] += weight
                cat_pts["ALL"]["i_cnt"] += 1
                
            if cat in cat_pts:
                if in_b:
                    cat_pts[cat]["b"] += weight
                    cat_pts[cat]["b_cnt"] += 1
                if in_i:
                    cat_pts[cat]["i"] += weight
                    cat_pts[cat]["i_cnt"] += 1
            
            b_val = (b_months or 0.5) if in_b else 0.0
            i_val = (i_months or 0.5) if in_i else 0.0
            
            if i_val < b_val:
                row_data["status"] = "Less Representation"
                less_rep.append(row_data)
            elif i_val > b_val:
                row_data["status"] = "More Representation"
                more_rep.append(row_data)
            else:
                row_data["status"] = "Equal"
                other_rep.append(row_data)
                
    less_rep.sort(key=lambda x: (1 if not x["in_i"] else 2, x["name"]))
    more_rep.sort(key=lambda x: (1 if not x["in_b"] else 2, x["name"]))
    other_rep.sort(key=lambda x: x["name"])
    noise_items.sort(key=lambda x: x["name"])
    
    # Calculate: (improved - baseline) / baseline * 100%
    def calc_delta_pct(b_val, i_val):
        if b_val <= 0:
            return 0.0
        return ((i_val - b_val) / b_val) * 100.0
        
    all_delta_pct = calc_delta_pct(cat_pts["ALL"]["b"], cat_pts["ALL"]["i"])
    hard_delta_pct = calc_delta_pct(cat_pts["HARD_TECH"]["b"], cat_pts["HARD_TECH"]["i"])
    qa_delta_pct = calc_delta_pct(cat_pts["QA_METHODOLOGY"]["b"], cat_pts["QA_METHODOLOGY"]["i"])
    proc_delta_pct = calc_delta_pct(cat_pts["PROCESS_LEADERSHIP"]["b"], cat_pts["PROCESS_LEADERSHIP"]["i"])

    b_noise_cnt = sum(1 for r in noise_items if r['in_b'])
    i_noise_cnt = sum(1 for r in noise_items if r['in_i'])
    noise_delta_pct = calc_delta_pct(b_noise_cnt, i_noise_cnt)

    print("=" * 80)
    print("📊 ATS POINT AUDIT LOG & BREAKDOWN:")
    print("=" * 80)
    print(f"BASELINE RESUME (Total: {cat_pts['ALL']['b']:.0f} pts):")
    print(f"  • Hard Tech & Tools:     {cat_pts['HARD_TECH']['b_cnt']:2d} skills × 4 pts = {cat_pts['HARD_TECH']['b']:.0f} pts")
    print(f"  • QA Methodologies:      {cat_pts['QA_METHODOLOGY']['b_cnt']:2d} skills × 3 pts = {cat_pts['QA_METHODOLOGY']['b']:.0f} pts")
    print(f"  • Process & Leadership:  {cat_pts['PROCESS_LEADERSHIP']['b_cnt']:2d} skills × 2 pts = {cat_pts['PROCESS_LEADERSHIP']['b']:.0f} pts")
    print(f"  • Filtered Noise:        {b_noise_cnt:2d} artifacts")
    print(f"  -------------------------------------------------------------")
    print(f"  TOTAL BASELINE POINTS  = {cat_pts['ALL']['b']:.0f} pts")
    print()
    print(f"IMPROVED RESUME (Total: {cat_pts['ALL']['i']:.0f} pts):")
    print(f"  • Hard Tech & Tools:     {cat_pts['HARD_TECH']['i_cnt']:2d} skills × 4 pts = {cat_pts['HARD_TECH']['i']:.0f} pts")
    print(f"  • QA Methodologies:      {cat_pts['QA_METHODOLOGY']['i_cnt']:2d} skills × 3 pts = {cat_pts['QA_METHODOLOGY']['i']:.0f} pts")
    print(f"  • Process & Leadership:  {cat_pts['PROCESS_LEADERSHIP']['i_cnt']:2d} skills × 2 pts = {cat_pts['PROCESS_LEADERSHIP']['i']:.0f} pts")
    print(f"  • Filtered Noise:        {i_noise_cnt:2d} artifacts ({noise_delta_pct:+.1f}% noise reduction)")
    print(f"  -------------------------------------------------------------")
    print(f"  TOTAL IMPROVED POINTS  = {cat_pts['ALL']['i']:.0f} pts")
    print(f"  NET SCORE DELTA:         {all_delta_pct:+.1f}% ((Improved - Baseline) / Baseline)")
    print("=" * 80)

    def render_table_rows(items, is_noise=False):
        rows = []
        for r in items:
            cat_badge_class = {
                "HARD_TECH": "badge-hard",
                "QA_METHODOLOGY": "badge-qa",
                "PROCESS_LEADERSHIP": "badge-proc",
                "PARSER_NOISE": "badge-noise"
            }.get(r["category"], "badge-noise")
            
            b_val = (r["b_months"] or 0.5) if r["in_b"] else 0.0
            i_val = (r["i_months"] or 0.5) if r["in_i"] else 0.0
            
            delta_pill_class = "pill-pos" if i_val > b_val else ("pill-neg" if i_val < b_val else "pill-neutral")
            
            rows.append(f"""<tr class="skill-row {'noise-row' if is_noise else ''}" 
                data-name="{r['name'].lower()}" 
                data-cat="{r['category']}" 
                data-weight="{r['weight']}"
                data-in-b="{'1' if r['in_b'] else '0'}"
                data-in-i="{'1' if r['in_i'] else '0'}">
              <td style="width: 40px; text-align: center;">
                <input type="checkbox" class="ignore-checkbox" onchange="toggleIgnoreSkill('{r['name']}', this)" {'checked' if is_noise else ''}>
              </td>
              <td style="font-weight: 600;">{r['name']}</td>
              <td><span class="badge {cat_badge_class}">{r['category'].replace('_', ' ')}</span></td>
              <td>{r['base_disp']} <span style="font-size:0.75rem;color:var(--text-secondary);">({r['base_last']})</span></td>
              <td>{r['imp_disp']} <span style="font-size:0.75rem;color:var(--text-secondary);">({r['imp_last']})</span></td>
              <td><span class="delta-pill {delta_pill_class}">{r['imp_disp']} vs {r['base_disp']}</span></td>
              <td style="font-size: 0.8rem; color: var(--text-secondary);">{r['reason']}</td>
            </tr>""")
        return "".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Affinda ATS Resume Comparison & Signal Dashboard</title>
<style>
  :root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-hover: #334155;
    --border: #334155;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --accent: #38bdf8;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #eab308;
    --purple: #c084fc;
    --badge-bg: #0f172a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 24px;
  }}
  .container {{ max-width: 1250px; margin: 0 auto; }}
  
  header {{
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }}
  h1 {{ font-size: 1.75rem; font-weight: 700; color: #fff; }}
  .subtitle {{ color: var(--text-secondary); font-size: 0.9rem; }}
  
  .scorecard-banner {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
  .kpi-title {{ font-size: 0.8rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 1.75rem; font-weight: 700; margin-top: 4px; display: flex; align-items: baseline; gap: 8px; }}
  .delta-pill {{
    font-size: 0.75rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 9999px;
  }}
  .pill-pos {{ background: rgba(34, 197, 94, 0.15); color: var(--green); }}
  .pill-neg {{ background: rgba(239, 68, 68, 0.15); color: var(--red); }}
  .pill-neutral {{ background: rgba(148, 163, 184, 0.15); color: var(--text-secondary); }}
  
  .section-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 20px;
    overflow: hidden;
  }}
  .section-header {{
    padding: 16px 20px;
    background: var(--surface);
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid transparent;
    transition: background 0.15s;
  }}
  .section-header:hover {{ background: var(--surface-hover); }}
  .section-header.open {{ border-bottom-color: var(--border); }}
  .section-title {{ font-size: 1.1rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }}
  .chevron {{ transition: transform 0.2s; font-size: 0.8rem; color: var(--text-secondary); }}
  .section-header.open .chevron {{ transform: rotate(180deg); }}
  
  .section-content {{ padding: 20px; display: none; }}
  .section-content.open {{ display: block; }}
  
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; text-align: left; }}
  th, td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  th {{ background: rgba(15, 23, 42, 0.6); color: var(--text-secondary); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }}
  tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
  
  .skill-row.ignored {{
    opacity: 0.35;
    text-decoration: line-through;
    filter: grayscale(80%);
  }}
  
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--badge-bg);
    border: 1px solid var(--border);
    white-space: nowrap;
  }}
  .badge-hard {{ border-color: #38bdf8; color: #38bdf8; }}
  .badge-qa {{ border-color: #22c55e; color: #22c55e; }}
  .badge-proc {{ border-color: #c084fc; color: #c084fc; }}
  .badge-noise {{ border-color: #ef4444; color: #ef4444; }}
  
  .controls-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 16px;
    padding: 12px;
    background: rgba(15, 23, 42, 0.5);
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .filter-group {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .filter-btn {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .filter-btn.active {{ background: var(--accent); color: #0f172a; border-color: var(--accent); font-weight: 600; }}
  .search-input {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text-primary);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    width: 240px;
  }}
  .search-input:focus {{ outline: 1px solid var(--accent); border-color: var(--accent); }}
  
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .diff-col {{ background: rgba(15, 23, 42, 0.3); padding: 14px; border-radius: 8px; border: 1px solid var(--border); }}
  .diff-col h4 {{ font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; }}
  .val-row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }}
  .val-label {{ color: var(--text-secondary); font-size: 0.85rem; }}
  .val-data {{ font-weight: 500; font-size: 0.85rem; }}
</style>
</head>
<body>

<div class="container">
  <header>
    <div>
      <h1>Affinda ATS Resume Comparison & Signal Dashboard</h1>
      <div class="subtitle">Target Role: <strong>{target_role}</strong> | Relative ATS Delta: (Improved - Baseline) / Baseline</div>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="filter-btn" onclick="resetIgnoredSkills()" title="Reset all ignored checkboxes">↺ Reset Ignored</button>
      <span class="badge" style="background: rgba(56, 189, 248, 0.1); color: var(--accent); border-color: var(--accent);">Affinda US1 + Gemini Flash</span>
    </div>
  </header>

  <!-- Top Executive Scorecards: (Improved - Baseline) / Baseline -->
  <div class="scorecard-banner">
    <div class="kpi-card">
      <div class="kpi-title">Overall ATS Score Delta</div>
      <div class="kpi-value" style="color: {'var(--green)' if all_delta_pct >= 0 else 'var(--red)'};">
        <span id="kpi-all-val">{all_delta_pct:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-all-sub">
        Baseline: {cat_pts['ALL']['b']:.0f} pts → Improved: {cat_pts['ALL']['i']:.0f} pts
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-title">Hard Tech & Tools Delta</div>
      <div class="kpi-value" style="color: {'var(--green)' if hard_delta_pct >= 0 else 'var(--red)'};">
        <span id="kpi-hard-val">{hard_delta_pct:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-hard-sub">
        Baseline: {cat_pts['HARD_TECH']['b_cnt']} tools → Improved: {cat_pts['HARD_TECH']['i_cnt']} tools
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-title">QA Methodologies Delta</div>
      <div class="kpi-value" style="color: {'var(--green)' if qa_delta_pct >= 0 else 'var(--red)'};">
        <span id="kpi-qa-val">{qa_delta_pct:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-qa-sub">
        Baseline: {cat_pts['QA_METHODOLOGY']['b_cnt']} practices → Improved: {cat_pts['QA_METHODOLOGY']['i_cnt']} practices
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-title">Process & Leadership Delta</div>
      <div class="kpi-value" style="color: {'var(--green)' if proc_delta_pct >= 0 else 'var(--red)'};">
        <span id="kpi-proc-val">{proc_delta_pct:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-proc-sub">
        Baseline: {cat_pts['PROCESS_LEADERSHIP']['b_cnt']} skills → Improved: {cat_pts['PROCESS_LEADERSHIP']['i_cnt']} skills
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-title">Filtered Noise Keywords</div>
      <div class="kpi-value" style="color: {'var(--green)' if noise_delta_pct <= 0 else 'var(--red)'};">
        <span id="kpi-noise-val">{noise_delta_pct:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-noise-sub">
        Baseline: {b_noise_cnt} artifacts → Improved: {i_noise_cnt} artifacts
      </div>
    </div>
  </div>

  <!-- SECTION 1: PROFILE METADATA -->
  <div class="section-card">
    <div class="section-header open" onclick="toggleSection(this)">
      <div class="section-title">
        <span>👤 1. Profile & Contact Metadata</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content open">
      <div class="grid-2">
        <div class="diff-col">
          <h4>Baseline Resume</h4>
          <div class="val-row"><span class="val-label">Full Name</span><span class="val-data">{b.get('name', {}).get('raw', '-')}</span></div>
          <div class="val-row"><span class="val-label">Profession</span><span class="val-data">{b.get('profession', '-')}</span></div>
          <div class="val-row"><span class="val-label">Email</span><span class="val-data">{(b.get('emails') or ['-'])[0]}</span></div>
          <div class="val-row"><span class="val-label">Phone</span><span class="val-data">{(b.get('phoneNumbers') or ['-'])[0]}</span></div>
          <div class="val-row"><span class="val-label">Location</span><span class="val-data">{b.get('location', {}).get('formatted', '-')}</span></div>
          <div class="val-row"><span class="val-label">LinkedIn</span><span class="val-data">{b.get('linkedin', '-')}</span></div>
          <div class="val-row"><span class="val-label">Languages</span><span class="val-data">{', '.join(b.get('languages', []))}</span></div>
        </div>
        <div class="diff-col">
          <h4>Improved Resume</h4>
          <div class="val-row"><span class="val-label">Full Name</span><span class="val-data">{i.get('name', {}).get('raw', '-')}</span></div>
          <div class="val-row"><span class="val-label">Profession</span><span class="val-data">{i.get('profession', '-')}</span></div>
          <div class="val-row"><span class="val-label">Email</span><span class="val-data">{(i.get('emails') or ['-'])[0]}</span></div>
          <div class="val-row"><span class="val-label">Phone</span><span class="val-data">{(i.get('phoneNumbers') or ['-'])[0]}</span></div>
          <div class="val-row"><span class="val-label">Location</span><span class="val-data">{i.get('location', {}).get('formatted', '-')}</span></div>
          <div class="val-row"><span class="val-label">LinkedIn</span><span class="val-data">{i.get('linkedin', '-')}</span></div>
          <div class="val-row"><span class="val-label">Languages</span><span class="val-data">{', '.join(i.get('languages', []))}</span></div>
        </div>
      </div>
      <div style="margin-top: 14px;">
        <h4 style="font-size: 0.8rem; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 6px;">Parsed Summary Comparison</h4>
        <div class="grid-2">
          <div style="background: rgba(15,23,42,0.5); padding: 12px; border-radius: 6px; font-size: 0.85rem; color: var(--text-secondary);">{b.get('summary', '-')}</div>
          <div style="background: rgba(15,23,42,0.5); padding: 12px; border-radius: 6px; font-size: 0.85rem; color: var(--text-secondary);">{i.get('summary', '-')}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- SECTION 2: EDUCATION -->
  <div class="section-card">
    <div class="section-header open" onclick="toggleSection(this)">
      <div class="section-title">
        <span>🎓 2. Education & Certifications</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content open">
      <div class="grid-2">
        <div class="diff-col">
          <h4>Baseline Education ({len(b.get('education', []))})</h4>
          {''.join([f'''<div style="margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border);">
            <div style="font-weight: 600; color: #fff;">{e.get('accreditation', {}).get('education') or e.get('degree') or 'Degree'}</div>
            <div style="color: var(--accent); font-size: 0.85rem;">{e.get('organization')}</div>
            <div style="color: var(--text-secondary); font-size: 0.75rem;">Dates: {e.get('dates', {}).get('rawText', '-')} | Level: {e.get('accreditation', {}).get('educationLevel', '-')}</div>
          </div>''' for e in b.get('education', [])])}
          
          <h4 style="margin-top: 14px;">Baseline Certifications ({len(b.get('certifications', []))})</h4>
          <ul style="padding-left: 18px; font-size: 0.85rem; color: var(--text-secondary);">
            {''.join([f'<li style="margin-bottom: 4px;">{c}</li>' for c in b.get('certifications', [])])}
          </ul>
        </div>
        
        <div class="diff-col">
          <h4>Improved Education ({len(i.get('education', []))})</h4>
          {''.join([f'''<div style="margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border);">
            <div style="font-weight: 600; color: #fff;">{e.get('accreditation', {}).get('education') or e.get('degree') or 'Degree'}</div>
            <div style="color: var(--accent); font-size: 0.85rem;">{e.get('organization')}</div>
            <div style="color: var(--text-secondary); font-size: 0.75rem;">Dates: {e.get('dates', {}).get('rawText', '-')} | Level: {e.get('accreditation', {}).get('educationLevel', '-')}</div>
          </div>''' for e in i.get('education', [])])}
          
          <h4 style="margin-top: 14px;">Improved Certifications ({len(i.get('certifications', []))})</h4>
          <ul style="padding-left: 18px; font-size: 0.85rem; color: var(--text-secondary);">
            {''.join([f'<li style="margin-bottom: 4px;">{c}</li>' for c in i.get('certifications', [])])}
          </ul>
        </div>
      </div>
    </div>
  </div>

  <!-- SECTION 3: WORK EXP METADATA -->
  <div class="section-card">
    <div class="section-header open" onclick="toggleSection(this)">
      <div class="section-title">
        <span>💼 3. Work Experience Role Progression</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content open">
      <div class="grid-2">
        <div class="diff-col">
          <h4>Baseline Roles (1 Lump Position)</h4>
          {''.join([f'''<div style="background: rgba(15,23,42,0.4); padding: 12px; border-radius: 6px; margin-bottom: 10px;">
            <div style="font-weight: 600; color: #fff;">{w.get('jobTitle')}</div>
            <div style="color: var(--accent); font-size: 0.85rem;">{w.get('organization')}</div>
            <div style="color: var(--text-secondary); font-size: 0.75rem; margin-top: 4px;">
              Duration: {w.get('dates', {}).get('rawText', '-')} ({w.get('dates', {}).get('monthsInPosition', '-')} months)
            </div>
          </div>''' for w in b.get('workExperience', [])])}
        </div>
        <div class="diff-col">
          <h4>Improved Roles (3 Tiered Positions)</h4>
          {''.join([f'''<div style="background: rgba(15,23,42,0.4); padding: 12px; border-radius: 6px; margin-bottom: 10px;">
            <div style="font-weight: 600; color: #fff;">{w.get('jobTitle')}</div>
            <div style="color: var(--accent); font-size: 0.85rem;">{w.get('organization')}</div>
            <div style="color: var(--text-secondary); font-size: 0.75rem; margin-top: 4px;">
              Duration: {w.get('dates', {}).get('rawText', '-')} ({w.get('dates', {}).get('monthsInPosition', '-')} months)
            </div>
          </div>''' for w in i.get('workExperience', [])])}
        </div>
      </div>
    </div>
  </div>

  <!-- SECTION 4: SKILLS CONTROLS & FILTERING -->
  <div class="controls-bar">
    <div class="filter-group">
      <span style="font-size: 0.8rem; color: var(--text-secondary); font-weight: 600;">FILTER CATEGORY:</span>
      <button class="filter-btn active" onclick="filterCategory('ALL_SIGNAL', this)">All Signal Skills ({len(all_skill_names) - len(noise_items)})</button>
      <button class="filter-btn" onclick="filterCategory('HARD_TECH', this)">Hard Tech & Tools</button>
      <button class="filter-btn" onclick="filterCategory('QA_METHODOLOGY', this)">QA Methodologies</button>
      <button class="filter-btn" onclick="filterCategory('PROCESS_LEADERSHIP', this)">Process & Leadership</button>
      <button class="filter-btn" onclick="filterCategory('PARSER_NOISE', this)" style="border-color: rgba(239,68,68,0.4);">Filtered Noise ({len(noise_items)})</button>
    </div>
    <div>
      <input type="text" class="search-input" id="skillSearch" placeholder="Search skill name..." onkeyup="filterSkillSearch()">
    </div>
  </div>

  <!-- SECTION 4A: LESS REPRESENTATION -->
  <div class="section-card">
    <div class="section-header open" onclick="toggleSection(this)">
      <div class="section-title">
        <span style="color: var(--red);">📉 4a. Signal Skills with Less Representation (<span id="count-less">{len(less_rep)}</span>)</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content open">
      <table class="skill-table" id="table-less">
        <thead>
          <tr>
            <th style="width: 40px;">Ignore</th>
            <th>Skill Name</th>
            <th>Category</th>
            <th>Baseline</th>
            <th>Improved</th>
            <th>Delta Representation</th>
            <th>Classification Rationale</th>
          </tr>
        </thead>
        <tbody>
          {render_table_rows(less_rep)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- SECTION 4B: MORE REPRESENTATION -->
  <div class="section-card">
    <div class="section-header open" onclick="toggleSection(this)">
      <div class="section-title">
        <span style="color: var(--green);">📈 4b. Signal Skills with More Representation (<span id="count-more">{len(more_rep)}</span>)</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content open">
      <table class="skill-table" id="table-more">
        <thead>
          <tr>
            <th style="width: 40px;">Ignore</th>
            <th>Skill Name</th>
            <th>Category</th>
            <th>Baseline</th>
            <th>Improved</th>
            <th>Delta Representation</th>
            <th>Classification Rationale</th>
          </tr>
        </thead>
        <tbody>
          {render_table_rows(more_rep)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- SECTION 4C: OTHER SKILLS (EQUAL) -->
  <div class="section-card">
    <div class="section-header" onclick="toggleSection(this)">
      <div class="section-title">
        <span>⚖️ 4c. Other Signal Skills (Equal Representation) (<span id="count-other">{len(other_rep)}</span>)</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content">
      <table class="skill-table" id="table-other">
        <thead>
          <tr>
            <th style="width: 40px;">Ignore</th>
            <th>Skill Name</th>
            <th>Category</th>
            <th>Baseline</th>
            <th>Improved</th>
            <th>Status</th>
            <th>Classification Rationale</th>
          </tr>
        </thead>
        <tbody>
          {render_table_rows(other_rep)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- SECTION 5: PARSER NOISE QUARANTINE -->
  <div class="section-card" style="border-color: rgba(239, 68, 68, 0.3);">
    <div class="section-header" onclick="toggleSection(this)">
      <div class="section-title">
        <span style="color: var(--text-secondary);">🗑️ 5. Quarantined Parser Artifacts & Fluff ({len(noise_items)})</span>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="section-content">
      <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 12px;">
        These items were automatically identified by Gemini as parser hallucinations or generic English words. They are excluded from your score and comparisons by default.
      </p>
      <table class="skill-table" id="table-noise">
        <thead>
          <tr>
            <th style="width: 40px;">Un-ignore</th>
            <th>Skill Name</th>
            <th>Category</th>
            <th>Baseline</th>
            <th>Improved</th>
            <th>Status</th>
            <th>Classifier Reason</th>
          </tr>
        </thead>
        <tbody>
          {render_table_rows(noise_items, is_noise=True)}
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
let currentCategory = 'ALL_SIGNAL';
let currentSearchText = '';
let ignoredSkills = new Set();

const CAT_WEIGHTS = {{
  'HARD_TECH': 4.0,
  'QA_METHODOLOGY': 3.0,
  'PROCESS_LEADERSHIP': 2.0
}};

function initIgnoredSkills() {{
  const saved = localStorage.getItem('affinda_ignored_skills');
  if (saved) {{
    try {{
      const arr = JSON.parse(saved);
      arr.forEach(s => ignoredSkills.add(s));
    }} catch(e) {{}}
  }}
  
  document.querySelectorAll('.skill-row').forEach(row => {{
    const name = row.querySelector('td:nth-child(2)').innerText.trim();
    const chk = row.querySelector('.ignore-checkbox');
    if (ignoredSkills.has(name)) {{
      chk.checked = true;
      row.classList.add('ignored');
    }} else if (!row.classList.contains('noise-row')) {{
      chk.checked = false;
      row.classList.remove('ignored');
    }}
  }});
  
  recalculateDelta();
  applyFilters();
}}

function toggleSection(headerEl) {{
  headerEl.classList.toggle('open');
  const contentEl = headerEl.nextElementSibling;
  contentEl.classList.toggle('open');
}}

function toggleIgnoreSkill(skillName, checkboxEl) {{
  const row = checkboxEl.closest('tr');
  if (checkboxEl.checked) {{
    ignoredSkills.add(skillName);
    row.classList.add('ignored');
  }} else {{
    ignoredSkills.delete(skillName);
    row.classList.remove('ignored');
  }}
  localStorage.setItem('affinda_ignored_skills', JSON.stringify(Array.from(ignoredSkills)));
  recalculateDelta();
}}

function resetIgnoredSkills() {{
  ignoredSkills.clear();
  localStorage.removeItem('affinda_ignored_skills');
  document.querySelectorAll('.skill-row').forEach(row => {{
    const chk = row.querySelector('.ignore-checkbox');
    if (row.classList.contains('noise-row')) {{
      chk.checked = true;
      row.classList.add('ignored');
    }} else {{
      chk.checked = false;
      row.classList.remove('ignored');
    }}
  }});
  recalculateDelta();
  applyFilters();
}}

function recalculateDelta() {{
  let stats = {{
    'ALL': {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }},
    'HARD_TECH': {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }},
    'QA_METHODOLOGY': {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }},
    'PROCESS_LEADERSHIP': {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }}
  }};
  let noiseStats = {{ b_cnt: 0, i_cnt: 0 }};
  
  document.querySelectorAll('.skill-row').forEach(row => {{
    const cat = row.getAttribute('data-cat');
    const chk = row.querySelector('.ignore-checkbox');
    const inB = row.getAttribute('data-in-b') === '1';
    const inI = row.getAttribute('data-in-i') === '1';
    
    if (cat === 'PARSER_NOISE') {{
      if (inB) noiseStats.b_cnt++;
      if (inI) noiseStats.i_cnt++;
    }} else if (!chk.checked) {{
      const weight = CAT_WEIGHTS[cat] || 1.0;
      
      if (inB) {{ stats['ALL'].b_pts += weight; stats['ALL'].b_cnt++; }}
      if (inI) {{ stats['ALL'].i_pts += weight; stats['ALL'].i_cnt++; }}
      
      if (stats[cat]) {{
        if (inB) {{ stats[cat].b_pts += weight; stats[cat].b_cnt++; }}
        if (inI) {{ stats[cat].i_pts += weight; stats[cat].i_cnt++; }}
      }}
    }}
  }});
  
  // (improved - baseline) / baseline * 100%
  function getPct(b, i) {{
    if (b <= 0) return 0;
    return ((i - b) / b) * 100;
  }}
  
  const allDelta = getPct(stats['ALL'].b_pts, stats['ALL'].i_pts);
  const allEl = document.getElementById('kpi-all-val');
  allEl.innerText = `${{allDelta >= 0 ? '+' : ''}}${{allDelta.toFixed(1)}}%`;
  allEl.parentElement.style.color = allDelta >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('kpi-all-sub').innerText = `Baseline: ${{stats['ALL'].b_pts.toFixed(0)}} pts → Improved: ${{stats['ALL'].i_pts.toFixed(0)}} pts`;

  updateCatDelta('hard', stats['HARD_TECH'], 'tools');
  updateCatDelta('qa', stats['QA_METHODOLOGY'], 'practices');
  updateCatDelta('proc', stats['PROCESS_LEADERSHIP'], 'skills');

  const noiseDelta = noiseStats.b_cnt > 0 ? (((noiseStats.i_cnt - noiseStats.b_cnt) / noiseStats.b_cnt) * 100) : 0;
  const noiseEl = document.getElementById('kpi-noise-val');
  if (noiseEl) {{
    noiseEl.innerText = `${{noiseDelta >= 0 ? '+' : ''}}${{noiseDelta.toFixed(1)}}%`;
    noiseEl.parentElement.style.color = noiseDelta <= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('kpi-noise-sub').innerText = `Baseline: ${{noiseStats.b_cnt}} artifacts → Improved: ${{noiseStats.i_cnt}} artifacts`;
  }}
}}

function updateCatDelta(prefix, catStat, unitName) {{
  if (!catStat) return;
  const delta = (catStat.b_pts > 0) ? (((catStat.i_pts - catStat.b_pts) / catStat.b_pts) * 100) : 0;
  
  const el = document.getElementById(`kpi-${{prefix}}-val`);
  el.innerText = `${{delta >= 0 ? '+' : ''}}${{delta.toFixed(1)}}%`;
  el.parentElement.style.color = delta >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById(`kpi-${{prefix}}-sub`).innerText = `Baseline: ${{catStat.b_cnt}} ${{unitName}} → Improved: ${{catStat.i_cnt}} ${{unitName}}`;
}}

function filterCategory(cat, btnEl) {{
  currentCategory = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btnEl.classList.add('active');
  applyFilters();
}}

function filterSkillSearch() {{
  currentSearchText = document.getElementById('skillSearch').value.toLowerCase().trim();
  applyFilters();
}}

function applyFilters() {{
  document.querySelectorAll('.skill-row').forEach(row => {{
    const rowCat = row.getAttribute('data-cat') || '';
    const rowName = row.getAttribute('data-name') || '';
    
    let matchesCat = false;
    if (currentCategory === 'ALL_SIGNAL') {{
      matchesCat = (rowCat !== 'PARSER_NOISE');
    }} else {{
      matchesCat = (rowCat === currentCategory);
    }}
    
    let matchesSearch = (currentSearchText === '') || rowName.includes(currentSearchText);
    
    if (matchesCat && matchesSearch) {{
      row.style.display = '';
    }} else {{
      row.style.display = 'none';
    }}
  }});
}}

window.addEventListener('DOMContentLoaded', initIgnoredSkills);
</script>

</body>
</html>
"""

    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Generated percentage delta dashboard: {output_filepath}")

def main():
    print("🚀 FETCHING RESUMES & CHECKING AFFINDA HASH CACHE...")
    results = {}
    for key, info in DOCS.items():
        print(f"📥 Loading {info['name']}...")
        pdf_bytes = fetch_pdf_bytes(info["id"])
        results[key] = call_affinda_with_cache(pdf_bytes, info["filename"])
        
    out_html = PROJECT_ROOT / "ats_comparison.html"
    generate_html_report(results["baseline"], results["improved"], str(out_html))

if __name__ == "__main__":
    main()

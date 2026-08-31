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

def parse_doc_id(id_or_url):
    """Extract Google Doc/Drive ID from a URL or return as-is if already an ID."""
    import re
    # Match: /d/{id}/ or /d/{id} at end, or ?id={id}
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', id_or_url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', id_or_url)
    if m:
        return m.group(1)
    # Assume it's already a raw ID
    return id_or_url.strip()

def fetch_pdf_bytes(doc_id_or_url):
    doc_id = parse_doc_id(doc_id_or_url)
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

def extract_resume_target_role(doc_data, fallback_name="Software Development Engineer"):
    """Extracts target role from parsed resume work experience or profession."""
    d = doc_data.get("data", {})
    work_exp = d.get("workExperience", [])
    if work_exp and work_exp[0].get("jobTitle"):
        return work_exp[0].get("jobTitle")
    if d.get("profession"):
        return d.get("profession")
    return fallback_name

def get_or_generate_taxonomy_definition(target_role):
    """Step 1: Generate role-specific taxonomy categories via Gemini. Cached per role."""
    import re
    role_slug = re.sub(r'[^a-zA-Z0-9]+', '_', target_role.lower()).strip('_')
    def_file = CACHE_DIR / f"taxonomy_def_{role_slug}.json"
    
    if def_file.exists():
        with open(def_file, "r") as f:
            return json.load(f)
    
    print(f"🧠 Step 1: Generating taxonomy categories for '{target_role}' via Gemini...")
    prompt = f"""You are an expert ATS (Applicant Tracking System) and Technical Recruiting specialist.

For the role of "{target_role}", generate the skill taxonomy categories that an ATS system would use to evaluate resumes for this role.

For each category, provide:
- A short machine-readable ID (UPPER_SNAKE_CASE)
- A human-readable name
- A description of what skills belong in this category
- A weight (1-5) representing how important this category is for ATS scoring for this specific role
- 5-8 example skills that belong in this category

Also include a "PARSER_NOISE" category for non-technical filler words and parser artifacts, with weight 0.

Return ONLY a valid JSON object:
{{
  "role": "{target_role}",
  "categories": [
    {{
      "id": "CATEGORY_ID",
      "name": "Human Readable Name",
      "description": "What belongs here",
      "weight": 4,
      "examples": ["Skill1", "Skill2"]
    }}
  ]
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0, "seed": 42}
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=120) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
            taxonomy_def = json.loads(text_content)
        
        with open(def_file, "w") as f:
            json.dump(taxonomy_def, f, indent=2)
        
        cats = taxonomy_def.get("categories", [])
        for c in cats:
            print(f"   • {c['id']} (weight={c['weight']}): {c['name']}")
        print(f"   💾 Saved taxonomy definition to .cache/taxonomy_def_{role_slug}.json")
        return taxonomy_def
    except Exception as e:
        print(f"   ⚠️ Taxonomy generation error: {e}. Using fallback categories.")
        fallback = {
            "role": target_role,
            "categories": [
                {"id": "TECHNICAL_SKILLS", "name": "Technical Skills", "description": "All technical skills", "weight": 4, "examples": []},
                {"id": "METHODOLOGY", "name": "Methodology & Practices", "description": "Methodologies and practices", "weight": 3, "examples": []},
                {"id": "LEADERSHIP", "name": "Leadership & Process", "description": "Leadership and process skills", "weight": 2, "examples": []},
                {"id": "PARSER_NOISE", "name": "Parser Noise", "description": "Non-technical filler", "weight": 0, "examples": []}
            ]
        }
        with open(def_file, "w") as f:
            json.dump(fallback, f, indent=2)
        return fallback


def get_or_classify_taxonomy(skill_names, target_role, taxonomy_def):
    """Step 2: Classify skills into taxonomy categories. Incremental cache per role."""
    import re
    role_slug = re.sub(r'[^a-zA-Z0-9]+', '_', target_role.lower()).strip('_')
    taxonomy_file = CACHE_DIR / f"taxonomy_{role_slug}.json"
    
    taxonomy = {}
    if taxonomy_file.exists():
        with open(taxonomy_file, "r") as f:
            taxonomy = json.load(f)
            
    unclassified = [s for s in skill_names if s not in taxonomy]
    if not unclassified:
        return taxonomy
    
    # Build category context from taxonomy definition
    categories = taxonomy_def.get("categories", [])
    cat_descriptions = "\n".join([
        f'- "{c["id"]}": {c["name"]} — {c["description"]}. Examples: {", ".join(c.get("examples", []))}'
        for c in categories
    ])
    valid_ids = [c["id"] for c in categories]
    
    print(f"🤖 Step 2: Classifying {len(unclassified)} skills for '{target_role}' via Gemini...")
    prompt = f"""You are an expert ATS & Technical Recruiting Classifier for {target_role} roles.

The following taxonomy categories have been defined for this role:
{cat_descriptions}

Classify each of the following raw skill strings into EXACTLY ONE of the categories listed above.
If a skill does not clearly belong to any technical category, classify it as "PARSER_NOISE".

Skills to classify:
{json.dumps(unclassified, indent=2)}

Return ONLY a valid JSON object:
{{
  "skill_name": {{
    "category": "CATEGORY_ID",
    "reason": "short explanation"
  }}
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0, "seed": 42}
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=120) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
            new_classifications = json.loads(text_content)
            
        # Validate categories — if Gemini returns an unknown category, map to PARSER_NOISE
        for k, v in new_classifications.items():
            if v.get("category") not in valid_ids:
                v["category"] = "PARSER_NOISE"
                v["reason"] = f"Category '{v.get('category')}' not in taxonomy; defaulted to PARSER_NOISE"
            taxonomy[k] = v
            
        with open(taxonomy_file, "w") as f:
            json.dump(taxonomy, f, indent=2)
        print(f"   💾 Saved {len(new_classifications)} classifications to .cache/taxonomy_{role_slug}.json")
    except Exception as e:
        print(f"   ⚠️ Gemini classification notice: {e}. Defaulting new skills to PARSER_NOISE.")
        for s in unclassified:
            taxonomy[s] = {"category": "PARSER_NOISE", "reason": "Unclassified fallback"}
    return taxonomy

def generate_html_report(base_data, imp_data, output_filepath):
    b = base_data.get("data", {})
    i = imp_data.get("data", {})
    
    b_role = extract_resume_target_role(base_data, "Baseline Role")
    i_role = extract_resume_target_role(imp_data, "Improved Role")
    print(f"🎯 Baseline Resume Target Role: '{b_role}'")
    print(f"🎯 Improved Resume Target Role: '{i_role}'")
    
    # Step 1: Generate taxonomy definitions
    b_tax_def = get_or_generate_taxonomy_definition(b_role)
    i_tax_def = b_tax_def if b_role == i_role else get_or_generate_taxonomy_definition(i_role)
    
    b_skills = {s["name"]: s for s in b.get("skills", []) if s.get("name")}
    i_skills = {s["name"]: s for s in i.get("skills", []) if s.get("name")}
    all_skill_names = sorted(list(set(b_skills.keys()).union(set(i_skills.keys()))))
    
    # Step 2: Classify skills into taxonomy categories
    base_taxonomy = get_or_classify_taxonomy(list(b_skills.keys()), target_role=b_role, taxonomy_def=b_tax_def)
    imp_taxonomy = get_or_classify_taxonomy(list(i_skills.keys()), target_role=i_role, taxonomy_def=i_tax_def)
    
    # Build weight lookups from taxonomy definitions
    b_weights = {c["id"]: float(c["weight"]) for c in b_tax_def.get("categories", [])}
    i_weights = {c["id"]: float(c["weight"]) for c in i_tax_def.get("categories", [])}
    
    # Build union of all non-noise categories across both taxonomies
    b_cat_info = {c["id"]: c for c in b_tax_def.get("categories", []) if c["id"] != "PARSER_NOISE"}
    i_cat_info = {c["id"]: c for c in i_tax_def.get("categories", []) if c["id"] != "PARSER_NOISE"}
    union_cat_ids = sorted(set(b_cat_info.keys()) | set(i_cat_info.keys()),
                           key=lambda cid: max(b_weights.get(cid, 0), i_weights.get(cid, 0)),
                           reverse=True)
    # Merge category metadata (prefer the one with higher weight)
    union_cat_meta = {}
    for cid in union_cat_ids:
        if cid in b_cat_info and cid in i_cat_info:
            union_cat_meta[cid] = b_cat_info[cid] if b_weights.get(cid, 0) >= i_weights.get(cid, 0) else i_cat_info[cid]
        elif cid in b_cat_info:
            union_cat_meta[cid] = b_cat_info[cid]
        else:
            union_cat_meta[cid] = i_cat_info[cid]
    
    less_rep = []
    more_rep = []
    other_rep = []
    noise_items = []
    
    cat_pts = {"ALL": {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0}}
    for cid in union_cat_ids:
        cat_pts[cid] = {"b": 0.0, "i": 0.0, "b_cnt": 0, "i_cnt": 0}
    
    for name in all_skill_names:
        in_b = name in b_skills
        in_i = name in i_skills
        bs = b_skills.get(name, {})
        is_ = i_skills.get(name, {})
        
        b_tax = base_taxonomy.get(name, {}) if in_b else {}
        i_tax = imp_taxonomy.get(name, {}) if in_i else {}
        
        b_cat = b_tax.get("category", "PARSER_NOISE")
        i_cat = i_tax.get("category", "PARSER_NOISE")
        
        b_weight = b_weights.get(b_cat, 0.0)
        i_weight = i_weights.get(i_cat, 0.0)
        
        # Primary category & reason for row rendering
        display_cat = i_cat if in_i else b_cat
        display_reason = i_tax.get("reason") if in_i else b_tax.get("reason", "")
        
        b_months = bs.get("numberOfMonths")
        i_months = is_.get("numberOfMonths")
        
        b_disp = f"{b_months} mos" if b_months is not None else ("Yes" if in_b else "No")
        i_disp = f"{i_months} mos" if i_months is not None else ("Yes" if in_i else "No")
        b_last = bs.get("lastUsed") or "-"
        i_last = is_.get("lastUsed") or "-"
        
        row_data = {
            "name": name,
            "category": display_cat,
            "reason": display_reason,
            "b_cat": b_cat,
            "i_cat": i_cat,
            "b_weight": b_weight,
            "i_weight": i_weight,
            "in_b": in_b,
            "in_i": in_i,
            "b_months": b_months,
            "i_months": i_months,
            "base_disp": b_disp,
            "imp_disp": i_disp,
            "base_last": b_last,
            "imp_last": i_last
        }
        
        is_noise = (display_cat == "PARSER_NOISE")
        if is_noise:
            noise_items.append(row_data)
        else:
            if in_b and b_cat != "PARSER_NOISE":
                cat_pts["ALL"]["b"] += b_weight
                cat_pts["ALL"]["b_cnt"] += 1
                if b_cat in cat_pts:
                    cat_pts[b_cat]["b"] += b_weight
                    cat_pts[b_cat]["b_cnt"] += 1
                    
            if in_i and i_cat != "PARSER_NOISE":
                cat_pts["ALL"]["i"] += i_weight
                cat_pts["ALL"]["i_cnt"] += 1
                if i_cat in cat_pts:
                    cat_pts[i_cat]["i"] += i_weight
                    cat_pts[i_cat]["i_cnt"] += 1
            
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

    b_noise_cnt = sum(1 for r in noise_items if r['in_b'])
    i_noise_cnt = sum(1 for r in noise_items if r['in_i'])
    noise_delta_pct = calc_delta_pct(b_noise_cnt, i_noise_cnt)

    print("=" * 80)
    print("📊 ATS POINT AUDIT LOG & BREAKDOWN:")
    print("=" * 80)
    print(f"BASELINE RESUME (Total: {cat_pts['ALL']['b']:.0f} pts):")
    for cid in union_cat_ids:
        meta = union_cat_meta[cid]
        w = b_weights.get(cid, 0)
        print(f"  • {meta['name']:40s} {cat_pts[cid]['b_cnt']:2d} skills × {w:.0f} pts = {cat_pts[cid]['b']:.0f} pts")
    print(f"  • {'Filtered Noise':40s} {b_noise_cnt:2d} artifacts")
    print(f"  -------------------------------------------------------------")
    print(f"  TOTAL BASELINE POINTS  = {cat_pts['ALL']['b']:.0f} pts")
    print()
    print(f"IMPROVED RESUME (Total: {cat_pts['ALL']['i']:.0f} pts):")
    for cid in union_cat_ids:
        meta = union_cat_meta[cid]
        w = i_weights.get(cid, 0)
        print(f"  • {meta['name']:40s} {cat_pts[cid]['i_cnt']:2d} skills × {w:.0f} pts = {cat_pts[cid]['i']:.0f} pts")
    print(f"  • {'Filtered Noise':40s} {i_noise_cnt:2d} artifacts ({noise_delta_pct:+.1f}% noise reduction)")
    print(f"  -------------------------------------------------------------")
    print(f"  TOTAL IMPROVED POINTS  = {cat_pts['ALL']['i']:.0f} pts")
    print(f"  NET SCORE DELTA:         {all_delta_pct:+.1f}% ((Improved - Baseline) / Baseline)")
    print("=" * 80)

    def render_table_rows(items, is_noise=False):
        rows = []
        for r in items:
            cat_badge_class = cat_badge_map.get(r["category"], "badge-noise")
            
            b_val = (r["b_months"] or 0.5) if r["in_b"] else 0.0
            i_val = (r["i_months"] or 0.5) if r["in_i"] else 0.0
            
            delta_pill_class = "pill-pos" if i_val > b_val else ("pill-neg" if i_val < b_val else "pill-neutral")
            
            rows.append(f"""<tr class="skill-row {'noise-row' if is_noise else ''}" 
                data-name="{r['name'].lower()}" 
                data-cat="{r['category']}" 
                data-b-cat="{r['b_cat']}"
                data-i-cat="{r['i_cat']}"
                data-b-weight="{r['b_weight']}"
                data-i-weight="{r['i_weight']}"
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

    role_display = f"Target Role: <strong>{b_role}</strong>" if b_role == i_role else f"Baseline: <strong>{b_role}</strong> vs. Improved: <strong>{i_role}</strong>"

    # Pre-compute dynamic KPI cards HTML
    kpi_cards_html = ""
    for cid in union_cat_ids:
        d = calc_delta_pct(cat_pts[cid]["b"], cat_pts[cid]["i"])
        color = "var(--green)" if d >= 0 else "var(--red)"
        kpi_cards_html += f"""
    <div class="kpi-card">
      <div class="kpi-title">{union_cat_meta[cid]['name']} Delta</div>
      <div class="kpi-value" style="color: {color};">
        <span id="kpi-{cid.lower()}-val">{d:+.1f}%</span>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;" id="kpi-{cid.lower()}-sub">
        Baseline: {cat_pts[cid]['b_cnt']} skills → Improved: {cat_pts[cid]['i_cnt']} skills
      </div>
    </div>
    """

    # Pre-compute dynamic filter buttons HTML
    filter_buttons_html = ""
    for cid in union_cat_ids:
        d = calc_delta_pct(cat_pts[cid]["b"], cat_pts[cid]["i"])
        color = "var(--green)" if d >= 0 else "var(--red)"
        filter_buttons_html += f'<button class="filter-btn" onclick="filterCategory(\'{cid}\', this)">{union_cat_meta[cid]["name"]} <span style="color: {color}; font-weight: 700;">{d:+.1f}%</span></button>'

    # Pre-compute CAT_WEIGHTS JSON for JS
    cat_weights_json = json.dumps({c["id"]: float(c["weight"]) for c in b_tax_def.get("categories", [])})

    # Pre-compute badge colors for each category
    badge_colors = [
        "#38bdf8",  # sky blue
        "#22c55e",  # green
        "#c084fc",  # purple
        "#f59e0b",  # amber
        "#ec4899",  # pink
        "#14b8a6",  # teal
        "#f97316",  # orange
        "#6366f1",  # indigo
        "#84cc16",  # lime
        "#06b6d4",  # cyan
    ]
    cat_badge_map = {"PARSER_NOISE": "badge-noise"}
    badge_css_rules = "  .badge-noise {{ border-color: #ef4444; color: #ef4444; }}\n"
    for idx, cid in enumerate(union_cat_ids):
        cls = f"badge-cat-{idx}"
        cat_badge_map[cid] = cls
        color = badge_colors[idx % len(badge_colors)]
        badge_css_rules += f"  .{cls} {{ border-color: {color}; color: {color}; }}\n"

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
  {badge_css_rules}
  
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
      <div class="subtitle">{role_display} | Relative ATS Delta: (Improved - Baseline) / Baseline</div>
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

    {kpi_cards_html}


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
      <button class="filter-btn active" onclick="filterCategory('ALL_SIGNAL', this)">All Signal Skills ({len(all_skill_names) - len(noise_items)}) <span style="color: {'var(--green)' if all_delta_pct >= 0 else 'var(--red)'}; font-weight: 700;">{all_delta_pct:+.1f}%</span></button>
      {filter_buttons_html}
      <button class="filter-btn" onclick="filterCategory('PARSER_NOISE', this)" style="border-color: rgba(239,68,68,0.4);">Filtered Noise ({len(noise_items)}) <span style="color: {'var(--green)' if noise_delta_pct <= 0 else 'var(--red)'}; font-weight: 700;">{noise_delta_pct:+.1f}%</span></button>
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
const CAT_WEIGHTS = {cat_weights_json};


function initIgnoredSkills() {{
  const saved = localStorage.getItem('ats_ignored_skills');
  if (saved) {{
    ignoredSkills = new Set(JSON.parse(saved));
  }}
  document.querySelectorAll('.skill-row').forEach(row => {{
    const name = row.getAttribute('data-name');
    const chk = row.querySelector('.ignore-checkbox');
    if (ignoredSkills.has(name)) {{
      chk.checked = true;
      row.classList.add('ignored');
    }} else if (row.classList.contains('noise-row')) {{
      chk.checked = true;
      row.classList.add('ignored');
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

function toggleIgnoreSkill(skillName, checkbox) {{
  const row = checkbox.closest('.skill-row');
  const name = row.getAttribute('data-name');
  if (checkbox.checked) {{
    ignoredSkills.add(name);
    row.classList.add('ignored');
  }} else {{
    ignoredSkills.delete(name);
    row.classList.remove('ignored');
  }}
  localStorage.setItem('ats_ignored_skills', JSON.stringify([...ignoredSkills]));
  recalculateDelta();
}}

function resetIgnoredSkills() {{
  localStorage.removeItem('ats_ignored_skills');
  ignoredSkills = new Set();
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
  const allCatIds = new Set();
  document.querySelectorAll('.skill-row').forEach(row => {{
    const bCat = row.getAttribute('data-b-cat');
    const iCat = row.getAttribute('data-i-cat');
    if (bCat && bCat !== 'PARSER_NOISE') allCatIds.add(bCat);
    if (iCat && iCat !== 'PARSER_NOISE') allCatIds.add(iCat);
  }});
  
  let stats = {{ 'ALL': {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }} }};
  allCatIds.forEach(cid => {{ stats[cid] = {{ b_pts: 0, i_pts: 0, b_cnt: 0, i_cnt: 0 }}; }});
  let noiseStats = {{ b_cnt: 0, i_cnt: 0 }};
  
  document.querySelectorAll('.skill-row').forEach(row => {{
    const cat = row.getAttribute('data-cat');
    const bCat = row.getAttribute('data-b-cat');
    const iCat = row.getAttribute('data-i-cat');
    const bWeight = parseFloat(row.getAttribute('data-b-weight') || '0');
    const iWeight = parseFloat(row.getAttribute('data-i-weight') || '0');
    const chk = row.querySelector('.ignore-checkbox');
    const inB = row.getAttribute('data-in-b') === '1';
    const inI = row.getAttribute('data-in-i') === '1';
    
    if (cat === 'PARSER_NOISE') {{
      if (inB) noiseStats.b_cnt++;
      if (inI) noiseStats.i_cnt++;
    }} else if (!chk.checked) {{
      if (inB && bCat !== 'PARSER_NOISE') {{
        stats['ALL'].b_pts += bWeight;
        stats['ALL'].b_cnt++;
        if (stats[bCat]) {{ stats[bCat].b_pts += bWeight; stats[bCat].b_cnt++; }}
      }}
      if (inI && iCat !== 'PARSER_NOISE') {{
        stats['ALL'].i_pts += iWeight;
        stats['ALL'].i_cnt++;
        if (stats[iCat]) {{ stats[iCat].i_pts += iWeight; stats[iCat].i_cnt++; }}
      }}
    }}
  }});
  
  function getPct(b, i) {{
    if (b <= 0) return 0;
    return ((i - b) / b) * 100;
  }}
  
  const allDelta = getPct(stats['ALL'].b_pts, stats['ALL'].i_pts);
  const allEl = document.getElementById('kpi-all-val');
  allEl.innerText = `${{allDelta >= 0 ? '+' : ''}}${{allDelta.toFixed(1)}}%`;
  allEl.parentElement.style.color = allDelta >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('kpi-all-sub').innerText = `Baseline: ${{stats['ALL'].b_pts.toFixed(0)}} pts → Improved: ${{stats['ALL'].i_pts.toFixed(0)}} pts`;

  allCatIds.forEach(cid => {{
    const el = document.getElementById(`kpi-${{cid.toLowerCase()}}-val`);
    if (el && stats[cid]) {{
      const delta = getPct(stats[cid].b_pts, stats[cid].i_pts);
      el.innerText = `${{delta >= 0 ? '+' : ''}}${{delta.toFixed(1)}}%`;
      el.parentElement.style.color = delta >= 0 ? 'var(--green)' : 'var(--red)';
      const subEl = document.getElementById(`kpi-${{cid.toLowerCase()}}-sub`);
      if (subEl) subEl.innerText = `Baseline: ${{stats[cid].b_cnt}} skills → Improved: ${{stats[cid].i_cnt}} skills`;
    }}
  }});

  const noiseDelta = noiseStats.b_cnt > 0 ? (((noiseStats.i_cnt - noiseStats.b_cnt) / noiseStats.b_cnt) * 100) : 0;
  const noiseEl = document.getElementById('kpi-noise-val');
  if (noiseEl) {{
    noiseEl.innerText = `${{noiseDelta >= 0 ? '+' : ''}}${{noiseDelta.toFixed(1)}}%`;
    noiseEl.parentElement.style.color = noiseDelta <= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('kpi-noise-sub').innerText = `Baseline: ${{noiseStats.b_cnt}} artifacts → Improved: ${{noiseStats.i_cnt}} artifacts`;
  }}
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
  let lessCount = 0, moreCount = 0, otherCount = 0;
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
      const table = row.closest('table');
      if (table) {{
        const tid = table.id;
        if (tid === 'table-less') lessCount++;
        else if (tid === 'table-more') moreCount++;
        else if (tid === 'table-other') otherCount++;
      }}
    }} else {{
      row.style.display = 'none';
    }}
  }});
  const lessEl = document.getElementById('count-less');
  const moreEl = document.getElementById('count-more');
  const otherEl = document.getElementById('count-other');
  if (lessEl) lessEl.innerText = lessCount;
  if (moreEl) moreEl.innerText = moreCount;
  if (otherEl) otherEl.innerText = otherCount;
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
    import argparse
    parser = argparse.ArgumentParser(
        description="ATS Resume Comparison Dashboard — compare two resumes via Affinda + Gemini",
        epilog="Examples:\n"
               "  python3 generate_report.py --baseline 1AqF9... --improved 1TshO...\n"
               "  python3 generate_report.py --baseline-file base.pdf --improved-file new.pdf\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--baseline", metavar="DOC_ID", help="Google Doc/Drive ID for the baseline resume")
    parser.add_argument("--improved", metavar="DOC_ID", help="Google Doc/Drive ID for the improved resume")
    parser.add_argument("--baseline-file", metavar="PATH", help="Local PDF path for the baseline resume")
    parser.add_argument("--improved-file", metavar="PATH", help="Local PDF path for the improved resume")
    parser.add_argument("-o", "--output", metavar="PATH", default=str(PROJECT_ROOT / "ats_comparison.html"),
                        help="Output HTML path (default: ats_comparison.html)")
    args = parser.parse_args()

    # Resolve inputs: CLI args override hardcoded defaults
    docs = {
        "baseline": {"name": "Baseline Resume", "filename": "baseline_resume.pdf"},
        "improved": {"name": "Improved Resume", "filename": "improved_resume.pdf"},
    }

    print("🚀 FETCHING RESUMES & CHECKING AFFINDA HASH CACHE...")
    results = {}

    for key, label_flag, file_flag, default_id in [
        ("baseline", args.baseline, args.baseline_file, DOCS["baseline"]["id"]),
        ("improved", args.improved, args.improved_file, DOCS["improved"]["id"]),
    ]:
        info = docs[key]
        print(f"📥 Loading {info['name']}...")

        if file_flag:
            # Local PDF file
            with open(file_flag, "rb") as f:
                pdf_bytes = f.read()
            info["filename"] = Path(file_flag).name
            print(f"   📄 Loaded local file: {file_flag}")
        else:
            # Google Doc/Drive export
            doc_id = label_flag or default_id
            pdf_bytes = fetch_pdf_bytes(doc_id)

        results[key] = call_affinda_with_cache(pdf_bytes, info["filename"])

    generate_html_report(results["baseline"], results["improved"], args.output)

if __name__ == "__main__":
    main()

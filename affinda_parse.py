#!/usr/bin/env python3
"""
Affinda ATS Resume Comparison & Skill Benchmark
Pulls live PDFs of Baseline and Improved resumes from Google Docs,
uploads to Affinda Resume Parser (US1 Region), and prints exact ATS extracted fields.
"""

import urllib.request
import json
import uuid
import sys
import ssl

from config import AFFINDA_API_KEY as API_KEY

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

BASE_URL = "https://api.us1.affinda.com/v3"
COLLECTION_ID = "sVbXvfpU"

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

def upload_and_parse(pdf_bytes, filename):
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
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json"
    })
    
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode())

def parse_affinda_skills(doc_json):
    data = doc_json.get("data", {})
    skills_raw = data.get("skills", [])
    
    parsed_skills = []
    for s in skills_raw:
        if isinstance(s, dict):
            name = s.get("name")
            stype = s.get("type", "skill")
            months = s.get("numberOfMonths")
            parsed_skills.append({
                "name": name,
                "type": stype,
                "months": months
            })
        elif isinstance(s, str):
            parsed_skills.append({
                "name": s,
                "type": "skill",
                "months": None
            })
            
    work_exp = data.get("workExperience", [])
    roles = []
    for w in work_exp:
        job_title = w.get("jobTitle")
        org = w.get("organization")
        start = w.get("dates", {}).get("startDate") if isinstance(w.get("dates"), dict) else None
        end = w.get("dates", {}).get("endDate") if isinstance(w.get("dates"), dict) else None
        is_current = w.get("dates", {}).get("isCurrent") if isinstance(w.get("dates"), dict) else False
        roles.append({
            "title": job_title,
            "org": org,
            "start": start,
            "end": end,
            "is_current": is_current,
            "raw_text": w.get("jobDescription", "")[:100] if w.get("jobDescription") else ""
        })
        
    education = data.get("education", [])
    edu_list = []
    for e in education:
        deg = e.get("degree") or e.get("accreditation")
        org = e.get("organization")
        edu_list.append({"degree": deg, "org": org})
        
    certifications = data.get("certifications", [])
    
    total_experience_years = data.get("totalYearsExperience")
    profession = data.get("profession")
    
    return {
        "profession": profession,
        "totalYearsExperience": total_experience_years,
        "skills": parsed_skills,
        "roles": roles,
        "education": edu_list,
        "certifications": certifications,
        "raw": data
    }

def main():
    parsed = {}
    for key, info in DOCS.items():
        print(f"📥 Pulling & Parsing {info['name']} via Affinda API...")
        pdf_bytes = fetch_pdf_bytes(info["id"])
        resp = upload_and_parse(pdf_bytes, info["filename"])
        
        # Save raw JSON for reference
        with open(f"affinda_{key}.json", "w") as f:
            json.dump(resp, f, indent=2)
            
        parsed[key] = parse_affinda_skills(resp)
        print(f"   ✓ Extracted {len(parsed[key]['skills'])} skills, {len(parsed[key]['roles'])} roles, {len(parsed[key]['education'])} degrees\n")
        
    base = parsed["baseline"]
    imp = parsed["improved"]
    
    print("=" * 85)
    print("🏢 AFFINDA ATS PARSER: EXECUTIVE COMPARISON")
    print("=" * 85)
    print(f"{'Field':<30} | {'Baseline Resume':<24} | {'Improved Resume':<24}")
    print("-" * 85)
    print(f"{'Detected Profession':<30} | {str(base['profession']):<24} | {str(imp['profession']):<24}")
    print(f"{'Total Years of Experience':<30} | {str(base['totalYearsExperience']):<24} | {str(imp['totalYearsExperience']):<24}")
    print(f"{'Total Skills Parsed':<30} | {len(base['skills']):<24} | {len(imp['skills']):<24}")
    print(f"{'Work Roles Parsed':<30} | {len(base['roles']):<24} | {len(imp['roles']):<24}")
    print(f"{'Education Entries':<30} | {len(base['education']):<24} | {len(imp['education']):<24}")
    print(f"{'Certifications Parsed':<30} | {len(base['certifications']):<24} | {len(imp['certifications']):<24}")

    print("\n" + "=" * 85)
    print("💼 WORK EXPERIENCE ROLES PARSED BY AFFINDA")
    print("=" * 85)
    print("BASELINE ROLES:")
    for r in base["roles"]:
        print(f"  • {r['title']} @ {r['org']} ({r['start']} to {r['end']})")
    print("\nIMPROVED ROLES:")
    for r in imp["roles"]:
        print(f"  • {r['title']} @ {r['org']} ({r['start']} to {r['end']})")

    # Skills comparison
    base_skills = {s["name"]: s for s in base["skills"] if s["name"]}
    imp_skills = {s["name"]: s for s in imp["skills"] if s["name"]}
    
    all_skill_names = sorted(list(set(base_skills.keys()).union(set(imp_skills.keys()))))
    
    print("\n" + "=" * 85)
    print("🧠 AFFINDA DETECTED SKILLS MATRIX (RAW ATS EXTRACTED SKILLS)")
    print("=" * 85)
    print(f"{'Skill / Entity':<35} | {'Baseline':<18} | {'Improved':<18} | {'Status':<12}")
    print("-" * 85)
    
    for s_name in all_skill_names:
        in_b = s_name in base_skills
        in_i = s_name in imp_skills
        
        b_mon = f"{base_skills[s_name]['months']} mos" if in_b and base_skills[s_name]['months'] else ("Yes" if in_b else "No")
        i_mon = f"{imp_skills[s_name]['months']} mos" if in_i and imp_skills[s_name]['months'] else ("Yes" if in_i else "No")
        
        if in_b and not in_i:
            status = "❌ LOST"
        elif not in_b and in_i:
            status = "⭐ GAINED"
        else:
            status = "= KEPT"
            
        print(f"{s_name:<35} | {b_mon:<18} | {i_mon:<18} | {status:<12}")

if __name__ == "__main__":
    main()

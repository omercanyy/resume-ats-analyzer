import urllib.request
import json
import os
import ssl
from pathlib import Path

from config import GEMINI_API_KEY, PROJECT_ROOT

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

TAXONOMY_FILE = PROJECT_ROOT / "sdet_skill_taxonomy.json"

def load_taxonomy():
    if TAXONOMY_FILE.exists():
        with open(TAXONOMY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_taxonomy(taxonomy):
    with open(TAXONOMY_FILE, "w") as f:
        json.dump(taxonomy, f, indent=2)

def classify_skills_with_gemini(skill_names):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file or environment.")
        
    taxonomy = load_taxonomy()
    unclassified = [s for s in skill_names if s not in taxonomy]
    
    if not unclassified:
        print(f"⚡ All {len(skill_names)} skills already classified in taxonomy cache.")
        return taxonomy
        
    print(f"🤖 Classifying {len(unclassified)} new skills via Gemini 3.6 Flash...")
    
    prompt = f"""You are an expert ATS & Technical Recruiting Classifier for Software Development Engineer in Test (SDET) and Backend Software Engineering roles.

Classify each of the following raw skill strings extracted by an ATS resume parser into EXACTLY ONE of these four categories:
1. "HARD_TECH": Specific programming languages, tools, frameworks, databases, cloud infra, CI/CD, test libraries (e.g., Java, Spring Boot, Playwright, Selenium, Kubernetes, REST Assured, Git, PostgreSQL, Docker, AI Agents, JUnit 5, Apache POI, Splunk).
2. "QA_METHODOLOGY": Industry testing practices, test architecture concepts, and testing types (e.g., BDD, TDD, Root Cause Analysis, Smoke Testing, Performance Testing, Data-Driven Testing, Load Testing, Regression Testing, Framework Design, Test Strategy, Object Model).
3. "PROCESS_LEADERSHIP": Team leadership, engineering processes, Agile/Scrum events, security operations (e.g., Technical Leadership, Incident Management, Agile Software Development, Scrum, Vulnerability Management, Mentoring, Human-in-the-loop, Triage, Auditing, Hardening, Sprint Planning).
4. "PARSER_NOISE": Generic resume filler words, non-technical English nouns/verbs, vague phrases, or obvious parser hallucinations (e.g., Source (Game Engine), FourGen Computer-Aided Software Engineering (CASE) Tools, Adoptions, Execution Time, Maintainability, Failure Analysis, Investigation, Table Setting, Collaboration, Social Media, Website Management, Reliability, Test Case, Test Planning, UI Components).

Skills to classify:
{json.dumps(unclassified, indent=2)}

Return ONLY a valid JSON object with the skill names as keys:
{{
  "skill_name": {{
    "category": "HARD_TECH" | "QA_METHODOLOGY" | "PROCESS_LEADERSHIP" | "PARSER_NOISE",
    "reason": "1 short phrase explanation"
  }}
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        res_data = json.loads(resp.read().decode('utf-8'))
        text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
        new_classifications = json.loads(text_content)
        
    for k, v in new_classifications.items():
        taxonomy[k] = v
        
    save_taxonomy(taxonomy)
    print(f"💾 Saved updated taxonomy to {TAXONOMY_FILE} ({len(taxonomy)} total skills)")
    return taxonomy

if __name__ == "__main__":
    with open("affinda_baseline.json") as f:
        b = json.load(f)["data"]["skills"]
    with open("affinda_improved.json") as f:
        i = json.load(f)["data"]["skills"]
        
    all_names = sorted(list(set([s["name"] for s in b + i if s.get("name")])))
    tax = classify_skills_with_gemini(all_names)
    
    noise_count = sum(1 for v in tax.values() if v.get("category") == "PARSER_NOISE")
    hard_count = sum(1 for v in tax.values() if v.get("category") == "HARD_TECH")
    qa_count = sum(1 for v in tax.values() if v.get("category") == "QA_METHODOLOGY")
    proc_count = sum(1 for v in tax.values() if v.get("category") == "PROCESS_LEADERSHIP")
    
    print("\n=== CLASSIFICATION BREAKDOWN ===")
    print(f"  • HARD_TECH:          {hard_count} skills")
    print(f"  • QA_METHODOLOGY:     {qa_count} skills")
    print(f"  • PROCESS_LEADERSHIP: {proc_count} skills")
    print(f"  • PARSER_NOISE:       {noise_count} skills (will be filtered)")

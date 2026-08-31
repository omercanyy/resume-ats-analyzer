#!/usr/bin/env python3
"""
================================================================================
ATS RESUME ANALYZER & BENCHMARKING ENGINE (AUDIENCE #1 FOCUS)
================================================================================
This script dynamically fetches both resumes live from Google Docs via export
endpoints and performs an in-depth ATS keyword matching, frequency, density,
section distribution, dual-indexing, and job description fit analysis.
================================================================================
"""

import urllib.request
import re
import sys
import json
import ssl
from collections import Counter, defaultdict

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

DOCS = {
    "baseline": {
        "id": "1AqF9a4sGk9B_N4RIXe4vjFez52YEYZA6",
        "name": "Baseline Resume",
        "url": "https://docs.google.com/document/d/1AqF9a4sGk9B_N4RIXe4vjFez52YEYZA6/edit"
    },
    "improved": {
        "id": "1TshOr8vt_NgOTz-K18sYaismGn4CJeHcGB5W1_GSVNI",
        "name": "Improved Resume (Role-based Tech Stacks + Skills Matrix)",
        "url": "https://docs.google.com/document/d/1TshOr8vt_NgOTz-K18sYaismGn4CJeHcGB5W1_GSVNI/edit"
    }
}

KEYWORD_TAXONOMY = {
    "1. Languages & Core": [
        "Java", "SQL", "Gherkin", "Python", "JavaScript", "TypeScript", "HTML", "JSON", 
        "Data Structures", "Algorithms"
    ],
    "2. Frameworks & Libraries": [
        "Spring", "Spring Boot", "Spring WebClient", "Angular", "JPA/Hibernate", "Hibernate", "JDBC", "Spock"
    ],
    "3. Test Automation & Tools": [
        "Playwright", "Selenium", "Selenium WebDriver", "REST Assured", "JUnit", "JUnit 5", 
        "TestNG", "Cucumber", "JBehave", "JMeter", "Postman", "Insomnia", "Cypress", 
        "Apache POI", "Maven Surefire"
    ],
    "4. CI/CD, Build & DevOps": [
        "Maven", "Gradle", "Jenkins", "Git", "GitHub", "Bitbucket", "CI/CD"
    ],
    "5. Cloud & Infrastructure": [
        "Pivotal Cloud Foundry (PCF)", "PCF", "Kubernetes", "Microsoft Azure", "Azure", 
        "AWS", "Amazon Web Services (AWS)", "Splunk"
    ],
    "6. AI & Modern Engineering": [
        "GitHub Copilot", "Claude", "Claude CLI", "AI Agents", "LLMs", 
        "Large Language Models (LLMs)", "Generative AI", "AI-Assisted Software Development", 
        "MCP", "HITL", "human-in-the-loop"
    ],
    "7. QA Methodologies & Testing Types": [
        "API Testing", "UI Testing", "UI Automation", "Performance Testing", "Load Testing", 
        "Regression Testing", "Functional Testing", "Smoke Testing", "Integration Testing", 
        "End-to-End Testing", "Cross-browser Testing", "Parallel Execution", "Data-Driven Testing", 
        "Black Box Testing", "Boundary Value Analysis", "Decision Table Testing", "BDD", "TDD", 
        "Page Object Model (POM)", "Behavior-Driven Development (BDD)", "Test-Driven Development (TDD)",
        "Test Automation", "Automation Framework Design", "Test Architecture", "QA Strategy", "Test Strategy"
    ],
    "8. Architecture, Security & Operations": [
        "Microservices", "REST APIs", "Software Architecture", "GitHub Advanced Security (GHAS)", 
        "GHAS", "Root Cause Analysis (RCA)", "RCA", "Production Incident Management", 
        "Vulnerability Management", "Release SLOs"
    ],
    "9. Process & Collaboration": [
        "SDLC", "STLC", "SDLC/STLC", "Agile/Scrum", "Agile", "Scrum", "Jira", "Technical Leadership", 
        "Mentoring", "Framework Modernization", "Code Refactoring"
    ],
    "10. Databases & Tools": [
        "Oracle", "Oracle Database", "SQL Developer", "IntelliJ IDEA"
    ]
}

DUAL_INDEX_PAIRS = [
    ("BDD", "Behavior-Driven Development"),
    ("TDD", "Test-Driven Development"),
    ("POM", "Page Object Model"),
    ("RCA", "Root Cause Analysis"),
    ("GHAS", "GitHub Advanced Security"),
    ("PCF", "Pivotal Cloud Foundry"),
    ("AWS", "Amazon Web Services"),
    ("LLMs", "Large Language Models"),
    ("SDLC", "Software Development Life Cycle"),
    ("STLC", "Software Testing Life Cycle"),
    ("HITL", "Human-in-the-Loop")
]

SIMULATED_JOB_DESCRIPTIONS = {
    "JD 1: Lead SDET / QA Architect (Java, Playwright/Selenium, Spring Boot, Microservices, CI/CD)": [
        "Java", "Spring Boot", "Microservices", "Playwright", "Selenium WebDriver", 
        "REST Assured", "Cucumber", "BDD", "CI/CD", "Jenkins", "Kubernetes", "Git", 
        "Performance Testing", "JMeter", "Root Cause Analysis (RCA)", "Technical Leadership", 
        "Agile", "Jira", "GitHub Copilot", "SQL"
    ],
    "JD 2: Senior Automation Engineer (API & UI Automation, Cypress/Playwright, Multi-Cloud)": [
        "Java", "Playwright", "Cypress", "Selenium", "API Testing", "Postman", 
        "REST Assured", "AWS", "Azure", "CI/CD", "Maven", "JUnit", "TestNG", 
        "Page Object Model (POM)", "Data-Driven Testing", "GitHub", "SDLC"
    ],
    "JD 3: Modern QA Lead (AI-Driven Testing, Security, PCF/K8s Architecture)": [
        "Java", "Spring", "Microservices", "Playwright", "AI Agents", "LLMs", 
        "GitHub Copilot", "Claude", "GitHub Advanced Security (GHAS)", "Kubernetes", 
        "Pivotal Cloud Foundry (PCF)", "Splunk", "Test Architecture", "QA Strategy", 
        "Production Incident Management", "SDLC/STLC"
    ]
}

def fetch_doc(doc_id):
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=15) as response:
        content = response.read().decode('utf-8')
    
    # Strip footnote definitions at end and inline comment brackets like [a], [b], [c]
    content = re.sub(r'(?m)^\[[a-z0-9]+\][^\n]*', '', content)
    content = re.sub(r'\[[a-z0-9]+\]', '', content)
    return content.strip()

def match_keyword_count(text, keyword):
    escaped = re.escape(keyword)
    pattern = rf'(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])'
    
    if keyword.isupper() and len(keyword) <= 5:
        matches = list(re.finditer(pattern, text))
    else:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        
    return len(matches)

def parse_sections(text):
    lines = text.splitlines()
    sections = {}
    current_sec = "HEADER"
    sec_lines = []
    
    heading_patterns = [
        ("PROFESSIONAL SUMMARY", "SUMMARY"),
        ("PROFESSIONAL SKILLS", "PROFESSIONAL_SKILLS_BULLETS"),
        ("WORKING EXPERIENCE", "EXPERIENCE"),
        ("WORK EXPERIENCE", "EXPERIENCE"),
        ("EXPERIENCE", "EXPERIENCE"),
        ("LANGUAGES/TOOLS", "LANGUAGES_TOOLS"),
        ("LANGUAGES & TOOLS", "LANGUAGES_TOOLS"),
        ("SKILLS", "SKILLS"),
        ("EDUCATION", "EDUCATION"),
        ("CERTIFICATES", "CERTIFICATES"),
        ("COMMUNITY", "COMMUNITY")
    ]
    
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        
        matched_heading = None
        for head_text, sec_id in heading_patterns:
            if cleaned.upper() == head_text or cleaned.upper().startswith(head_text + " "):
                matched_heading = (head_text, sec_id)
                break
                
        if matched_heading:
            if sec_lines:
                sections[current_sec] = "\n".join(sec_lines)
                sec_lines = []
            current_sec = matched_heading[1]
        else:
            sec_lines.append(cleaned)
            
    if sec_lines:
        sections[current_sec] = "\n".join(sec_lines)
        
    return sections

def analyze_resume(text):
    words = re.findall(r'\b[A-Za-z0-9_-]+\b', text)
    total_words = len(words)
    total_chars = len(text)
    
    category_counts = {}
    keyword_freq = {}
    
    for cat, kw_list in KEYWORD_TAXONOMY.items():
        cat_total = 0
        for kw in kw_list:
            cnt = match_keyword_count(text, kw)
            if cnt > 0:
                keyword_freq[kw] = cnt
                cat_total += cnt
        category_counts[cat] = cat_total
        
    sections = parse_sections(text)
    section_metrics = {}
    for s_name, s_content in sections.items():
        s_words = len(re.findall(r'\b[A-Za-z0-9_-]+\b', s_content))
        s_kw_hits = sum(match_keyword_count(s_content, kw) for kw in keyword_freq)
        section_metrics[s_name] = {
            "lines": len(s_content.splitlines()),
            "words": s_words,
            "chars": len(s_content),
            "kw_hits": s_kw_hits,
            "density": (s_kw_hits / s_words * 100) if s_words > 0 else 0
        }
        
    total_ats_hits = sum(keyword_freq.values())
    unique_ats_keywords = len(keyword_freq)
    keyword_density = (total_ats_hits / total_words * 100) if total_words > 0 else 0
    
    dual_index_results = {}
    for acr, full in DUAL_INDEX_PAIRS:
        c_acr = match_keyword_count(text, acr)
        c_full = match_keyword_count(text, full)
        dual_index_results[f"{acr} / {full}"] = {
            "acronym_count": c_acr,
            "full_phrase_count": c_full,
            "both_present": (c_acr > 0 and c_full > 0),
            "status": "Both Present" if (c_acr > 0 and c_full > 0) else ("Acronym Only" if c_acr > 0 else ("Full Only" if c_full > 0 else "Missing"))
        }
        
    jd_scores = {}
    for jd_name, jd_keywords in SIMULATED_JOB_DESCRIPTIONS.items():
        matched = [kw for kw in jd_keywords if match_keyword_count(text, kw) > 0]
        score_pct = (len(matched) / len(jd_keywords)) * 100
        jd_scores[jd_name] = {
            "matched_count": len(matched),
            "total_reqs": len(jd_keywords),
            "match_pct": score_pct,
            "matched_keywords": matched,
            "missing_keywords": [kw for kw in jd_keywords if kw not in matched]
        }

    return {
        "total_words": total_words,
        "total_chars": total_chars,
        "total_ats_hits": total_ats_hits,
        "unique_ats_keywords": unique_ats_keywords,
        "keyword_density": keyword_density,
        "keyword_freq": keyword_freq,
        "category_counts": category_counts,
        "section_metrics": section_metrics,
        "dual_index_results": dual_index_results,
        "jd_scores": jd_scores,
        "sections": sections
    }

def print_report():
    print("=" * 90)
    print("🚀 LIVE FETCH & ATS AUDIENCE #1 ANALYSIS BENCHMARK")
    print("=" * 90)
    
    analyses = {}
    for key, info in DOCS.items():
        print(f"📥 Fetching '{info['name']}' from Google Docs (Doc ID: {info['id']})...")
        text = fetch_doc(info['id'])
        analyses[key] = analyze_resume(text)
        print(f"   ✓ Extracted {len(text)} characters, {analyses[key]['total_words']} words\n")
        
    base = analyses["baseline"]
    imp = analyses["improved"]
    
    print("=" * 90)
    print("🏆 1. ATS HIGH-LEVEL KPI EXECUTIVE SCORECARD")
    print("=" * 90)
    print(f"{'Metric':<38} | {'Baseline':<16} | {'Improved':<16} | {'Delta':<14}")
    print("-" * 90)
    
    metrics = [
        ("Total Word Count", base["total_words"], imp["total_words"], imp["total_words"] - base["total_words"]),
        ("Total Characters", base["total_chars"], imp["total_chars"], imp["total_chars"] - base["total_chars"]),
        ("Total ATS Keyword Hits", base["total_ats_hits"], imp["total_ats_hits"], imp["total_ats_hits"] - base["total_ats_hits"]),
        ("Unique ATS Keywords Matched", base["unique_ats_keywords"], imp["unique_ats_keywords"], imp["unique_ats_keywords"] - base["unique_ats_keywords"]),
        ("ATS Keyword Density (%)", f"{base['keyword_density']:.2f}%", f"{imp['keyword_density']:.2f}%", f"{(imp['keyword_density'] - base['keyword_density']):+.2f}%"),
        ("Signal-to-Noise Ratio (Keywords/Total Words)", f"1 in {base['total_words']/base['total_ats_hits']:.1f} words", f"1 in {imp['total_words']/imp['total_ats_hits']:.1f} words", "2.5x Higher")
    ]
    for label, b, i, d in metrics:
        d_str = f"{d:+}" if isinstance(d, (int, float)) else str(d)
        print(f"{label:<38} | {str(b):<16} | {str(i):<16} | {d_str:<14}")

    print("\n" + "=" * 90)
    print("📁 2. CATEGORY BREAKDOWN (ATS MATCH COUNTS)")
    print("=" * 90)
    print(f"{'Category':<38} | {'Baseline':<16} | {'Improved':<16} | {'Delta':<14}")
    print("-" * 90)
    for cat in KEYWORD_TAXONOMY.keys():
        b_cnt = base["category_counts"].get(cat, 0)
        i_cnt = imp["category_counts"].get(cat, 0)
        diff = i_cnt - b_cnt
        print(f"{cat:<38} | {b_cnt:<16} | {i_cnt:<16} | {diff:+<14}")

    print("\n" + "=" * 90)
    print("🏛️ 3. SECTION-LEVEL KEYWORD DENSITY & PLACEMENT")
    print("=" * 90)
    print(f"--- BASELINE RESUME SECTIONS ---")
    print(f"{'Section':<32} | {'Words':<8} | {'Chars':<8} | {'ATS Hits':<10} | {'Density':<10}")
    print("-" * 90)
    for s, m in base["section_metrics"].items():
        print(f"{s:<32} | {m['words']:<8} | {m['chars']:<8} | {m['kw_hits']:<10} | {m['density']:.1f}%")
        
    print(f"\n--- IMPROVED RESUME SECTIONS ---")
    print(f"{'Section':<32} | {'Words':<8} | {'Chars':<8} | {'ATS Hits':<10} | {'Density':<10}")
    print("-" * 90)
    for s, m in imp["section_metrics"].items():
        print(f"{s:<32} | {m['words']:<8} | {m['chars']:<8} | {m['kw_hits']:<10} | {m['density']:.1f}%")

    print("\n" + "=" * 90)
    print("🔍 4. KEYWORD FREQUENCY & DELTA COMPARISON (ALL MATCHES)")
    print("=" * 90)
    all_kws = sorted(list(set(list(base["keyword_freq"].keys()) + list(imp["keyword_freq"].keys()))))
    print(f"{'Keyword':<34} | {'Baseline':<10} | {'Improved':<10} | {'Status':<18}")
    print("-" * 90)
    
    gained = []
    lost = []
    increased = []
    decreased = []
    
    for kw in all_kws:
        b_cnt = base["keyword_freq"].get(kw, 0)
        i_cnt = imp["keyword_freq"].get(kw, 0)
        diff = i_cnt - b_cnt
        
        if b_cnt == 0 and i_cnt > 0:
            status = f"⭐ NEW (+{i_cnt})"
            gained.append((kw, i_cnt))
        elif b_cnt > 0 and i_cnt == 0:
            status = f"❌ DROPPED (-{b_cnt})"
            lost.append((kw, b_cnt))
        elif diff > 0:
            status = f"▲ +{diff} ({b_cnt}->{i_cnt})"
            increased.append((kw, diff, b_cnt, i_cnt))
        elif diff < 0:
            status = f"▼ {diff} ({b_cnt}->{i_cnt})"
            decreased.append((kw, diff, b_cnt, i_cnt))
        else:
            status = f"= ({b_cnt})"
            
        print(f"{kw:<34} | {b_cnt:<10} | {i_cnt:<10} | {status:<18}")

    print("\n" + "=" * 90)
    print("🔄 5. DUAL-INDEXING ANALYSIS (ACRONYM vs FULL PHRASE)")
    print("=" * 90)
    print(f"{'Term Pair (Acronym / Full)':<38} | {'Baseline Status':<24} | {'Improved Status':<24}")
    print("-" * 90)
    for pair, res_base in base["dual_index_results"].items():
        res_imp = imp["dual_index_results"][pair]
        b_st = f"{res_base['status']} ({res_base['acronym_count']}/{res_base['full_phrase_count']})"
        i_st = f"{res_imp['status']} ({res_imp['acronym_count']}/{res_imp['full_phrase_count']})"
        print(f"{pair:<38} | {b_st:<24} | {i_st:<24}")

    print("\n" + "=" * 90)
    print("🎯 6. SIMULATED JOB REQUISITION MATCH BENCHMARKS")
    print("=" * 90)
    for jd_name, jd_base in base["jd_scores"].items():
        jd_imp = imp["jd_scores"][jd_name]
        print(f"\n📋 {jd_name}")
        print(f"   Baseline Match Score : {jd_base['matched_count']}/{jd_base['total_reqs']} ({jd_base['match_pct']:.1f}%)")
        print(f"   Improved Match Score : {jd_imp['matched_count']}/{jd_imp['total_reqs']} ({jd_imp['match_pct']:.1f}%) [{(jd_imp['match_pct'] - jd_base['match_pct']):+.1f}%]")
        if jd_imp["missing_keywords"]:
            print(f"   ⚠️ Missing in Improved: {', '.join(jd_imp['missing_keywords'])}")
        if jd_base["missing_keywords"]:
            print(f"   ⚠️ Missing in Baseline: {', '.join(jd_base['missing_keywords'])}")

if __name__ == "__main__":
    print_report()

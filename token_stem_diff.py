#!/usr/bin/env python3
"""
Simple Token & Stem Frequency Differential Analyzer
Tokenizes both resumes, removes stopwords, applies Porter stemming,
and highlights words that decreased or dropped to 0 in the Improved version.
"""

import urllib.request
import re
import ssl
from collections import Counter, defaultdict

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl._create_unverified_context()

DOCS = {
    "baseline": "1AqF9a4sGk9B_N4RIXe4vjFez52YEYZA6",
    "improved": "1TshOr8vt_NgOTz-K18sYaismGn4CJeHcGB5W1_GSVNI"
}

# Standard English stopwords
STOPWORDS = set([
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'as', 'at',
    'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'could', 'did',
    'do', 'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have',
    'having', 'he', 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', 'if', 'in',
    'into', 'is', 'it', 'its', 'itself', 'just', 'me', 'more', 'most', 'my', 'myself', 'no', 'nor', 'not',
    'of', 'off', 'on', 'once', 'only', 'or', 'other', 'ought', 'our', 'ours', 'ourselves', 'out', 'over',
    'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their', 'theirs', 'them',
    'themselves', 'then', 'there', 'these', 'they', 'this', 'those', 'through', 'to', 'too', 'under',
    'until', 'up', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'while', 'who', 'whom',
    'why', 'with', 'would', 'you', 'your', 'yours', 'yourself', 'yourselves', 'across', 'including', 'using',
    'per', 'via', 'etc', 'also', 'well', 'within', 'throughout'
])

def fetch_doc(doc_id):
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as response:
        content = response.read().decode('utf-8')
    # Strip footnote definitions and inline comment tags like [a], [b]
    content = re.sub(r'(?m)^\[[a-z0-9]+\][^\n]*', '', content)
    content = re.sub(r'\[[a-z0-9]+\]', '', content)
    return content.strip()

class SimplePorterStemmer:
    """Lightweight Porter Stemmer implementation for standard English word stemming."""
    def is_consonant(self, word, i):
        letter = word[i]
        if letter in 'aeiou':
            return False
        if letter == 'y':
            if i == 0:
                return True
            return not self.is_consonant(word, i - 1)
        return True

    def measure(self, stem):
        m = 0
        i = 0
        length = len(stem)
        while i < length:
            while i < length and not self.is_consonant(stem, i):
                i += 1
            if i >= length:
                break
            while i < length and self.is_consonant(stem, i):
                i += 1
            m += 1
        return m

    def contains_vowel(self, stem):
        return any(not self.is_consonant(stem, i) for i in range(len(stem)))

    def ends_double_consonant(self, word):
        if len(word) >= 2 and word[-1] == word[-2] and self.is_consonant(word, len(word) - 1):
            return True
        return False

    def stem(self, word):
        word = word.lower()
        if len(word) <= 2:
            return word

        # Step 1a: Plurals and -ed / -ing
        if word.endswith('sses'):
            word = word[:-2]
        elif word.endswith('ies'):
            word = word[:-2]
        elif not word.endswith('ss') and word.endswith('s'):
            word = word[:-1]

        # Step 1b: -ed, -ing
        if word.endswith('eed'):
            if self.measure(word[:-3]) > 0:
                word = word[:-1]
        elif word.endswith('ed'):
            stem = word[:-2]
            if self.contains_vowel(stem):
                word = stem
                if word.endswith('at') or word.endswith('bl') or word.endswith('iz'):
                    word += 'e'
                elif self.ends_double_consonant(word) and not word.endswith(('l', 's', 'z')):
                    word = word[:-1]
        elif word.endswith('ing'):
            stem = word[:-3]
            if self.contains_vowel(stem):
                word = stem
                if word.endswith('at') or word.endswith('bl') or word.endswith('iz'):
                    word += 'e'
                elif self.ends_double_consonant(word) and not word.endswith(('l', 's', 'z')):
                    word = word[:-1]

        # Step 1c: y -> i
        if word.endswith('y') and self.contains_vowel(word[:-1]):
            word = word[:-1] + 'i'

        # Step 2 & 4: Common suffixes
        suffixes = [
            ('ational', 'ate'), ('tional', 'tion'), ('enci', 'ence'), ('anci', 'ance'),
            ('izer', 'ize'), ('abli', 'able'), ('alli', 'al'), ('entli', 'ent'),
            ('eli', 'e'), ('ousli', 'ous'), ('ization', 'ize'), ('ation', 'ate'),
            ('ator', 'ate'), ('alism', 'al'), ('iveness', 'ive'), ('fulness', 'ful'),
            ('ousness', 'ous'), ('aliti', 'al'), ('iviti', 'ive'), ('biliti', 'ble'),
            ('icate', 'ic'), ('ative', ''), ('alize', 'al'), ('iciti', 'ic'),
            ('ical', 'ic'), ('ful', ''), ('ness', ''), ('able', ''), ('ible', ''),
            ('ant', ''), ('ement', ''), ('ment', ''), ('ent', ''), ('ism', ''),
            ('ate', ''), ('iti', ''), ('ous', ''), ('ive', ''), ('ize', '')
        ]
        for suf, repl in suffixes:
            if word.endswith(suf):
                stem = word[:-len(suf)]
                if self.measure(stem) > 1:
                    word = stem + repl
                break

        return word

def process_text(text):
    stemmer = SimplePorterStemmer()
    # Simple regex tokenization: words with letters only
    tokens = re.findall(r'[a-zA-Z]+', text.lower())
    
    stem_counts = Counter()
    stem_to_examples = defaultdict(Counter)
    
    for t in tokens:
        if t in STOPWORDS or len(t) <= 1:
            continue
        stemmed = stemmer.stem(t)
        stem_counts[stemmed] += 1
        stem_to_examples[stemmed][t] += 1
        
    return stem_counts, stem_to_examples, len(tokens)

def main():
    print("📥 Pulling Google Docs live...")
    base_text = fetch_doc(DOCS["baseline"])
    imp_text = fetch_doc(DOCS["improved"])
    
    base_stems, base_examples, base_total_tokens = process_text(base_text)
    imp_stems, imp_examples, imp_total_tokens = process_text(imp_text)
    
    all_stems = sorted(list(set(base_stems.keys()).union(set(imp_stems.keys()))))
    
    dropped_to_zero = []
    decreased = []
    increased = []
    new_words = []
    
    for stem in all_stems:
        b_cnt = base_stems.get(stem, 0)
        i_cnt = imp_stems.get(stem, 0)
        diff = i_cnt - b_cnt
        
        # Pick the most representative surface word
        surface_counts = Counter()
        for s, c in base_examples[stem].items():
            surface_counts[s] += c
        for s, c in imp_examples[stem].items():
            surface_counts[s] += c
        rep_word = surface_counts.most_common(1)[0][0] if surface_counts else stem
        
        if b_cnt > 0 and i_cnt == 0:
            dropped_to_zero.append((rep_word, stem, b_cnt, i_cnt, diff))
        elif diff < 0:
            decreased.append((rep_word, stem, b_cnt, i_cnt, diff))
        elif b_cnt == 0 and i_cnt > 0:
            new_words.append((rep_word, stem, b_cnt, i_cnt, diff))
        elif diff > 0:
            increased.append((rep_word, stem, b_cnt, i_cnt, diff))

    print("\n" + "=" * 80)
    print("🚨 WORDS/STEMS THAT DROPPED TO ZERO IN IMPROVED RESUME (COMPLETELY LOST)")
    print("=" * 80)
    print(f"{'Representative Word':<25} | {'Stem':<15} | {'Baseline Count':<16} | {'Improved Count':<16}")
    print("-" * 80)
    for rep, stem, b, i, d in sorted(dropped_to_zero, key=lambda x: -x[2]):
        print(f"{rep:<25} | {stem:<15} | {b:<16} | {i:<16}")

    print("\n" + "=" * 80)
    print("📉 WORDS/STEMS WITH DECREASED FREQUENCY IN IMPROVED RESUME")
    print("=" * 80)
    print(f"{'Representative Word':<25} | {'Stem':<15} | {'Baseline Count':<16} | {'Improved Count':<16} | {'Delta':<8}")
    print("-" * 80)
    for rep, stem, b, i, d in sorted(decreased, key=lambda x: x[4]):
        print(f"{rep:<25} | {stem:<15} | {b:<16} | {i:<16} | {d:<8}")

    print("\n" + "=" * 80)
    print("📈 TOP WORDS/STEMS THAT INCREASED SIGNIFICANTLY")
    print("=" * 80)
    print(f"{'Representative Word':<25} | {'Stem':<15} | {'Baseline Count':<16} | {'Improved Count':<16} | {'Delta':<8}")
    print("-" * 80)
    for rep, stem, b, i, d in sorted(increased + new_words, key=lambda x: -x[4])[:25]:
        status = "(NEW)" if b == 0 else ""
        print(f"{rep:<25} | {stem:<15} | {b:<16} | {i:<16} | {d:+<6} {status}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
extract_keywords.py - Scan all abstracts and extract candidate keyword phrases.

Outputs a CSV ranked by number of papers each phrase appears in,
for manual curation into a keyword tag list.

Usage:
    python3 extract_keywords.py
    python3 extract_keywords.py --min-count 3 --max-ngram 4 --output keywords.csv
"""

import re
import csv
import sys
import argparse
import unicodedata
from collections import defaultdict

import inflect
import pymysql
from config import DB_CONFIG

_inflect = inflect.engine()
_singular_cache: dict[str, str] = {}

# inflect gets these math-specific plurals wrong; override manually
MATH_SINGULAR_OVERRIDES = {
    'tableaux':   'tableau',
    'vertices':   'vertex',
    'matrices':   'matrix',
    'indices':    'index',
    'axes':       'axis',
    'bases':      'basis',
    'simplices':  'simplex',
    'radii':      'radius',
    'radius':     'radius',   # inflect mangles this to 'radiu'
    'rhombus':    'rhombus',  # inflect mangles this to 'rhombu'
    'locus':      'locus',    # inflect mangles this to 'locu'
    'foci':       'focus',
    'tori':       'torus',
    'lemmata':    'lemma',
    'automata':   'automaton',
    'criteria':   'criterion',
    'phenomena':  'phenomenon',
    'strata':     'stratum',
    # Words inflect mangles by treating as Latin/Greek plurals
    'axis':          'axis',          # inflect returns 'axi'
    'erdos':         'erdos',         # inflect returns 'erdo' (Latin -os rule)
    'calculus':      'calculus',      # inflect returns 'calculu'
    'class':         'class',         # inflect returns 'clas'
    'continuous':    'continuous',    # inflect returns 'continuou'
    'homogeneous':   'homogeneous',   # inflect returns 'homogeneou'
    'inhomogeneous': 'inhomogeneous', # inflect returns 'inhomogeneou'
    'mobius':        'mobius',        # inflect returns 'mobiu'
    'process':       'process',       # inflect returns 'proces'
    'thesis':        'thesis',        # inflect returns 'thesi'
}


def singularize(word: str) -> str:
    """Return the singular form of a word, with caching for performance."""
    if word not in _singular_cache:
        if word in MATH_SINGULAR_OVERRIDES:
            _singular_cache[word] = MATH_SINGULAR_OVERRIDES[word]
        elif word in STOPWORDS:
            # Don't singularize stopwords — inflect mangles function words
            # (e.g. this->thi, was->wa) producing forms that bypass the filter
            _singular_cache[word] = word
        else:
            result = _inflect.singular_noun(word)
            _singular_cache[word] = result if result else word
    return _singular_cache[word]


# Common English words and math paper boilerplate to ignore as standalone terms.
# Multi-word phrases are only filtered if they start/end with these.
STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'that',
    'this', 'these', 'those', 'it', 'its', 'we', 'our', 'their', 'they',
    'which', 'who', 'when', 'where', 'how', 'if', 'then', 'than',
    'not', 'no', 'so', 'also', 'always', 'both', 'each', 'all', 'some', 'any',
    'such', 'up', 'out', 'into', 'over', 'about', 'given', 'via',
    'show', 'shows', 'shown', 'prove', 'proves', 'proved', 'proven',
    'use', 'used', 'using', 'obtain', 'obtained', 'consider', 'considered',
    'give', 'gives', 'study', 'studies', 'studied', 'find', 'found',
    'introduce', 'present', 'paper', 'work', 'result', 'results',
    'following', 'thus', 'hence', 'therefore', 'let', 'note',
    'well', 'known', 'one', 'two', 'three', 'first', 'second', 'third',
    'many', 'several', 'various', 'certain', 'other', 'different',
    'more', 'less', 'most', 'least', 'further', 'moreover', 'however',
    'here', 'there', 'now', 'only', 'just', 'i', 'ii', 'iii', 'e', 'g',
    'new', 'natural', 'general', 'special', 'main', 'key', 'important',
    'corresponding', 'associated', 'related', 'defined', 'induced',
    # User-specified additional stopwords
    'above', 'added', 'adding', 'additionally', 'admit', 'admitting', 'acute', 'after', 'al', 'allow', 'allowing',
    'almost', 'analytic', 'analytical', 'another', 'answer', 'apart',
    'application', 'approach', 'appropriate', 'arbitrary', 'argument', 'arise',
    'asked', 'assigned', 'assignment', 'assume', 'assuming', 'based',
    'behavior', 'behaviour', 'behind', 'belief', 'belonging', 'below', 'between',
    'active', 'acting', 'alternately', 'adjacent',
    'bijective', 'call', 'called', 'calling', 'case', 'characterise', 'characterize', 'choose', 'chosen', 'classical',
    'clear', 'combination', 'combinatorial', 'combine', 'combining', 'common', 'compare', 'competition',
    'concerning', 'conjecture', 'conjectured', 'connecting', 'consideration', 'consisting',
    'construction', 'constructive', 'contain', 'containing', 'conventional', 'counting', 'current', 'declaring',
    'deep', 'denote', 'denoting', 'depend', 'depending', 'describe', 'describing',
    'determine', 'determined', 'determining', 'differ', 'direction', 'disjoint', 'draw',
    'computing', 'condition', 'constant', 'due', 'easier', 'easily', 'effective', 'efficient', 'efficiently',
    'enumerate', 'enumerating', 'equal', 'equinumerous', 'exploit',
    'eventually', 'expanding', 'explaining', 'explicit', 'extending',
    'et', 'every', 'exactly', 'example', 'excess', 'exhibit', 'exhibiting',
    'exist', 'exists', 'expression', 'extend', 'extension',
    'fairly', 'few', 'formalism', 'full', 'furthermore', 'gave',
    'generalization', 'generalize', 'generalized', 'generalizing',
    'generalise', 'generalised', 'generalising', 'generating', 'generic',
    'having', 'her', 'hidden', 'him', 'his', 'historic',
    'holding', 'holds', 'immediate', 'immediately', 'implicit', 'improve', 'improved', 'improving',
    'include', 'including', 'independent', 'independently', 'infinite', 'influence', 'initial', 'instance', 'interest', 'intermediate',
    'interesting', 'intuition', 'investigate', 'involving', 'large', 'largest', 'lead', 'leading', 'leads',
    'left', 'lemma', 'literature', 'london', 'lying', 'math', 'me', 'mentioned', 'method', 'much',
    'near', 'needed', 'newly', 'next', 'nice', 'nontrivial', 'observe', 'observing', 'occur',
    'often',
    'occurring', 'obvious', 'parameter', 'part', 'per', 'perhaps', 'possible', 'precisely',
    'preserving', 'pretty', 'previous', 'previously', 'probably', 'problem',
    'parameterise', 'parameterised', 'parameterize', 'parameterized', 'parameterizing',
    'parametrise', 'parametrised', 'parametrize', 'parametrized', 'parametrizing',
    'proc', 'procedure', 'produced', 'producing', 'proof', 'property', 'proportion', 'quite', 'quote', 'quoting',
    'rare', 'rather', 'realized', 'realizing', 'reasonable', 'recall', 'recalling', 'recent', 'recently',
    'relation', 'relative', 'relatively', 'remain', 'remaining', 'require', 'required', 'research', 'resp', 'respectively', 'restricted', 'right', 'robustly',
    'moderate', 'opposite',
    'prescribed',
    'same', 'satisfy', 'satisfied', 'satisfying', 'say', 'saying', 'seeming', 'seems', 'select', 'setting', 'since',
    'slow', 'small', 'so-called', 'solvable', 'specified', 'staller', 'stated', 'swap', 'systematic',
    'straightforward', 'structural', 'structure', 'subject', 'successively', 'sufficiently', 'suppose', 'supposing',
    'technique', 'technology', 'them', 'theoretic', 'thereof', 'thereby', 'thesis', 'triangle', 'trivial', 'typical',
    'under', 'underlying', 'unexpected', 'us', 'usual', 'variation', 'verifying',
    'way', 'what', 'whereas', 'whereby', 'while', 'whose', 'without', 'yield', 'yielding',
}


def strip_latex(text):
    """Remove LaTeX markup, keeping natural language words."""
    # Display math $$...$$
    text = re.sub(r'\$\$.*?\$\$', ' ', text, flags=re.DOTALL)
    # Inline math $...$
    text = re.sub(r'\$[^$]*?\$', ' ', text)
    # Accent commands: strip accent but keep base letter (e.g. \"{o}->o, \H{o}->o)
    # Handles names like Möbius (M\"{o}bius -> Mobius) and Erdős (Erd\H{o}s -> Erdos)
    text = re.sub(r'\\[Hcvkrudbt]\{([a-zA-Z])\}', r'\1', text)   # \H{o}, \c{s}, etc.
    text = re.sub(r'\\["\'\`\^~\.=]\{([a-zA-Z])\}', r'\1', text)  # \"{o}, \'{e}, etc.
    text = re.sub(r'\\["\'\`\^~\.=]([a-zA-Z])', r'\1', text)       # \"o, \'e, etc.
    # \command{...} — remove whole thing
    text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', ' ', text)
    # Bare \command tokens
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    # Remaining braces
    text = re.sub(r'[{}]', ' ', text)
    # Normalize Unicode accented letters to ASCII (e.g. Möbius -> Mobius, Erdős -> Erdos)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return text


def tokenize(text):
    """Lowercase, strip LaTeX, and split into alphabetic word tokens."""
    text = strip_latex(text)
    text = text.lower()
    # Keep alphabetic words and hyphenated compounds (e.g. "q-analog"), then singularize
    tokens = re.findall(r'[a-z]+(?:-[a-z]+)*', text)
    return [singularize(t) for t in tokens]


def extract_ngrams(tokens, max_n):
    """Yield all n-grams as strings for n in 1..max_n."""
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            yield ' '.join(tokens[i:i + n])


def is_useful(phrase):
    """Return True if the phrase is a plausible keyword candidate."""
    words = phrase.split()
    # Drop single-character tokens
    if any(len(w) <= 1 for w in words):
        return False
    # Drop any phrase containing a stopword anywhere
    if any(w in STOPWORDS for w in words):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Extract keyword candidates from paper titles and abstracts.'
    )
    parser.add_argument('--min-count', type=int, default=5,
                        help='Min papers a phrase must appear in (default: 5)')
    parser.add_argument('--max-ngram', type=int, default=4,
                        help='Max n-gram length in words (default: 4)')
    parser.add_argument('--output', default='keywords.csv',
                        help='Output CSV file (default: keywords.csv)')
    args = parser.parse_args()

    print("Connecting to database...")
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    print("Fetching papers...")
    cursor.execute("SELECT id, title, abstract FROM papers")
    papers = cursor.fetchall()
    cursor.close()
    conn.close()
    print(f"  {len(papers):,} papers loaded.")

    # Map phrase -> set of paper IDs (so each paper counts once per phrase)
    phrase_papers = defaultdict(set)

    print(f"Extracting n-grams (1–{args.max_ngram} words)...")
    for i, (paper_id, title, abstract) in enumerate(papers):
        if i % 10000 == 0:
            print(f"  {i:,} / {len(papers):,}...")
        text = (title or '') + ' ' + (abstract or '')
        tokens = tokenize(text)
        seen_in_this_paper = set()
        for phrase in extract_ngrams(tokens, args.max_ngram):
            if phrase not in seen_in_this_paper and is_useful(phrase):
                phrase_papers[phrase].add(paper_id)
                seen_in_this_paper.add(phrase)

    print(f"  {len(phrase_papers):,} unique phrases found.")

    # Filter by min count and sort descending
    filtered = [
        (phrase, len(ids))
        for phrase, ids in phrase_papers.items()
        if len(ids) >= args.min_count
    ]
    filtered.sort(key=lambda x: -x[1])

    print(f"  {len(filtered):,} phrases appear in >= {args.min_count} papers.")

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['phrase', 'paper_count', 'word_count'])
        writer.writerows([(phrase, count, len(phrase.split())) for phrase, count in filtered])

    print(f"Done! Written to: {args.output}")


if __name__ == '__main__':
    main()

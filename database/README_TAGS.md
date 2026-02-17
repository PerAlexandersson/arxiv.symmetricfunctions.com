# Tags and Full-Text Search

## Setting Up the Database

Tags and full-text search are built into the main schema. To set up a fresh database:

```bash
cd database
./reset_database.sh
```

This will create the database with all tables including tags and full-text search enabled.

## Tag Types

The system supports four tag types:

1. **`msc`** - Mathematics Subject Classification 2020 codes (e.g., `05A15`, `05E05`)
2. **`personal`** - Your custom tags (e.g., `interesting`, `read-later`, `symmetric-functions`)
3. **`arxiv`** - arXiv category tags (e.g., `math.CO`, `math.PR`)
4. **`other`** - Any other categorization

## Using Tags (Command Line)

The `tags_helper.py` script provides a CLI interface:

```bash
cd src

# Add a tag to a paper
python tags_helper.py add 2401.12345 "05A15" msc
python tags_helper.py add 2401.12345 "interesting" personal

# Remove a tag
python tags_helper.py remove 2401.12345 "interesting" personal

# List all tags for a paper
python tags_helper.py list 2401.12345

# Find all papers with a specific tag
python tags_helper.py search "05A15"

# List all available tags
python tags_helper.py tags
python tags_helper.py tags msc  # Filter by type

# Full-text search
python tags_helper.py fulltext "symmetric functions"
python tags_helper.py fulltext "+Schur +positivity -quantum"  # Boolean mode
```

## Using Tags in Python

```python
from tags_helper import add_tag_to_paper, get_paper_tags, search_by_tag, fulltext_search

# Add tags
add_tag_to_paper('2401.12345', '05E05', tag_type='msc')
add_tag_to_paper('2401.12345', 'must-read', tag_type='personal')

# Get all tags for a paper
tags = get_paper_tags('2401.12345')
for tag in tags:
    print(f"{tag['tag_type']}: {tag['name']}")

# Find papers by tag
papers = search_by_tag('05E05', tag_type='msc')
for paper in papers:
    print(f"{paper['arxiv_id']}: {paper['title']}")

# Full-text search
results = fulltext_search('symmetric functions Schur')
for result in results:
    print(f"[{result['relevance']:.2f}] {result['title']}")
```

## Using in Flask App (app.py)

To add tags functionality to your web interface, you can import the helper functions:

```python
from tags_helper import get_paper_tags, search_by_tag, fulltext_search

@app.route('/paper/<arxiv_id>')
def paper_detail(arxiv_id):
    # ... existing code ...
    paper['tags'] = get_paper_tags(arxiv_id)
    # ... render template ...

@app.route('/search')
def search():
    query = request.args.get('q', '')
    results = fulltext_search(query)
    return render_template('search_results.html', results=results)

@app.route('/tag/<tag_name>')
def papers_by_tag(tag_name):
    papers = search_by_tag(tag_name)
    return render_template('tag_results.html', tag=tag_name, papers=papers)
```

## Full-Text Search Syntax

The full-text search supports MySQL's boolean mode operators:

- `+word` - Must contain this word
- `-word` - Must NOT contain this word
- `"exact phrase"` - Exact phrase match
- `word1 word2` - Contains either word (OR)
- `+word1 +word2` - Must contain both words (AND)

Examples:
```sql
-- Natural language search (automatic relevance ranking)
SELECT * FROM papers
WHERE MATCH(title, abstract) AGAINST('symmetric functions');

-- Boolean search
SELECT * FROM papers
WHERE MATCH(title, abstract) AGAINST('+Schur +positivity -quantum' IN BOOLEAN MODE);
```

## Common MSC Codes (Pre-loaded)

The schema includes common combinatorics MSC 2020 codes:

- **05A05** - Permutations, words, matrices
- **05A15** - Exact enumeration problems, generating functions
- **05A17** - Combinatorial aspects of partitions of integers
- **05A30** - q-calculus and related topics
- **05E05** - Symmetric functions and generalizations
- **05E10** - Combinatorial aspects of representation theory

See [schema.sql](schema.sql) for the complete list.

## Future Enhancements

You can later add:
- Web UI for managing tags
- Tag autocomplete
- Tag hierarchies (using `parent_tag_id`)
- Tag clouds / popular tags
- Bulk tagging operations
- Auto-tagging based on keywords

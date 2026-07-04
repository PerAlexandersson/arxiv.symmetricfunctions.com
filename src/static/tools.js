async function generateBibtex(event) {
    event.preventDefault();

    const input = document.getElementById('input-field').value.trim();
    const resultContainer = document.getElementById('result-container');
    const errorMessage = document.getElementById('error-message');
    const arxivBibtex = document.getElementById('arxiv-bibtex');
    const publishedBibtex = document.getElementById('published-bibtex');
    const publishedTabBtn = document.getElementById('published-tab-btn');

    // Hide previous results
    resultContainer.style.display = 'none';
    errorMessage.style.display = 'none';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
        const response = await fetch('/api/generate-bibtex', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({input: input, lookup_doi: document.getElementById('lookup-doi-cb').checked})
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to generate BibTeX');
        }

        // Show results
        const hasArxiv = !!data.arxiv;
        const hasPublished = !!data.published;

        if (hasArxiv) {
            arxivBibtex.textContent = data.arxiv;
            document.getElementById('arxiv-tab-btn').style.display = 'inline-block';
        } else {
            document.getElementById('arxiv-tab-btn').style.display = 'none';
        }

        if (hasPublished) {
            publishedBibtex.textContent = data.published;
            publishedTabBtn.style.display = 'inline-block';
        } else {
            publishedTabBtn.style.display = 'none';
        }

        // Activate the most relevant tab
        showTab(hasPublished && !hasArxiv ? 'published-tab' : 'arxiv-tab');

        // Show note if DOI was discovered via Crossref
        const noteDiv = document.getElementById('doi-lookup-note');
        if (data.doi_lookup) {
            const pct = Math.round(data.doi_lookup.confidence * 100);
            noteDiv.textContent = `DOI found via Crossref (${pct}% confidence): ${data.doi_lookup.doi}`;
            noteDiv.style.display = 'block';
        } else {
            noteDiv.style.display = 'none';
        }

        resultContainer.style.display = 'block';

    } catch (error) {
        errorMessage.textContent = error.message;
        errorMessage.style.display = 'block';
    }
}

document.getElementById('bibtex-form')?.addEventListener('submit', generateBibtex);

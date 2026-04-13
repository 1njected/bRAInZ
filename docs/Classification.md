# Classification

bRAInZ automatically classifies every ingested item into a category and assigns tags. Classification runs in two LLM passes and optionally consults a set of manually verified items to improve accuracy over time.

---

## How it works

### Inputs

Three signals are used, in priority order:

| Priority | Signal | Source |
|----------|--------|--------|
| 1 (strongest) | **Title** | Page title, PDF subject, or note title |
| 2 | **Description** | `og:description`, meta description, or PDF subject line |
| 3 (supporting) | **Body excerpt** | First 100 words of extracted content (configurable via `classifier_body_words`) |

The body excerpt is intentionally short — it confirms signals from the title, it does not override them.

---

### Pass 1 — Category + Summary

The LLM receives:
- The title, description, and body excerpt
- The full list of categories from `taxonomy.yaml`, each with its description and tag list
- Up to 5 **verified example items** retrieved from the vector index (see [Verified Examples](#verified-examples) below), shown as:
  ```
  "Heap Exploitation in glibc malloc" → reversing
  "Kerberoasting with Rubeus"         → redteam
  ```

Output: one category name and a one-sentence summary.

---

### Pass 2 — Tags

Using the category chosen in Pass 1, the LLM receives:
- The same title, description, and body excerpt
- The allowed tag list for that category (from `taxonomy.yaml`)
- Up to 3 verified examples **from the same category**, shown as:
  ```
  Title: "Heap Exploitation in glibc malloc"
  Tags: ["heap", "buffer-overflow", "rop"]
  ```

The model first lists the concrete techniques it identifies in the content (chain-of-thought), then maps those to tags from the allowed list. Tags not on the allowlist are never returned.

Output: 0–5 tags.

---

### Verified Examples

Every time you manually edit an item's category or tags via **Edit → Save**, that item is marked `verified: true` and its content embedding is stored in the vector index.

When classifying a new item:
1. The classifier embeds `title + first 200 words of content`
2. It searches the vector index, restricted to verified items only
3. The 5 most similar verified items (by cosine similarity) are retrieved
4. Their titles, categories, and tags are injected as few-shot examples into both passes

This means the classifier gets smarter as you verify more items — without any retraining.

If no verified items exist yet, classification falls back to the taxonomy descriptions and tag lists alone.

---

### Taxonomy

Categories and their tags live in `data/taxonomy.yaml`. This file is the single source of truth for:
- Which categories exist and their descriptions
- Which tags are valid per category

Edits to `taxonomy.yaml` take effect immediately (mtime-based cache), without restarting the container.

---

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `ingestion.classifier_body_words` | `100` | Words from body included in the classification prompt |

Set in `data/config.yaml`:

```yaml
ingestion:
  classifier_body_words: 150
```

---

## Reclassification

Reclassification (`Reclassify` button in the UI, or `brainz reclassify` via CLI) re-runs both passes against the current content. It always uses the LLM — it does not short-circuit to a stored result. Verified examples from the index are consulted the same way as during initial ingestion.

Reclassifying a verified item does **not** clear its `verified` flag — the item remains a training example for other items.

---

## Improving classification accuracy

In order of impact:

1. **Fix the taxonomy first** — clear category descriptions and specific tags are the strongest lever. If a category description is ambiguous (e.g. `os` previously said "exploitation"), the LLM will misclassify.

2. **Verify items via Edit → Save** — each verified item becomes a few-shot example. Five verified items in a category is usually enough for reliable classification of similar content.

3. **Use the AI tag suggester** — the **Suggest tags from document…** section in the Edit modal asks the LLM to suggest tags grounded in the item's actual content, which you can then add before saving.

4. **Increase `classifier_body_words`** — raising this from 100 to 200–300 words gives the LLM more context, at the cost of a slightly larger prompt.

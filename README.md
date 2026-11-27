# Uudised

A personal news feed that drops the fuss (scandals, crime, celebrities, outrage, polls, live blogs) and keeps the **top 20 stories that matter**, ranked by importance.

- Each update fetches Estonian and international feeds, and Claude scores every new item against the reader profile in [`pipeline/profile.md`](pipeline/profile.md).
- Coverage of the same event from several outlets becomes one card with several links. Follow-ups join the existing card and mark it "Updated".
- **✓ Read** moves a story to History. **Not interested** hides it, and the next update uses those clicks to learn what to skip.
- Unread stories never fade: an important story found weeks ago stays on top until it's read.
- Only headlines, links and short excerpts are shown. Clicking a headline opens the original article.

## Run it

```sh
cp .env.example .env      # add your ANTHROPIC_API_KEY
./start.sh                # http://localhost:8765, updates every 12 hours
```

`./start.sh --every 6` updates every 6 hours. Without an API key, a crude keyword filter is used instead of Claude.

One-off update without the server: `python -m pipeline.run`.

## Layout

| Path | What it is |
|---|---|
| `pipeline/sources.py` | Feed list |
| `pipeline/profile.md` | What matters to the reader, what counts as noise, the importance scale |
| `pipeline/rank.py` | Claude scoring (and offline fallback) |
| `pipeline/run.py` | One update: fetch, score, merge into the story pool |
| `pipeline/serve.py` | Local server: site, click storage, update timer |
| `site/` | The reading page |
| `data/` | Your clicks and seen items (not committed) |

## Sources

ERR (ET + EN), Postimees, Äripäev, Õhtuleht, Levila (titles and links only), BBC, The Guardian (API key), The Verge, Ars Technica, TechCrunch. Delfi is left out: its terms forbid automated collection.

## Tests

```sh
python -m unittest discover tests
python -m pipeline.run --fixtures tests/fixtures --offline   # dry run on sample feeds
```

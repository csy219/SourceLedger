# docs/demo

Walkthrough media for the root README.

```text
cover.png        video cover / first frame
query.gif        Query tab, 6-10s
retrieval.gif    Retrieval tab, 6-10s
context.gif      Context tab, 6-10s
resilience.gif   Resilience tab, 6-10s
security.gif     Security tab, 6-10s
runtime.gif      Runtime tab, 6-10s
```

Recording checklist:

1. Start PostgreSQL, Redis, the FastAPI app and `npm run dev`.
2. Hide anything private (API keys, chat apps, bookmarks). Browser to 110-125% zoom, F11.
3. Record 6-10 seconds per tab with ScreenToGif, export as GIF.
4. Record one 2-3 minute pass with Xbox Game Bar (Win + Alt + R) for the mp4.
5. Upload the mp4 to a GitHub issue comment to get a user-attachments URL, then paste it
   into the README demo block.

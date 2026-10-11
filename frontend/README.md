# SourceLedger Workbench

React workbench for the SourceLedger verifiable RAG Runtime.

## Development

```powershell
cd C:\Users\ASUS\Desktop\agent-learningstage1\project_a\frontend
npm.cmd install
npm.cmd run dev
```

The frontend expects the API at:

```text
http://127.0.0.1:8000
```

Override with `.env.local`:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Build

```powershell
npm.cmd run build
```

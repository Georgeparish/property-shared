---
paths:
  - "property_app/**"
---

# Property App Rules

MCP App with Prefab UI dashboards. Uses FastMCP 3.2+ and Prefab UI 0.19+. Full reference in `property_app/CLAUDE.md`.

## Dashboard Pattern

- Use `@mcp.tool(app=True)` with server-side data fetch — NOT `@app.ui()` + `CallTool`
- Always return `ToolResult(content=text_summary, structured_content=view)` so the LLM gets readable text
- Data tools return `dict`, apply `_slim()` from `tools.py` to strip bulk fields (`raw`, `images`, `floorplans`, `epc_match`)
- Each dashboard file has a `_helper()` function shared by both the data tool and dashboard tool

## Registration

- New dashboard modules must be imported in `server.py` `main()` — decorators register on import
- Tests go in `tests/test_app_{name}.py`

## Tool Descriptions

- Neutral data-assembly language — "yield calculation" not "yield estimate", "comparable sales data" not "deal analysis"
- All tools: `readOnlyHint=True`. External API tools: add `openWorldHint=True`

## Prefab Prop Gotchas

- `Tab(title="X")` — NOT `label`
- `ChartSeries(dataKey="x")` — camelCase, NOT `data_key`
- `BarChart(xAxis="x")` — camelCase, NOT `x_axis`
- `Ring(size="lg")` — string, NOT int
- `Sparkline(curve="smooth")` — valid: `"linear"`, `"smooth"`, `"step"`
- `Image` does NOT render in claude.ai — blocked by CSP at iframe level, all approaches fail

## Docs Lookup

Check Prefab component props: `https://prefab.prefect.io/docs/protocol/{component-name}.md`

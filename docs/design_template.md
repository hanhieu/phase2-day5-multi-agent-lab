# Design Template — Multi-Agent Research System

## Problem

Người dùng đặt một câu hỏi nghiên cứu phức tạp (ví dụ: "GraphRAG state-of-the-art là gì?").
Hệ thống cần: (1) tìm kiếm thông tin từ web, (2) phân tích và đánh giá evidence,
(3) viết câu trả lời cuối cùng có citations. Một single-agent prompt không thể làm
tốt cả ba việc cùng lúc vì mỗi việc cần system prompt, output format, và temperature khác nhau.

## Why multi-agent?

Single-agent baseline chỉ dùng pretrained knowledge của LLM — không có retrieval,
dễ hallucinate (thực tế đã quan sát: baseline mô tả sai định nghĩa GraphRAG).
Multi-agent giải quyết bằng cách:
- **Researcher** fetch real-time web sources (Tavily) → grounding thực tế
- **Analyst** đánh giá evidence quality độc lập với việc viết
- **Writer** tổng hợp với citations rõ ràng
- Mỗi agent có thể retry độc lập khi fail, không cần restart toàn bộ pipeline

## Agent roles

| Agent | Responsibility | Input | Output | Failure mode |
|---|---|---|---|---|
| Supervisor | Routing: quyết định agent nào chạy tiếp theo, khi nào stop | `ResearchState` | Updated `route_history` | Loop vô hạn → fix bằng `max_iterations` |
| Researcher | Tìm kiếm web (Tavily), tổng hợp research notes | `request.query`, `request.max_sources` | `state.sources`, `state.research_notes` | Search API fail → fallback mock; LLM fail → retry 3× |
| Analyst | Phân tích research notes, đánh giá evidence | `state.research_notes` | `state.analysis_notes` | Empty notes → raise error ngay, không gọi LLM |
| Writer | Viết final answer với inline citations | `state.research_notes`, `state.analysis_notes`, `state.sources` | `state.final_answer` | LLM fail → retry 3×; empty notes → raise error |

## Shared state

| Field | Type | Lý do cần |
|---|---|---|
| `request` | `ResearchQuery` | Query gốc, max_sources, audience — cần ở mọi agent |
| `iteration` | `int` | Đếm số lần supervisor chạy → enforce max_iterations |
| `route_history` | `list[str]` | Debug trace: ai đã chạy theo thứ tự nào |
| `sources` | `list[SourceDocument]` | Researcher lưu, Writer dùng để build References section |
| `research_notes` | `str \| None` | Output của Researcher, input của Analyst và Writer |
| `analysis_notes` | `str \| None` | Output của Analyst, input của Writer |
| `final_answer` | `str \| None` | Output của Writer, hiển thị cho user |
| `trace` | `list[dict]` | Mỗi agent append event: tokens, cost, duration → benchmark |
| `errors` | `list[str]` | Supervisor check field này để stop sớm khi có lỗi |

## Routing policy

```
START
  │
  ▼
Supervisor ──── research_notes is None? ──► Researcher ──┐
  │                                                       │
  │◄──────────────────────────────────────────────────────┘
  │
  ├──── analysis_notes is None? ──► Analyst ──┐
  │                                            │
  │◄───────────────────────────────────────────┘
  │
  ├──── final_answer is None? ──► Writer ──┐
  │                                        │
  │◄───────────────────────────────────────┘
  │
  ├──── errors not empty OR iteration >= max_iterations ──► END (early stop)
  │
  └──── all fields populated ──► END (done)
```

## Guardrails

- **Max iterations**: `max_iterations=6` (từ `Settings`). Supervisor stop ngay khi `iteration >= max_iterations`.
- **Timeout**: `timeout_seconds=60` truyền vào OpenAI client. Nếu LLM call vượt quá 60s → raise timeout error.
- **Retry**: `tenacity` retry 3 lần với exponential backoff (2s, 4s, 8s) cho mọi LLM call.
- **Fallback**: Tavily search fail → fallback về mock sources tự động (không crash pipeline).
- **Validation**: Analyst và Writer check `research_notes is not None` trước khi gọi LLM. Nếu empty → append error vào `state.errors` và raise `AgentExecutionError`.

## Benchmark plan

| Query | Metric | Expected outcome |
|---|---|---|
| "Research GraphRAG state-of-the-art and write a 500-word summary" | Latency | baseline ~10s, multi-agent ~47s |
| "Research GraphRAG state-of-the-art and write a 500-word summary" | Cost | baseline ~$0.0004, multi-agent ~$0.0016 |
| "Research GraphRAG state-of-the-art and write a 500-word summary" | Quality (heuristic) | baseline 5/10, multi-agent 10/10 |
| "Research GraphRAG state-of-the-art and write a 500-word summary" | Hallucination | baseline: sai định nghĩa; multi-agent: đúng (Microsoft Research) |
| "Compare single-agent and multi-agent workflows for customer support" | Failure rate | 0/1 (cả hai không fail) |
| "Summarize production guardrails for LLM agents" | Citation coverage | multi-agent: có References section; baseline: không có |

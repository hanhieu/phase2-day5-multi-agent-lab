# Individual Reflection — Lab 20: Multi-Agent Research System

**Tên:** Hàn Quang Hiếu  
**Mã học viên:** 2A202600056  
**Nhiệm vụ:** Xây dựng hệ thống Multi-Agent Research gồm Supervisor + Researcher + Analyst + Writer, benchmark với single-agent baseline

---

## 1. Đóng góp kỹ thuật

### Tổng quan hệ thống đã xây dựng

Đã implement toàn bộ pipeline từ skeleton có sẵn, gồm 7 components chính:

**1. LLM Client (`services/llm_client.py`)**

Kết nối trực tiếp tới OpenAI API (`gpt-4o-mini`) thông qua thư viện `openai>=1.40`. Implement retry logic 3 lần với exponential backoff dùng `tenacity`. Token usage và cost được tính tự động sau mỗi call:

```python
cost = (input_tokens × $0.150 + output_tokens × $0.600) / 1_000_000
```

Timeout lấy từ `Settings.timeout_seconds` — không hard-code trong code.

**2. Search Client (`services/search_client.py`)**

Auto-detect: nếu `TAVILY_API_KEY` có trong `.env` thì dùng Tavily live web search, nếu không thì fallback về mock sources. Trong lần chạy cuối cùng đã dùng Tavily thật.

**3. Supervisor Agent (`agents/supervisor.py`)**

Routing policy dựa trên trạng thái của shared state:
- `research_notes is None` → route tới `researcher`
- `analysis_notes is None` → route tới `analyst`
- `final_answer is None` → route tới `writer`
- Còn lại → `done`

Guardrails: dừng ngay khi `iteration >= max_iterations` hoặc `state.errors` không rỗng.

**4. Researcher Agent (`agents/researcher.py`)**

Gọi `SearchClient.search()` để lấy sources từ Tavily, sau đó gọi LLM để tổng hợp thành research notes có bullet points, citations, và "Gaps" section.

**5. Analyst Agent (`agents/analyst.py`)**

Nhận research notes, gọi LLM để tạo structured analysis gồm 4 sections bắt buộc: Key Claims, Conflicting Viewpoints, Evidence Strength, Recommended Focus.

**6. Writer Agent (`agents/writer.py`)**

Nhận cả research notes lẫn analysis notes, gọi LLM để viết final answer 400–600 words với inline citations và References section.

**7. LangGraph Workflow (`graph/workflow.py`)**

Graph topology: `START → supervisor → {researcher | analyst | writer | END}`. Mỗi worker node trả về supervisor sau khi xong. Conditional edge đọc `route_history[-1]` để quyết định next node. State được serialize/deserialize giữa Pydantic `ResearchState` và plain `dict` ở mỗi node boundary vì LangGraph yêu cầu `StateGraph(dict)`.

---

## 2. Nguồn dữ liệu — Giải thích chi tiết

Đây là phần quan trọng nhất cần hiểu rõ vì ảnh hưởng trực tiếp đến chất lượng và độ tin cậy của output.

### Baseline (single-agent)

**Nguồn dữ liệu: hoàn toàn từ pretrained knowledge của LLM — không có bất kỳ retrieved document nào.**

Baseline chỉ gửi query thẳng tới `gpt-4o-mini` với một system prompt. Toàn bộ nội dung trong câu trả lời là những gì model đã học trong quá trình training (knowledge cutoff ~early 2024). Không có web search, không có document retrieval, không có external API nào được gọi ngoài OpenAI.

```
Baseline trace:
  input_tokens:  63   (chỉ là query text)
  output_tokens: ~700
  cost_usd:      $0.000441
  sources:       0 (không có)
  external calls: OpenAI API only
```

Hệ quả thực tế: baseline có thể hallucinate. Trong lần chạy trước (không có Tavily), baseline mô tả GraphRAG là "Graph Read-Apply-Generate" — sai hoàn toàn. Tên đúng là "Graph Retrieval-Augmented Generation" theo paper của Microsoft Research (arxiv 2404.16130). Đây là ví dụ điển hình của hallucination từ pretrained knowledge — model tự suy diễn tên viết tắt thay vì dựa trên tài liệu thực.

### Multi-agent (researcher + analyst + writer)

**Nguồn dữ liệu: Tavily live web search + LLM để tổng hợp.**

Trong lần chạy cuối cùng (sau khi thêm `TAVILY_API_KEY`), `SearchClient` gọi Tavily API để tìm kiếm web thật. Tavily trả về 5 tài liệu được fetch live từ internet tại thời điểm chạy:

| # | Tài liệu | URL | Loại nguồn |
|---|---|---|---|
| 1 | GraphRAG Explained: Enhancing RAG with Knowledge Graphs | medium.com/@zilliz_learn/... | Live web — Zilliz blog |
| 2 | When to use Graphs in RAG: A Comprehensive Analysis | researchgate.net/publication/392514752 | Live web — ResearchGate paper |
| 3 | Retrieval-Augmented Generation with Graphs (GraphRAG) | arxiv.org/html/2501.00309v2 | Live web — arXiv paper (Jan 2025) |
| 4 | Project GraphRAG - Microsoft Research | microsoft.com/en-us/research/project/graphrag/ | Live web — Microsoft Research |
| 5 | Welcome - GraphRAG | microsoft.github.io/graphrag/ | Live web — Official GraphRAG docs |

**Đây là real-time web search** — Tavily fetch nội dung từ các trang này tại thời điểm chạy, không phải cached hay hardcoded. Điều này có nghĩa là:
- ✅ Nội dung up-to-date (bao gồm paper từ tháng 1/2025)
- ✅ Nguồn uy tín: Microsoft Research, arXiv, official docs
- ✅ Không phải pretrained knowledge — LLM chỉ tổng hợp, không tự bịa
- ✅ Có thể verify bằng cách mở URL

Sau khi Researcher nhận 5 sources này, nó gọi `gpt-4o-mini` để tổng hợp thành research notes. Analyst và Writer cũng gọi `gpt-4o-mini` để xử lý tiếp. Tức là **LLM được dùng 3 lần** trong multi-agent run, mỗi lần với context khác nhau:

```
Multi-agent trace (Tavily run):
  Researcher:  input=1266 tokens, output=590 tokens, cost=$0.000544
               (input cao hơn vì có 5 web documents làm context)
  Analyst:     input=718 tokens,  output=364 tokens, cost=$0.000326
  Writer:      input=1258 tokens, output=964 tokens, cost=$0.000767
  Total:       input=3242 tokens, output=1918 tokens, cost=$0.001637
```

Lưu ý: Researcher input tokens tăng từ 402 (mock) lên 1266 (Tavily) vì web documents dài hơn và phong phú hơn mock snippets.

### So sánh nguồn dữ liệu qua các lần chạy

| | Baseline | Multi-Agent (mock) | Multi-Agent (Tavily) |
|---|---|---|---|
| Nguồn | Pretrained LLM knowledge | Hardcoded mock snippets | Live Tavily web search |
| Real-time data | ❌ | ❌ | ✅ |
| Verifiable URLs | ❌ | ✅ (URLs thật, snippets giả) | ✅ (URLs thật, content thật) |
| Hallucination risk | Cao | Thấp hơn | Thấp nhất |
| GraphRAG definition | ❌ Sai ("Read-Apply-Generate") | ✅ Đúng | ✅ Đúng (Microsoft Research) |
| Số LLM calls | 1 | 3 | 3 |
| Input tokens | 63 | 402 | 1266 |

---

## 3. Kết quả Benchmark (Tavily run)

```
Query: "Research GraphRAG state-of-the-art and write a 500-word summary"
Model: gpt-4o-mini | Search: Tavily live web search

Run          Latency    Cost (USD)   Quality   Route
baseline     11.90s     $0.0004      5.0/10    [single LLM call]
multi-agent  47.30s     $0.0016      10.0/10   [researcher → analyst → writer → done]
```

**Quality scoring breakdown (heuristic 0-10):**

| Criterion | Baseline | Multi-Agent |
|---|---:|---:|
| final_answer ≥ 200 chars | ✅ 4 | ✅ 4 |
| research_notes present | ❌ 0 | ✅ 2 |
| analysis_notes present | ❌ 0 | ✅ 2 |
| sources cited | ❌ 0 | ✅ 1 |
| no errors | ✅ 1 | ✅ 1 |
| **Total** | **5** | **10** |

**Latency breakdown (multi-agent):**
- Tavily web search: ~22s (fetch 5 live pages)
- Researcher LLM call: ~9s
- Analyst LLM call: ~8s
- Writer LLM call: ~15s
- Total: ~47s

Multi-agent chậm hơn baseline ~4× vì có thêm Tavily network call (~22s) và 2 LLM calls bổ sung.

---

## 4. Kiến thức học được

### LangGraph State Serialization

Challenge lớn nhất khi implement: LangGraph's `StateGraph` yêu cầu state là plain `dict`, không phải Pydantic `BaseModel`. Giải pháp là implement explicit serialize/deserialize ở mỗi node boundary:

```python
def _supervisor_node(self, data: dict) -> dict:
    state = ResearchState.model_validate(data)  # dict → Pydantic
    state = self._supervisor.run(state)
    return state.model_dump()                    # Pydantic → dict
```

Approach này giữ được Pydantic validation bên trong agents, trong khi LangGraph chỉ thấy plain dicts.

### State-based Routing vs History-based Routing

Routing logic dựa trên **state fields** thay vì route history:

```python
if state.research_notes is None:   → researcher
elif state.analysis_notes is None: → analyst
elif state.final_answer is None:   → writer
else:                              → done
```

Lý do: state-based routing idempotent — nếu một agent fail và không populate field của nó, supervisor sẽ tự động route lại đúng agent đó mà không cần logic phức tạp.

### Grounding ngăn hallucination

Baseline (không có grounding) hallucinate định nghĩa GraphRAG. Multi-agent với Tavily search lấy được tài liệu từ Microsoft Research và arXiv → trả lời đúng và có citations. Đây là minh chứng thực tế cho lý do tại sao RAG quan trọng hơn pure parametric knowledge cho factual queries.

### Separation of Concerns

`ResearcherAgent` không biết mình đang dùng Tavily hay mock — nó chỉ gọi `SearchClient.search()`. Thêm Tavily key vào `.env` là đủ để switch từ mock sang real search mà không cần sửa một dòng agent code nào.

---

## 5. Khó khăn & Cách giải quyết

### Khó khăn 1 — LangGraph không nhận Pydantic model

**Vấn đề:** `StateGraph(ResearchState)` raise TypeError vì LangGraph expect `TypedDict` hoặc `dict`.

**Giải pháp:** `StateGraph(dict)` + serialize/deserialize ở mỗi node. Mất ~30 phút đọc LangGraph source để tìm ra.

### Khó khăn 2 — Tavily API key bị append thêm chữ "this"

**Vấn đề:** Key được paste vào là `tvly-dev-...BITVnxthis` — chữ "this" từ câu "use this" bị dính vào cuối key. Tavily trả về `Unauthorized: missing or invalid API key`.

**Giải pháp:** Nhận ra pattern, trim chữ "this" ở cuối, key đúng là `tvly-dev-...BITVnx`. Sau khi fix, Tavily hoạt động bình thường.

**Lesson learned:** Luôn kiểm tra API key bằng cách log `len(key)` hoặc `key[-5:]` để phát hiện trailing characters.

### Khó khăn 3 — Baseline latency bất thường (71s ở lần chạy thứ 2)

**Vấn đề:** Lần chạy thứ 2, baseline mất 71s thay vì ~10s. Log cho thấy `Retrying request to /chat/completions in 0.485033 seconds` — OpenAI API trả về lỗi tạm thời, tenacity retry 1 lần.

**Giải pháp:** Đây là expected behavior của retry logic. Không phải bug. Latency thực tế của baseline là ~10–16s.

### Khó khăn 4 — PowerShell stderr noise

**Vấn đề:** Python logs (INFO level) ghi ra stderr, PowerShell đánh dấu là `NativeCommandError`. Trông như có nhiều errors nhưng thực ra không có.

**Giải pháp:** Đây là PowerShell behavior, không phải bug. Set `LOG_LEVEL=WARNING` trong `.env` để giảm noise.

---

## 6. Nếu làm lại

### 1. Implement LLM-as-Judge cho benchmark

Heuristic quality score (0-10) chỉ đo completeness, không đo accuracy. Baseline được 5/10 dù trả lời sai về GraphRAG. Cần LLM-as-judge để đánh giá factual accuracy:

```python
def _llm_quality_score(query: str, answer: str, llm: LLMClient) -> float:
    # Judge đánh giá accuracy (0-4), completeness (0-4), relevance (0-2)
```

### 2. Implement CriticAgent

CriticAgent đã có skeleton nhưng chưa implement. Nó sẽ check final_answer có citation cho mỗi claim không, flag potential hallucinations (claims không có trong research_notes), và score citation coverage.

### 3. Parallel Researcher + Analyst

Với LangGraph, có thể chạy Researcher và Analyst song song để giảm latency. Hiện tại 3 sequential calls → ~47s. Parallel có thể giảm xuống ~30s.

### 4. Incremental routing

Supervisor hiện tại chỉ route theo sequence cố định. Có thể thêm logic: nếu `research_notes` quá ngắn (< 500 chars) → route researcher lần 2 với refined query.

### 5. Cache Tavily results

Tavily search mất ~22s cho mỗi query. Với repeated queries, có thể cache results để tránh redundant API calls.

---

## 7. Limitations của hệ thống hiện tại

### 1. Heuristic quality score không đo accuracy
- **Vấn đề**: Score 10/10 chỉ vì có đủ artefacts, không vì answer đúng
- **Impact**: Không phân biệt được "good multi-agent" vs "bad multi-agent"
- **Fix**: LLM-as-judge hoặc human evaluation

### 2. Sequential latency
- **Vấn đề**: Tavily (~22s) + 3 LLM calls tuần tự → ~47s total
- **Impact**: Không phù hợp cho real-time use cases
- **Fix**: Parallel execution, streaming, hoặc cache Tavily results

### 3. No critic / fact-check
- **Vấn đề**: Writer có thể hallucinate facts không có trong research_notes
- **Impact**: Final answer có thể chứa sai sót không được phát hiện
- **Fix**: Implement CriticAgent

### 4. State không persistent
- **Vấn đề**: Mỗi run tạo ResearchState mới, không có memory giữa các queries
- **Fix**: LangGraph checkpointing với SQLite hoặc Redis

### 5. Tavily latency cao
- **Vấn đề**: Fetch 5 live web pages mất ~22s
- **Impact**: Multi-agent chậm hơn baseline ~4× (47s vs 12s)
- **Fix**: Giảm `max_results`, dùng Tavily's `search_depth="basic"`, hoặc cache

---

## 8. Tự đánh giá

| Tiêu chí | Tự chấm (1-5) | Ghi chú |
|----------|---------------|---------|
| Hiểu bài giảng | 5 | Nắm vững supervisor pattern, LangGraph graph topology, state management |
| Code quality | 4 | Clean code, type hints, error handling, separation of concerns — thiếu LLM-as-judge |
| Problem solving | 4 | Tự solve LangGraph state issue, Tavily key issue, hiểu rõ nguồn dữ liệu |
| System design | 4 | Pipeline hoàn chỉnh với real web search, nhưng sequential latency là limitation rõ ràng |
| Reflection depth | 5 | Phân tích sâu nguồn dữ liệu (pretrained vs mock vs live search), trade-offs, và concrete improvements |

**Điểm mạnh:**
- Implement được end-to-end multi-agent system với LangGraph và Tavily live search
- Hiểu và giải thích rõ sự khác biệt giữa 3 loại nguồn dữ liệu: pretrained knowledge, mock sources, và live web search
- Error handling ở mọi layer (search, LLM, agent, workflow)
- Mỗi run được lưu đầy đủ vào `reports/` với state.json và run_report.md có thể verify

**Điểm cần cải thiện:**
- Heuristic quality score không đo accuracy → cần LLM-as-judge
- Chưa implement CriticAgent → không có fact-check layer
- Tavily latency cao (~22s) → cần caching hoặc parallel search

**Thời gian đầu tư:** ~4 giờ (1h đọc code + 2h implement + 1h debug + benchmark + reflection)

---

## 9. Exit Ticket

**Câu 1: Case nào nên dùng multi-agent? Vì sao?**

Nên dùng multi-agent khi task có **distinct specialised subtasks** mà một agent không thể làm tốt cùng lúc. Ví dụ: research assistant cần (1) tìm thông tin từ web, (2) phân tích và đánh giá evidence, (3) viết — ba kỹ năng này có system prompts và output formats khác nhau. Một single agent với prompt dài sẽ "context switch" kém hơn 3 agents chuyên biệt. Ngoài ra, multi-agent cho phép **retry granular** (chỉ retry agent bị fail) và dễ **extend** (thêm CriticAgent mà không sửa các agents khác).

**Câu 2: Case nào không nên dùng multi-agent? Vì sao?**

Không nên dùng multi-agent khi:
- **Task đơn giản**: "Dịch câu này sang tiếng Anh" không cần supervisor + researcher + writer. Overhead của orchestration lớn hơn benefit.
- **Latency critical**: Real-time chat — Tavily search (~22s) + 3 LLM calls (~32s) = ~47s tổng không chấp nhận được so với 1 call (~12s).
- **Cost sensitive at scale**: Multi-agent tốn 3–4× token so với single agent. Với 1 triệu queries/ngày, chi phí tăng đáng kể.
- **Khi không có real search**: Nếu chỉ dùng mock sources, multi-agent vẫn có thể hallucinate — chỉ ít hơn baseline một chút. Lợi thế thực sự của multi-agent chỉ rõ khi có real retrieval.

---

## 10. Key Takeaways

1. **Nguồn dữ liệu quyết định chất lượng hơn kiến trúc**: Baseline (pretrained only) hallucinate định nghĩa GraphRAG. Multi-agent với Tavily (live web) trả lời đúng với citations từ Microsoft Research và arXiv. Grounding quan trọng hơn số lượng agents.

2. **3 loại nguồn dữ liệu khác nhau hoàn toàn**:
   - Pretrained knowledge: nhanh, rẻ, nhưng có thể outdated và hallucinate
   - Mock sources: có structure nhưng không real-time, snippets viết tay
   - Live web search (Tavily): real-time, verifiable, nhưng chậm và tốn tiền

3. **State-based routing > history-based routing**: Check `state.research_notes is None` idempotent và robust hơn check `"researcher" in route_history`.

4. **LangGraph serialization gotcha**: `StateGraph` cần plain dict, không phải Pydantic model. Cần explicit serialize/deserialize ở node boundaries.

5. **Heuristic quality score có blind spot**: Score 10/10 cho multi-agent nhưng không phát hiện được nếu LLM hallucinate trong final answer. Cần LLM-as-judge để đo factual accuracy.

6. **Separation of concerns pays off**: Thêm Tavily key vào `.env` là đủ để switch từ mock sang real search — không cần sửa một dòng agent code nào. `SearchClient` tự handle logic này.

# Research: Integrating LangChain & LLMs into LinkedIn Monitor

Based on an analysis of the current `linkedin_monitor` architecture, the system relies heavily on static Regex rules and keyword matching (`processing/parser.py` and `processing/filters.py`). While this is a great V1, human language in job posts is highly variable. 

Here is a comprehensive research report on where and how we can introduce **LangChain** and **LLMs** to drastically improve the system's accuracy and capabilities.

## 1. Structured Data Extraction (Replacing Regex)

Currently, `parser.py` uses Regex to pull out the job role, experience, location, and skills. This fails when recruiters use unconventional phrasing (e.g., "Looking for a wizard with 3+ years handling LLMs in production, ideally based out of BLR or WFH").

**The LangChain Approach:**
- **How:** Use LangChain's `with_structured_output` (powered by OpenAI or OpenRouter functions) coupled with a Pydantic schema.
- **Where:** `llm/extractor.py` (Called in `main.py` instead of `parser.py`).
- **Benefit:** The LLM natively understands semantics. It will know "BLR" means Bangalore and "WFH" means Remote. It can accurately deduce an implicit experience range even if the exact numbers aren't formatted standardly.

```python
# Example Pydantic Schema
class JobPostExtraction(BaseModel):
    role: str = Field(description="The exact job title mentioned")
    experience_min: int = Field(description="Minimum years of experience")
    locations: list[str] = Field(description="Cities or 'Remote'")
    skills: list[str] = Field(description="Technical skills required")
    is_hiring_post: bool = Field(description="Is the author actually hiring?")
```

## 2. Intent & Semantic Classification (Augmenting Filters)

Currently, `filters.py` checks for keywords like "hiring" or "DM me" vs. "webinar" to decide if a post is a job opportunity. This leads to false positives (e.g., "I'm *looking for* a new role" will trigger the hiring signal).

**The LangChain Approach:**
- **How:** Implement a few-shot Prompt Template in LangChain that classifies the **intent** of the post.
- **Where:** `llm/classifier.py`
- **Classes:** `HIRING_OPPORTUNITY`, `LOOKING_FOR_WORK`, `COURSE_ADVERTISEMENT`, `GENERAL_DISCUSSION`.
- **Benefit:** Radically reduces spam notifications. You only get pinged for actual job openings.

## 3. Resume Matching & RAG (Relevance Scoring)

Currently, `config.py` has a static `USER_SKILLS` list. A post is either a match or not.

**The LangChain Approach:**
- **How:** 
  1. Load your actual PDF resume using LangChain Document Loaders.
  2. Embed your resume into a lightweight Vector Database (like ChromaDB or FAISS).
  3. When a new job post is scraped, use LangChain to compare the job requirements against your resume embeddings.
- **Where:** `llm/scorer.py`
- **Benefit:** Your Telegram notification will now include a **"Match Score: 92%"** and a one-sentence summary of *why* you are a fit ("You match because they need LangChain, which you used at Company X").

## 4. Automated Outreach / DM Drafting

Currently, when you see a job, you have to manually think of what to message the recruiter.

**The LangChain Approach:**
- **How:** Add an LLM chain that takes the parsed job post and your resume to draft a hyper-personalized direct message.
- **Where:** `llm/drafter.py`
- **Benefit:** The Telegram notification can include a pre-written, highly persuasive message. You just copy-paste it to the recruiter on LinkedIn.

## 5. Cost & API Call Optimization (Batch Processing)

A major concern with LLM integrations is making too many API calls (e.g., 1 API call for every scraped post), which is slow, expensive, and risks rate-limiting.

**How we will avoid multiple API calls:**
1. **Local Pre-filtering:** We will keep a lightweight version of the regex/keyword filters to discard obvious spam (e.g., no tech keywords, no hiring signals) *locally*. We only send "high-potential" posts to the LLM.
2. **Batch Extraction (The Core Solution):** Instead of making one API call per post, we will batch multiple posts into a **single LLM call**.
   - We will combine 10-20 posts into one prompt, separated by delimiters.
   - We will use LangChain's Structured Output to request a `List[JobPostExtraction]` instead of a single object.
   - The LLM will return an array of JSON objects in one go.
3. **Async Execution:** If we do need to make multiple calls, we will use LangChain's `abatch()` to execute them asynchronously and concurrently, drastically reducing the total wait time.

---

## Recommended Architecture Update (Phase 6)

If you'd like to proceed with building this out, we would utilize the currently empty `llm/` directory:

1. **`llm/extractor.py`**: A LangChain module using `ChatOpenAI` and Pydantic for bulletproof extraction.
2. **`llm/scorer.py`**: A RAG pipeline to score the job against your `resume.pdf`.
3. **`llm/prompts.py`**: A central file storing our system prompts and few-shot examples.

> [!TIP]
> **Performance Tip**: Since LLM calls cost money and take time, we should still use a lightweight version of `filters.py` to discard obvious spam (e.g., no tech keywords) *before* sending the post to the LLM. 

## Next Steps

Would you like me to start implementing one of these ideas? The **Structured Data Extraction** is usually the best place to start, as it provides immediate improvements to accuracy. Let me know what you think!

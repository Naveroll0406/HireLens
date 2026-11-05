"""
LinkedIn AI Job Post Monitor — Configuration

Central configuration for all keywords, locations, filters, timing,
and behavioral parameters. Edit this file to customize the monitor.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Database
DATABASE_PATH = BASE_DIR / "data" / "linkedin_monitor.db"

# Persistent browser profile (stores LinkedIn login session)
BROWSER_PROFILE_DIR = BASE_DIR / "data" / "browser_profile"

# Logs
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "monitor.log"

# ---------------------------------------------------------------------------
# LinkedIn Search — Keywords
# ---------------------------------------------------------------------------
# These keywords are searched in LinkedIn Posts.
# Each keyword generates a separate search query.
DEFAULT_KEYWORDS = [
    "AI Engineer",
    "GenAI Engineer",
    "Generative AI Engineer",
    "LLM Engineer",
    "RAG Engineer",
    "AI Developer",
    "Prompt Engineer",
    "LangChain",
    "Vector Database",
    "AI Infrastructure Engineer",
    "MLOps",
]

# ---------------------------------------------------------------------------
# LinkedIn Search — Locations
# ---------------------------------------------------------------------------
# Posts are accepted if they mention ANY of these locations (case-insensitive).
# If a post has no detectable location, it is accepted by default.
TARGET_LOCATIONS = [
    "Hyderabad",
    "Bangalore",
    "Bengaluru",
    "Pune",
    "Chennai",
    "Mumbai",
    "Gurgaon",
    "Gurugram",
    "Noida",
    "Delhi",
    "Ahmedabad",
    "Surat",
    "Kolkata",
    "Jaipur",
    "Chandigarh",
    "Indore",
    "Kochi",
    "Trivandrum",
    "Thiruvananthapuram",
    "Coimbatore",
    "Bhubaneswar",
    "Nagpur",
    "Lucknow",
    "Mysore",
    "Visakhapatnam",
    "Vizag",
    "Vadodara",
    "Gandhinagar",
    "Remote",
    "Work from home",
    "WFH"
]

# ---------------------------------------------------------------------------
# Other locations we recognise but do NOT target
# ---------------------------------------------------------------------------
# Extracted so a post that says "based in Berlin" is scored as a location
# mismatch instead of "no location mentioned". Add your own as needed.
OTHER_LOCATIONS = [
    "USA", "US", "United States", "New York", "San Francisco", "Bay Area", "Seattle",
    "Austin", "Boston", "Chicago", "Canada", "Toronto", "Vancouver",
    "UK", "United Kingdom", "London", "Ireland", "Dublin",
    "Germany", "Berlin", "Munich", "Netherlands", "Amsterdam", "France", "Paris",
    "Poland", "Warsaw", "Spain", "Portugal", "Lisbon", "Europe", "EU",
    "Singapore", "Dubai", "UAE", "Abu Dhabi", "Saudi Arabia", "Riyadh", "Qatar",
    "Australia", "Sydney", "Melbourne", "Japan", "Tokyo", "Philippines", "Manila",
    "Vietnam", "Malaysia", "Kuala Lumpur", "Sri Lanka", "Colombo", "Nepal", "Bangladesh", "Dhaka",
]

# ---------------------------------------------------------------------------
# Location Aliases / Abbreviations
# ---------------------------------------------------------------------------
# Maps shorthand a post might use to a canonical location. The canonical value
# MUST appear in TARGET_LOCATIONS above, so alias matches still pass the filter.
LOCATION_ALIASES = {
    "blr": "Bangalore",
    "bglr": "Bangalore",
    "hyd": "Hyderabad",
    "ncr": "Delhi",
    "new delhi": "Delhi",
    "ggn": "Gurugram",
    "wfh": "Remote",
    "work from home": "Remote",
}

# ---------------------------------------------------------------------------
# Experience Filter
# ---------------------------------------------------------------------------
# Posts are accepted if the mentioned experience range overlaps with this range.
# If no experience is detected in the post, it is accepted by default.
EXPERIENCE_MIN = 0  # years
EXPERIENCE_MAX = 10  # years

# ---------------------------------------------------------------------------
# User Profile — Skills (for relevance scoring in V2)
# ---------------------------------------------------------------------------
USER_SKILLS = [
    "Python",
    "LangChain",
    "RAG",
    "LangGraph",
    "Vector Databases",
    "LLM",
    "Generative AI",
    "Prompt Engineering",
    "ChromaDB",
    "Pinecone",
    "OpenAI",
    "HuggingFace",
    "Transformers",
    "NLP",
    "FastAPI",
    "Docker",
    "claude code"
]

# ---------------------------------------------------------------------------
# Known AI/ML Skills — For extraction from posts
# ---------------------------------------------------------------------------
KNOWN_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++",
    "LangChain", "LlamaIndex", "RAG", "Retrieval Augmented Generation",
    "LLM", "Large Language Model", "GPT", "Claude", "Gemini", "Llama",
    "Mistral", "Anthropic", "OpenAI",
    "Vector Database", "ChromaDB", "Chroma", "Pinecone", "Weaviate",
    "Milvus", "Qdrant", "FAISS", "pgvector",
    "Prompt Engineering", "Fine-tuning", "Fine tuning", "RLHF", "DPO",
    "LoRA", "QLoRA", "PEFT",
    "Transformers", "HuggingFace", "Hugging Face",
    "NLP", "Natural Language Processing", "Computer Vision",
    "PyTorch", "TensorFlow", "Keras", "JAX", "scikit-learn",
    "MLOps", "ML Engineering", "Data Engineering",
    "AWS", "Azure", "GCP", "SageMaker", "Bedrock", "Vertex AI",
    "Docker", "Kubernetes", "FastAPI", "Flask", "Django",
    "MongoDB", "PostgreSQL", "Redis", "Elasticsearch",
    "Streamlit", "Gradio",
    "LangGraph", "LangSmith", "CrewAI", "AutoGen", "Semantic Kernel",
    "Agentic AI", "AI Agents", "Multi-Agent",
]

# ---------------------------------------------------------------------------
# Strict AI Role Keywords — Posts MUST match one of these to be displayed
# ---------------------------------------------------------------------------
AI_ROLE_KEYWORDS = [
    "AI Engineer",
    "LLM Engineer",
    "Generative AI Engineer",
    "GenAI Engineer",
    "Machine Learning Engineer",
    "ML Engineer",
    "Applied AI Engineer",
    "AI Research Engineer",
    "NLP Engineer",
    "MLOps Engineer",
    "AI Developer",
    "RAG Engineer",
    "Agentic AI Engineer",
    "Prompt Engineer",
    "AI Scientist",
    "ML Scientist",
    "AI Infrastructure Engineer",
    "ML Infrastructure Engineer",
    "Machine Learning Infrastructure Engineer",
    "AI Platform Engineer",
    "ML Platform Engineer",
    "MLOps",
    "Data Scientist",
    "Deep Learning Engineer",
    "Computer Vision Engineer",
    "AI Architect",
    "ML Architect",
    "AI Consultant",
    "AI Specialist",
    "AI Analyst",
    "LangChain Developer",
    "LLM Developer",
    "Gen AI Developer",
    "AI/ML Engineer",
    "ML/AI Engineer",
    "Software Engineer - AI",
    "Software Engineer - ML",
    "Software Engineer AI",
    "Software Engineer ML",
]

# ---------------------------------------------------------------------------
# Shortened URL domains — These will be resolved to their final destination
# ---------------------------------------------------------------------------
SHORTENED_URL_DOMAINS = [
    "bit.ly",
    "lnkd.in",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "ow.ly",
    "buff.ly",
    "is.gd",
    "rb.gy",
    "cutt.ly",
    "shorturl.at",
]

# Timeout (seconds) for following redirects when resolving a shortened URL.
URL_RESOLVE_TIMEOUT = 5

# ---------------------------------------------------------------------------
# URL classification — shared by the parser and the dashboard
# ---------------------------------------------------------------------------
# Social / generic domains that are never treated as an apply or company link.
EXCLUDE_URL_DOMAINS = [
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com", "medium.com", "github.com",
]

# Applicant-tracking-system domains → human-readable platform name.
ATS_PLATFORMS = {
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "workday.com": "Workday",
    "myworkday.com": "Workday",
    "myworkdayjobs.com": "Workday",
    "ashbyhq.com": "Ashby",
    "smartrecruiters.com": "SmartRecruiters",
    "icims.com": "iCIMS",
    "taleo.net": "Taleo",
    "breezy.hr": "Breezy",
    "recruitee.com": "Recruitee",
    "bamboohr.com": "BambooHR",
    "jazz.co": "JazzHR",
    "aplitrak.com": "Aplitrak",
    "indeed.com": "Indeed",
    "naukri.com": "Naukri",
    "wellfound.com": "Wellfound",
    "instahyre.com": "Instahyre",
    "cutshort.io": "Cutshort",
}
ATS_DOMAINS = list(ATS_PLATFORMS)

# URL path fragments that strongly suggest an application page.
APPLY_URL_PATH_HINTS = [
    "/apply", "/careers", "/jobs", "/job/", "/openings",
    "/vacancies", "/positions", "forms.gle", "docs.google.com/forms",
    "typeform.com", "notion.so",
]

# ---------------------------------------------------------------------------
# Seniority — Titles/keywords to REJECT (too senior)
# ---------------------------------------------------------------------------
SENIOR_TITLE_KEYWORDS = [
    "Senior", "Sr.", "Sr", "Staff", "Principal", "Lead",
    "Architect", "Director", "VP", "Vice President",
    "Head of", "Manager", "CTO", "Chief",
]

# ---------------------------------------------------------------------------
# Hiring Signal Keywords — Must contain at least one to be considered
# ---------------------------------------------------------------------------
HIRING_SIGNALS = [
    "hiring", "looking for", "we're looking", "we are looking",
    "we're seeking", "we are seeking",
    "open position", "open role", "job opening",
    "join our team", "join us", "come join",
    "apply", "apply now", "apply here",
    "DM me", "send your resume", "send your CV", "drop your resume",
    "interested candidates",
    "urgently hiring", "immediate joining",
    "walk-in", "walkin", "walk in",
    "job opportunity", "career opportunity",
    "position available", "role available",
    "vacancy", "vacancies",
    "#hiring", "#jobopening",
]

# ---------------------------------------------------------------------------
# Non-Hiring Rejection Keywords — Strong signals this is NOT a job post
# ---------------------------------------------------------------------------
NON_HIRING_SIGNALS = [
    "conference", "summit", "webinar", "workshop", "meetup",
    "course", "tutorial", "certification",
    "article", "blog post", "read more",
    "congratulations", "congrats", "promoted",
    "anniversary", "work anniversary",
    "launched", "released", "announcing",
    "survey", "poll", "vote",
    "hiring boom", "hiring trends", "job trends", "ecosystem", "revolution",
    "opentowork", "#opentowork", "looking for a new role", "looking for a job",
    "hire me", "my resume", "laid off", "layoff", "seeking a job",
    "seeking new opportunities", "looking for new opportunities",
    "growing fastest", "insights", "market report", "industry news",
]

# ---------------------------------------------------------------------------
# LinkedIn Search URL Template
# ---------------------------------------------------------------------------
# f_TPR=r86400 → Past 24 hours
# f_TPR=r604800 → Past week
# sortBy=date_posted → Most recent first
LINKEDIN_SEARCH_URL_TEMPLATE = (
    "https://www.linkedin.com/search/results/content/"
    "?keywords={keyword}"
    "&sortBy=date_posted"
    "&f_TPR=r{window_seconds}"
)

# Time-window rotation. Frequent runs only look back a short window (most of
# a 48h window is duplicates when you run hourly); once per DEEP_SCAN_EVERY_HOURS
# a run uses the deep window to catch anything the short window missed.
SEARCH_WINDOW_SECONDS = 86_400          # 24h — normal runs
SEARCH_WINDOW_DEEP_SECONDS = 604_800    # 7d  — periodic deep scan
DEEP_SCAN_EVERY_HOURS = 24

# ---------------------------------------------------------------------------
# Scraping Behavior
# ---------------------------------------------------------------------------
# Number of times to scroll down on search results page
SCROLL_COUNT = 4

# Delay range (seconds) between scrolls
SCROLL_DELAY_MIN = 2.0
SCROLL_DELAY_MAX = 5.0

# Delay range (seconds) between keyword searches
SEARCH_DELAY_MIN = 15.0
SEARCH_DELAY_MAX = 35.0

# Maximum posts to extract per keyword search
MAX_POSTS_PER_KEYWORD = 50

# Browser launch timeout (seconds)
BROWSER_TIMEOUT = 60

# Page navigation timeout (milliseconds)
PAGE_TIMEOUT = 30_000

# Per-keyword retry on transient failures (timeouts, empty DOM).
SEARCH_MAX_RETRIES = 3
SEARCH_RETRY_BACKOFF_SECONDS = 20.0   # doubles each attempt

# URL fragments / page text that mean LinkedIn has blocked or challenged us.
BLOCK_URL_MARKERS = ["/checkpoint/", "/authwall", "/uas/", "/login", "/challenge/"]
BLOCK_PAGE_MARKERS = [
    "unusual activity", "security verification", "let's do a quick security check",
    "verify you're a human", "your account has been restricted",
    "we've restricted your account",
]

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Interval in minutes between runs
RUN_INTERVAL_MINUTES = 60

# After LinkedIn blocks/challenges a run, skip this many scheduled intervals
# before trying again, so we don't hammer a flagged account.
BLOCKED_SKIP_INTERVALS = 2

# ---------------------------------------------------------------------------
# Database Maintenance
# ---------------------------------------------------------------------------
# Purge posts older than this many days
POST_RETENTION_DAYS = 90

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------
# Posts are scored 0-100 instead of hard-gated. Anything at or above
# RELEVANCE_THRESHOLD is shown as a hiring post; everything else is stored
# (for dedup and tuning) but hidden by default. The dashboard slider overrides
# the threshold at view time; the "relevance_threshold" DB setting overrides
# it at scrape time.
RELEVANCE_THRESHOLD = 50

# ---------------------------------------------------------------------------
# LLM scoring (optional - needs GEMINI_API_KEY in the environment or .env)
# ---------------------------------------------------------------------------
# Gemini scores each post against this description of what you are looking
# for. Edit it in the dashboard sidebar (stored in the settings table, which
# overrides this default) or change it here. The more specific it is, the
# better the filtering: name the skills you have, the seniority you want and
# the kinds of roles you would turn down.
CANDIDATE_PROFILE = (
    "AI, GenAI, LLM, RAG, MLOps, Machine Learning and Data Science "
    "engineering roles."
)

LLM_MODEL = "gemini-2.5-flash"

# Weights are additive from 0 and clamped to 0-100. A typical good post
# (AI title + hiring phrase + AI skills + target city) lands around 90-100.
# The positives can sum to ~110, so each "deal-breaker" penalty is sized to
# drop even a maxed-out post under the threshold on its own.
SCORE_WEIGHTS = {
    "ai_role_in_title": 35,        # extracted role matches AI_ROLE_KEYWORDS
    "search_keyword_hit": 10,      # the keyword that found the post appears in role/body
    "strong_ai_skill": 25,         # LLM / RAG / LangChain etc. in the body
    "generic_role_no_ai": -15,     # generic engineer title and no AI signal
    "non_ai_role": -60,            # explicit QA / frontend / Java-only title
    "location_match": 10,
    "location_mismatch": -65,      # locations mentioned, none of them ours
    "experience_overlap": 10,
    "experience_too_high": -65,    # minimum years above the user's max
    "has_apply_url": 5,
    "has_email": 5,
    "senior_title": -25,
    "hiring_signal_strong": 20,    # hiring confidence >= 0.6
    "hiring_signal_weak": 10,      # hiring confidence > 0 but < 0.6
    "no_hiring_signal": -60,
    "absolute_reject": -100,
}

# Phrases that scream "not a job post". Matched with word boundaries.
ABSOLUTE_REJECT_PHRASES = [
    "cfbr", "commenting for better reach", "whatsapp community", "join our whatsapp",
    "join my whatsapp", "daily fresher job", "telegram channel", "telegram group",
    "seeking a new role", "looking for a job", "open to work", "i am open to work",
    "hire me", "my resume", "laid off", "layoff", "seeking a job",
    "seeking new opportunities", "looking for new opportunities",
    "please find my resume", "i am looking for", "i'm looking for",
    "i am actively looking", "i'm actively looking", "kindly review my profile",
    "can you solve these", "mcq", "test your fundamentals", "spammers stay away",
]

# A city name followed / preceded by one of these is NOT a job location:
# "Delhi Public School", "IIT Bombay", "Mumbai Indians", "University of Pune".
LOCATION_NEGATIVE_AFTER = [
    "public school", "school", "university", "college", "institute", "institute of",
    "alumni", "indians", "super kings", "capitals", "titans", "royals", "knight riders",
    "police", "metro", "airport", "express", "mirror", "times", "stock exchange",
]
LOCATION_NEGATIVE_BEFORE = [
    "iit", "nit", "iiit", "iim", "bits", "university of", "institute of",
    "college of", "school of", "alumni of", "alumnus of", "studied at", "graduated from",
]

# Phrases that introduce the job title in a post. The role extractor looks
# for a title right after one of these before falling back to whole-text scan.
HIRING_ANCHORS = [
    "hiring for", "hiring a", "hiring an", "we're hiring", "we are hiring", "hiring",
    "looking for a", "looking for an", "looking for", "job title", "job role",
    "role", "position", "title", "opening for", "openings for", "opening",
    "vacancy for", "requirement", "designation", "profile", "urgent requirement",
]

# Titles that are explicitly NOT AI roles even if the body mentions ML.
NON_AI_ROLE_TITLES = [
    "data engineer", "data analyst", "qa engineer", "test engineer", "automation engineer",
    "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
    "devops", "cloud engineer", "system admin", "database administrator",
    "react", "angular", "vue", "java developer", "c# developer", ".net",
    "sales", "marketing", "recruiter", "business analyst", "product manager",
]

# Body keywords that mark a post as AI-relevant even with a generic title.
STRONG_AI_KEYWORDS = [
    "llm", "langchain", "langgraph", "llamaindex", "rag", "generative ai", "genai",
    "gen ai", "prompt engineering", "openai", "machine learning", "vector database",
    "fine-tuning", "fine tuning", "agentic", "ai agents", "transformers",
]

# ---------------------------------------------------------------------------
# Notifications — Telegram (optional)
# ---------------------------------------------------------------------------
# Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable. Only posts
# scoring >= NOTIFY_MIN_SCORE are sent, at most NOTIFY_MAX_PER_RUN per run.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NOTIFY_MIN_SCORE = 70
NOTIFY_MAX_PER_RUN = 15

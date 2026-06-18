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
    "LangGraph"
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

# ---------------------------------------------------------------------------
# Seniority — Titles/keywords to REJECT (too senior)
# ---------------------------------------------------------------------------
SENIOR_TITLE_KEYWORDS = [
    "Senior", "Sr.", "Sr ", "Staff", "Principal", "Lead",
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
    "hiring boom", "growing fastest", "insights", "report", "news",
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
    "&f_TPR=r172800"
)

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

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Interval in minutes between runs
RUN_INTERVAL_MINUTES = 60

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

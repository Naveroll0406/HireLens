# HireLens 🔍

Automated Job Discovery & Monitoring Tool

HireLens is an intelligent, automated LinkedIn monitor built to aggressively discover and filter AI, GenAI, LLM, and RAG engineering opportunities directly from LinkedIn posts. By bypassing standard job boards, it taps into the "hidden job market" where founders and hiring managers post directly to their network.

## 🚀 Key Features

- **Immune to Obfuscation**: Uses advanced Playwright structural traversing to reliably scrape posts even when LinkedIn dynamically scrambles its CSS class names.
- **Smart Deduplication**: Merges overlapping post fragments into pristine, single job opportunities without spamming your dashboard.
- **Rule-Based Filtering**: A manual, lightning-fast heuristic engine that instantly filters out noise using Regex and text matching, ensuring only highly relevant engineering jobs reach your screen.
- **Automated Stealth Scrolling**: Mimics human browsing behavior with randomized delays to extract hundreds of posts continuously without triggering LinkedIn's rate limits.
- **Precision Keyword Targeting**: Isolates searches purely to specialized AI roles (LLM, RAG, GenAI, LangChain), guaranteeing zero generic software engineering spam.
- **Persistent Local Storage**: Embeds a robust SQLite database to retain your run history, avoid duplicates across multiple days, and enable long-term analytics.
- **Session Caching**: Securely saves your LinkedIn login state via Playwright persistent profiles, so you only have to log in once for endless automated scraping.
- **Live Streamlit Dashboard**: Instantly view, sort, and analyze scraped hiring posts with a modern, lightning-fast, and beautiful UI.

## 🛠️ Tech Stack

- **Python**: Core application logic and data processing pipeline.
- **Playwright**: For stealthy, dynamic, and structure-based web scraping that bypasses modern anti-scraping defenses.
- **Streamlit**: Beautiful, interactive front-end dashboard for browsing discovered roles.
- **SQLite3**: Lightweight, persistent local storage for job posts, historical runs, and settings.

## ⚙️ How It Works

1. **Scraping**: The scraper takes your target URL or keywords, logs into LinkedIn, and aggressively scrolls through the feed.
2. **Structural Extraction**: It targets internal React components (`data-testid`, `componentkey`) to securely pull the exact post structures.
3. **Filtering & Deduping**: It identifies true "hiring" signals and filters by your desired experience level and target locations, deduplicating identical posts across multiple runs.
4. **Dashboard Delivery**: The processed and cleaned posts are instantly loaded into your local dashboard with direct `apply` links.

## ⚙️ Configuration & Settings

You can fully customize the behavior of the scraper without touching a single line of code! Just use the **⚙️ Settings** menu in the dashboard sidebar:

- **Scroll Duration (seconds):** Controls exactly how long the scraper spends continuously scrolling down the feed. Increase this number to scrape much deeper into the feed's history.
- **Scheduler Timer (minutes):** Controls how frequently the background scraper automatically wakes up to hunt for new jobs on autopilot.

*Any changes you make in the dashboard are saved permanently to your local SQLite database.*

## 💻 Getting Started

### Prerequisites
- Python 3.10+
- A valid LinkedIn account

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/Naveroll0406/HireLens.git
   cd HireLens
   ```
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

### Usage

HireLens operates using two parallel processes. You can run one or both depending on your needs.

#### 1. The Dashboard (UI)
Run the dashboard directly via Streamlit to view results and manually trigger scrapers:
```bash
streamlit run dashboard.py
```

#### 2. The Autopilot Scheduler (Background Monitor)
To run the scraper on a continuous, fully automated loop (based on your Scheduler Timer setting), run the scheduler script in a separate terminal:
```bash
python scheduler.py
```
*Leave this terminal open, and it will continuously hunt for new jobs in the background!*

---

*Built with ❤️ to uncover the hidden AI job market.*

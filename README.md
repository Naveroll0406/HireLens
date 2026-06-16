# HireLens 🔍

Automated Job Discovery & Monitoring Tool

HireLens is an intelligent, automated LinkedIn monitor built to aggressively discover and filter AI, GenAI, LLM, and RAG engineering opportunities directly from LinkedIn posts. By bypassing standard job boards, it taps into the "hidden job market" where founders and hiring managers post directly to their network.

## 🚀 Key Features

- **Immune to Obfuscation**: Uses advanced Playwright structural traversing to reliably scrape posts even when LinkedIn dynamically scrambles its CSS class names.
- **Smart Deduplication**: Merges overlapping post fragments into pristine, single job opportunities without spamming your dashboard.
- **AI-Powered Filtering**: A manual lightning-fast heuristic engine that instantly filters out noise, ensuring only highly relevant AI engineering jobs reach your screen.
- **Frankenstein-Proof**: Rigorous safeguards that prevent it from mistakenly scraping the webpage wrapper or footer metadata.
- **Live Streamlit Dashboard**: Instantly view, sort, and analyze scraped hiring posts with a modern, fast, and beautiful UI.

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
3. Copy the example environment file and add your LinkedIn credentials (don't worry, these stay completely local!):
   ```bash
   cp .env.example .env
   ```

### Usage
Run the dashboard directly via Streamlit:
```bash
streamlit run dashboard.py
```
From the dashboard, paste a LinkedIn Search URL and hit **🚀 Run Scraper**!

---

*Built with ❤️ to uncover the hidden AI job market.*

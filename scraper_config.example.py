"""
Standalone-scraper config — copy this file to `scraper_config.py` and edit that copy.
`scraper_config.py` is git-ignored so your account lists stay private.
Non-coders can safely tune the lists/numbers below. Logic lives in x_scraper.py.
"""

# --- Accounts whose reply sections we mine (handles, no @) --------------------
CALLERS = [
    # Add the X/Twitter handles you want to mine, e.g.:
    "example_account_1", "example_account_2", "example_account_3",
]

# --- Validated advanced-search queries (Latest tab) ---------------------------
SEARCH_QUERIES = [
    '(fumbled OR "always miss" OR "too late") (solana OR memecoin) -filter:links min_faves:1',
    '("how do you" OR "how do i") (find OR catch) (memecoins OR gems OR runners) early -filter:links',
    '("wish i bought" OR "wish i aped" OR "should have aped") (solana OR memecoin) -filter:links',
    '("keep missing" OR "always too late" OR "never catch") (pump OR runner OR memecoin OR solana) -filter:links',
    '(track OR follow OR copy) (whale OR "smart money" OR insider) wallet (solana OR memecoin) -filter:links',
    'missed pump solana -filter:links',
]

# --- Language patterns: (regex, theme, weight) --------------------------------
# weight feeds the intent score. Higher = stronger buying signal.
LANGUAGE_PATTERNS = [
    (r"\bhow (do|to) (you|i|find|catch)\b.*\b(early|gems|alpha|before)\b", "Wants discovery", 5),
    (r"\b(track|monitor|follow|copy)\b.*\b(whale|wallet|smart money|insider)\b", "Wants whale tracking", 5),
    (r"\b(any|best|recommend).{0,20}(tool|scanner|bot|app)\b", "Wants a tool", 5),
    (r"\bwish i (bought|aped|had)\b", "Missed run / regret", 4),
    (r"\bmissed\b.*\b(pump|run|runner|it|out|entry)\b", "Missed run / FOMO", 4),
    (r"\b(fumbled|sidelined|priced out|keep missing|always miss)\b", "Missed run / FOMO", 4),
    (r"\b(scanner|scanning|vet|screen)\b.*\b(coin|token|memecoin)\b", "Manual-scan fatigue", 4),
    (r"\b(scam|rug|rugged|paid (kol|caller)|shill)\b", "KOL distrust / rug fatigue", 3),
    (r"\bhesitat|paper hand", "Hesitation / conviction", 3),
    (r"\b(new to|just started|getting into)\b.*\b(solana|crypto|trenches|memecoin)\b", "Newcomer / onboarding", 3),
    (r"\btoo late\b", "Missed run / FOMO", 2),
]

# --- Humanized draft reply per theme (personalize before posting) -------------
# "the tool" is a placeholder — swap in your product name / pitch.
REPLY_TEMPLATES = {
    "Wants discovery": "honestly the 'find them early' part is a whole job on its own. i lean on the tool to do the early scanning/research so i'm not digging manually — might be what you're after",
    "Wants whale tracking": "following the right wallets is the real edge but you can't watch them all manually. the tool tracks smart-money wallets in real time, that's what i use",
    "Wants a tool": "if you want something that does the heavy lifting, the tool scans and flags early setups so you're not hunting all day",
    "Missed run / regret": "the 'wish i bought earlier' loop never really ends unless you get earlier signal. that's the only fix i've found",
    "Missed run / FOMO": "getting sidelined on entries is the worst. early alerts is what finally stopped it for me — you actually get a shot instead of hearing about it after",
    "Manual-scan fatigue": "automated for the first pass, manual to confirm. i run tokens through the tool first — catches obvious rugs and flags momentum early",
    "KOL distrust / rug fatigue": "the KOL fatigue is valid. i went data/wallet-based instead of paid callers, nobody getting paid to shill me a bag",
    "Hesitation / conviction": "hesitation kills more gains than bad picks. having wallet data to back a call is what helps me actually pull the trigger",
    "Newcomer / onboarding": "welcome! keep it simple early — a tool that finds plays for you helps you avoid getting rugged your first week",
}

# --- Filters to focus on genuine retail (not influencers or bots) -------------
FILTERS = {
    "follower_min": 25,       # below this = likely bot/throwaway
    "follower_max": 60000,    # above this = influencer/competitor, not a target
    "skip_verified_org": True,  # drop brand/org accounts
    "require_recent_days": 45,  # ignore posts older than this (0 = no limit)
}

# --- Score -> intent bucket cutoffs -------------------------------------------
SCORE_BUCKETS = {"HIGH": 6, "MED": 3}  # >=6 HIGH, >=3 MED, else LOW

# Handles to always drop (callers/competitors/known promoters). Add your own.
EXCLUDE_EXTRA = set()

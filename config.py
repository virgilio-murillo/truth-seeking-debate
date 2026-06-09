MAX_DEPTH = 7
MAX_EXCHANGES = 7
AGENT_SLOTS = 10
POLL_INTERVAL = 5

DEPTH_PRIORITY_WEIGHT = 1000
RESUMED_PARENT_BOOST = 500

RELEVANCE_THRESHOLD = 0.6
RELEVANCE_THRESHOLD_DEEP = 0.8

AGREEMENT_RATIO_THRESHOLD = 0.5

DEFAULT_AGENT = "investigator-child"

# Topic keywords → agent name
AGENT_MAP = {
    "bible-expert": ["bible", "biblical", "scripture", "theology", "church fathers",
                     "patristic", "greek text", "hebrew text", "septuagint", "lxx",
                     "new testament", "old testament", "salvation", "soteriology",
                     "christology", "eschatology", "biblia", "teología", "escritura",
                     "salvación", "griego", "hebreo"],
}

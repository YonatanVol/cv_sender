"""Bilingual keyword sets for the relevance funnel. English uses word-boundary
matching; Hebrew uses prefix/substring matching (so מפתח covers מפתח / מפתחת /
מפתח/ת). Kept as editable data so a future UI can expose them."""

# Role gate (2026-09-14). A title needs a STRONG software signal to be sent
# without review. WEAK signals ("engineer", "פיתוח", "QA") only make it a
# candidate that is held for the human, because on their own they also match
# Configuration Engineer, IT Engineer or "פיתוח ארגוני" (HR).
ROLE_STRONG_EN = [
    "software", "developer", "programmer", "frontend", "front-end", "front end",
    "backend", "back-end", "back end", "full stack", "fullstack", "full-stack",
    "data engineer", "devops", "sre", "sde", "machine learning", "ml engineer",
    "ai engineer", "algorithm", "embedded", "firmware", "qa automation",
    "automation engineer", "test automation", "android", "ios", "mobile developer",
    "web developer", "cloud engineer", "infrastructure engineer",
    "security engineer", "computer vision", "kernel", "cuda",
]
ROLE_STRONG_HE = [
    "תוכנה", "מפתח", "מתכנת", "פולסטאק", "פול סטאק", "פרונטאנד", "פרונט אנד",
    "בקאנד", "בק אנד", "אלגוריתמ", "דבאופס", "אוטומציית בדיקות",
]
ROLE_WEAK_EN = [
    "engineer", "web", "mobile", "automation", "qa", "quality assurance",
    "tester", "data", "implementer", "integration", "technical",
]
# 'אוטומציה' on its own is usually industrial control ("בקרה ואוטומציה"),
# not test automation — weak, so it is held for review rather than sent.
ROLE_WEAK_HE = ["פיתוח", "מהנדס", "בודק", "בדיקות", "מערכות", "מיישם",
                "אוטומציה", "אוטומטי"]

# Software-adjacent work: kept, but always held for review before sending.
BORDERLINE_EN = [
    "it", "crm", "siebel", "sap", "abap", "erp", "salesforce", "priority",
    "configuration", "implementer", "implementation", "manual qa", "manual",
    "support engineer", "system engineer", "systems engineer", "helpdesk",
    "bi developer", "power bi",
]
BORDERLINE_HE = ["מיישם", "תצורה", "הטמעה", "מערכות מידע", "תמיכה טכנית",
                 "בקרה", "בקרת", "חשמל", "מכונות", "תפעול"]

# Not software. Drops a title unless it ALSO carries a strong software signal
# ("Software Engineer, Recruiting Platform" stays).
NON_SOFTWARE_EN = [
    "hr", "human resources", "recruiter", "recruiting", "talent acquisition",
    "sales", "account executive", "account manager", "customer success",
    "customer support", "support specialist", "technician", "transcriber",
    "translator", "designer", "marketing", "finance", "accountant", "legal",
    "safety", "biolog", "microbiolog", "chemist", "nurse", "teacher", "tutor",
    "office manager", "administrative", "operations coordinator", "coordinator",
    "mechanical", "civil engineer", "electrical engineer", "business development",
]
NON_SOFTWARE_HE = [
    "משאבי אנוש", "גיוס", "הדרכה", "פיתוח ארגוני", "רכז", "מכירות", "שיווק",
    "כספים", "חשב", "מזכיר", "שירות לקוחות", "בטיחות", "טכנאי", "נציג",
    "פיתוח עסקי", "מעצב", "תמלול", "מתרגם", "אדמיניסטרציה",
]

# Back-compat for any caller that still reads the old names.
ROLE_EN = ROLE_STRONG_EN + ROLE_WEAK_EN
ROLE_HE = ROLE_STRONG_HE + ROLE_WEAK_HE

JUNIOR_EN = [
    "junior", "jr", "entry level", "entry-level", "new grad", "new-grad",
    "newgrad", "graduate", "intern", "internship", "student", "associate",
    "trainee", "apprentice", "early career", "early-career", "campus",
]
JUNIOR_HE = [
    "ג'וניור", "גוניור", "ג׳וניור", "סטודנט", "מתחיל", "זוטר", "בוגר",
    "התמחות", "מתמחה", "סטאז'", "סטאז", "חונכות",
]

SENIOR_EN = [
    "senior", "sr", "staff", "principal", "lead", "team lead", "tech lead",
    "manager", "director", "head of", "vp", "architect", "expert",
]
SENIOR_HE = [
    "בכיר", "סניור", "מוביל", "ראש צוות", "מנהל", "ארכיטקט", "מומחה",
]

ISRAEL_HINTS_EN = [
    "israel", "tel aviv", "tel-aviv", "tlv", "herzliya", "herzeliya", "haifa",
    "jerusalem", "ramat gan", "ramat-gan", "petah tikva", "petach tikva",
    "petah-tikva", "raanana", "ra'anana", "netanya", "beer sheva", "be'er sheva",
    "rehovot", "yokneam", "caesarea", "kiryat", "kfar saba", "rosh haayin",
    "bnei brak", "hod hasharon", "or yehuda", "rishon", "nes ziona", "modiin",
    "lod", "airport city", "yavne", "givatayim", "holon", "bat yam",
]
ISRAEL_HINTS_HE = [
    "ישראל", "תל אביב", "תל-אביב", "הרצליה", "חיפה", "ירושלים", "רמת גן",
    "פתח תקווה", "פתח תקוה", "רעננה", "נתניה", "באר שבע", "רחובות", "יקנעם",
    "כפר סבא", "ראש העין", "בני ברק", "הוד השרון", "ראשון לציון", "נס ציונה",
    "קיסריה", "מודיעין", "יבנה", "גבעתיים", "חולון", "בת ים", "לוד",
]

REMOTE_HINTS = ["remote", "מרחוק", "היברידי", "hybrid", "work from home", "wfh"]

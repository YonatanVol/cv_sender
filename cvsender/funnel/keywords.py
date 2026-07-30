"""Bilingual keyword sets for the relevance funnel. English uses word-boundary
matching; Hebrew uses prefix/substring matching (so מפתח covers מפתח / מפתחת /
מפתח/ת). Kept as editable data so a future UI can expose them."""

ROLE_EN = [
    "software", "developer", "engineer", "programmer", "frontend", "front-end",
    "front end", "backend", "back-end", "back end", "full stack", "fullstack",
    "full-stack", "web", "mobile", "android", "ios", "data engineer", "devops",
    "qa", "sde", "machine learning", "ml engineer", "algorithm", "embedded",
    "automation",
]
ROLE_HE = [
    "תוכנה", "מפתח", "פיתוח", "מתכנת", "הנדסת תוכנה", "פולסטאק", "פול סטאק",
    "פרונטאנד", "פרונט אנד", "בקאנד", "בק אנד", "בודק", "אלגוריתמ", "אוטומציה",
]

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

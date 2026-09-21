"""The funnel is where v1 died (5,629 -> 11). These lock in the fixes."""
from cvsender.channels.base import Job
from cvsender.funnel.scoring import score_job, min_years_required


def J(title, location="Tel Aviv, Israel", desc="", remote=False):
    return Job(channel="greenhouse", company="acme", external_id="1",
               title=title, location=location, description=desc, remote=remote)


def test_unlabeled_software_role_is_kept():
    # v1 rejected this as 'not clearly junior'. v2 keeps it (neutral).
    v = score_job(J("Software Engineer"), strictness="balanced")
    assert v.keep, v.reason


def test_explicit_senior_is_dropped():
    v = score_job(J("Senior Backend Engineer"))
    # A senior title is a gate now, not a score: keyword bonuses used to
    # outweigh the penalty and let senior roles through.
    assert not v.keep and v.stage == "seniority"


def test_junior_boost():
    assert score_job(J("Junior Software Developer")).keep
    assert score_job(J("Software Engineer, New Grad")).keep


def test_hebrew_titles():
    assert score_job(J("מפתח/ת תוכנה ג'וניור")).keep          # junior dev (HE)
    assert score_job(J("מפתחת Full Stack")).keep               # unlabeled dev (HE)
    assert not score_job(J("מפתח תוכנה בכיר")).keep            # senior (HE)


def test_hebrew_location():
    assert score_job(J("Backend Developer", location="תל אביב")).keep


def test_non_software_rejected():
    v = score_job(J("Account Executive", desc="sales quota"))
    assert not v.keep and v.stage == "role"


def test_role_gate_is_title_based():
    # A non-eng title whose JD mentions software must NOT sneak in.
    v = score_job(J("Public Policy Intern",
                    desc="work with our software engineering teams on policy"))
    assert not v.keep and v.stage == "role"


def test_geography_gate():
    assert not score_job(J("Software Engineer", location="New York")).keep
    assert score_job(J("Software Engineer", location="Remote", remote=True)).keep
    # unknown location is kept for review, not dropped
    assert score_job(J("Software Engineer", location="")).keep


def test_description_years_of_experience():
    assert min_years_required("Requires 5+ years of experience") == 5
    assert min_years_required("2-4 years experience") == 2
    assert min_years_required("no specific number here") is None
    # a senior YoE sinks an otherwise-neutral title
    assert not score_job(J("Software Engineer", desc="7+ years of experience required")).keep
    # 0-2 years lifts it
    assert score_job(J("Software Engineer", desc="0-2 years of experience")).keep


def test_strictness_knob():
    plain = J("Software Engineer")
    assert score_job(plain, strictness="balanced").keep      # neutral kept
    assert not score_job(plain, strictness="strict").keep    # strict needs a junior signal
    assert score_job(J("Senior Engineer"), strictness="loose").keep is False


def test_word_boundary_no_false_intern():
    # 'International' must not match 'intern'
    v = score_job(J("Manager, International Software"), strictness="balanced")
    assert not v.keep   # 'manager' senior wins, not a fake junior from 'intern'


# ---- 2026-09-14: tighter role gate, from the real titles sent that night ----
import pytest

AUTO = [   # clear software roles: may be sent without extra review
    "Junior Software Engineer", "Full Stack Developer", "Full Stack Engineer",
    "Generative AI Engineer", "Founding Engineer - Full-Stack & Infrastructure",
    "Java Software Engineer", "Algorithm Engineer", "QA Automation Engineer",
    "3D Algorithm Developer", "Motion Control - Real Time Embedded Engineer",
    "מפתח/ת תוכנה ג'וניור", "מהנדס אוטומציית בדיקות",
]
REVIEW = [  # software-adjacent: prepare, but hold for the human
    "IT Engineer", "Configuration Engineer- מהנדס\\ת תצורה",
    "Siebel CRM Developer-2789", "Technical Manual QA Engineer",
    "Streaming Platform Engineer", "Junior Systems Implementer (מיישם/ת מערכות)",
    "SAP ABAP Developer", "Manual QA Tester – Digital & Web",
    "מהנדס/ת בקרה ואוטומציה",          # industrial control, not software
    "מהנדס/ת חשמל",
    "Software Engineer, Recruiting Platform",   # software + non-software word
    "Software Sales Specialist",
]
DROP = [    # not software at all
    'רכז/ת הדרכה ופיתוח ארגוני החלפה לחל"ד עם אופציה',
    "Hebrew Transcriber (Freelance)", "Junior Customer Support Specialist",
    "IT Support Technician (Student Position)", "Product Designer, AI Builder",
    "Safety Officer", "Microbiologist & Researcher", "Sales Engineer",
    "HR Business Partner", "מנהל/ת פיתוח עסקי", "Talent Acquisition Specialist",
    "בקרת איכות",                      # quality control, no software signal
]


def _review(v):
    return any(s.startswith("review:") for s in v.signals)


@pytest.mark.parametrize("title", AUTO)
def test_clear_software_roles_auto(title):
    v = score_job(J(title))
    assert v.keep and not _review(v), (title, v.reason, v.signals)


@pytest.mark.parametrize("title", REVIEW)
def test_borderline_roles_are_kept_for_review(title):
    v = score_job(J(title))
    assert v.keep and _review(v), (title, v.reason, v.signals)


@pytest.mark.parametrize("title", DROP)
def test_non_software_roles_dropped(title):
    v = score_job(J(title))
    assert not v.keep and v.stage == "role", (title, v.reason, v.signals)


def test_hebrew_exclusion_needs_word_start():
    # 'מרכז' (center) contains 'רכז' (coordinator) but is not an exclusion
    assert score_job(J("מפתח/ת תוכנה במרכז הפיתוח")).keep


# ---- remote must mean "reachable from Israel" ----

@pytest.mark.parametrize("location,keep", [
    ("Tel Aviv, Israel", True),
    ("TLV, Tel Aviv, Israel", True),
    ("Remote", True),
    ("Remote - Israel", True),
    ("Remote (EMEA)", True),
    ("Remote (US)", False),
    ("US - Remote", False),
    ("San Francisco", False),
    ("New York, NY (HQ)", False),
    ("Singapore", False),
    ("London, UK", False),
])
def test_remote_elsewhere_is_not_remote_for_israel(location, keep):
    v = score_job(J("Software Engineer", location=location), strictness="balanced")
    assert v.keep is keep, (location, v.stage, v.reason)


def test_a_remote_flagged_us_job_is_still_rejected():
    """The board's own 'remote' flag must not override a US-only location."""
    j = J("Backend Engineer", location="Remote (US)", remote=True)
    assert score_job(j).keep is False


@pytest.mark.parametrize("location", ["Seoul, South Korea", "Europe, European Union",
                                      "APAC", "Shanghai, China"])
def test_other_regions_are_not_reachable_either(location):
    assert score_job(J("Software Engineer", location=location)).keep is False


# ---- 2026-09-21: the score is 0-100 and says why ----

def test_score_is_zero_to_one_hundred_with_a_band():
    v = score_job(J("Junior C++ Software Developer",
                    desc="Linux, algorithms, 0-2 years of experience"))
    assert 0 <= v.score <= 100 and v.band in dict((n, 1) for _, n in __import__(
        "cvsender.funnel.scoring", fromlist=["BANDS"]).BANDS)
    assert v.keep and v.score >= 75


def test_every_score_can_be_explained():
    v = score_job(J("Student Software Developer", desc="C, C++, Linux, algorithms"))
    labels = [c.label for c in v.contributions]
    assert any("student" in l.lower() for l in labels)
    assert any("C / C++" == l for l in labels)
    assert all(isinstance(c.points, int) and c.points != 0 for c in v.contributions)
    assert v.score == max(0, min(100, 50 + sum(c.points for c in v.contributions)))
    assert v.explain().startswith(f"{v.score:.0f} ")


def test_a_hard_years_requirement_sinks_a_job_a_preference_does_not():
    hard = score_job(J("Backend Developer",
                       desc="Python. 5+ years of experience required."))
    soft = score_job(J("Backend Developer",
                       desc="Python. 5 years of experience preferred, an advantage."))
    assert hard.keep is False, hard.explain()
    assert soft.keep is True, soft.explain()
    assert soft.score > hard.score + 20


def test_hebrew_soft_requirement_is_read_as_a_preference():
    from cvsender.funnel.scoring import years_are_required
    assert years_are_required("נדרש ניסיון של 5 שנים") is True
    assert years_are_required("ניסיון של 3 שנים - יתרון") is False


def test_skills_cannot_outweigh_seniority():
    """A senior role stuffed with matching keywords must still be rejected."""
    v = score_job(J("Senior Staff Backend Engineer",
                    desc="python java c++ linux embedded networking algorithms sql react docker"))
    assert v.keep is False, v.explain()


def test_strict_means_only_clear_junior_roles():
    assert score_job(J("Software Engineer"), strictness="strict").keep is False
    assert score_job(J("Junior Software Engineer"), strictness="strict").keep is True
    assert score_job(J("Software Engineer"), strictness="balanced").keep is True


@pytest.mark.parametrize("title", [
    "Software Team Leader (C)",      # scored 86 on 2026-09-21 — 'lead' misses 'Leader'
    "Group Leader, Backend",
    "Head of Engineering",
    "Chief Architect",
    "Engineering Manager",
    "מנהל/ת פיתוח",
    "ראש צוות תוכנה",
])
def test_leadership_titles_are_not_junior_roles(title):
    v = score_job(J(title, desc="python c++ linux"))
    assert v.keep is False, v.explain()

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
    assert not v.keep and v.stage == "score"


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

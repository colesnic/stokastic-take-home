#!/usr/bin/env python3
"""Build the Coles Law Firm static site.

Single source of truth for all page content, navigation, and structured
data. Run with `python3 build.py` from inside the coleslawfirm-site/
directory; pages are written in-place alongside this script.
"""
from __future__ import annotations
import json
import os
import urllib.parse
from pathlib import Path
from textwrap import dedent

SITE_URL = "https://www.coleslawfirm.com"
SITE_NAME = "Coles Law Firm"
FIRM_PHONE = "(616) 308-3509"
FIRM_PHONE_TEL = "+16163083509"
FIRM_EMAIL = "jennifer@coleslawfirm.com"
FIRM_TAGLINE = "Serving Michigan for over 20 years"

ROOT = Path(__file__).resolve().parent

# -------- Data ------------------------------------------------------------

# TODO: Replace initial-letter placeholders with real headshots.
#       Jennifer's photo is the highest priority — it appears on the
#       homepage, /about/, /meet-the-team/, /team/jennifer-coles/, and
#       inside several testimonials. Once received, add a `photo` field
#       (relative path under /assets/team/) and update team_card /
#       profile renderers to use <img> when present.
TEAM = [
    {
        "slug": "jennifer-coles",
        "name": "Jennifer Coles",
        "role": "Attorney",
        "initial": "J",
        "short": "Jennifer has been practicing law in Grand Rapids for 20+ years, focusing on estate planning, probate, and elder law.",
        "long": [
            "Jennifer Coles is the founding attorney of Coles Law, PLLC. For more than two decades, she has guided Michigan families through estate planning, probate, trust administration, and elder law matters.",
            "Her practice is grounded in the belief that estate planning should feel less like paperwork and more like a conversation — one where each client's goals, family dynamics, and values lead the way.",
            "Jennifer is known for explaining complex legal concepts in plain English, taking the time to ensure every client understands the documents they sign and the choices they're making.",
        ],
        "credentials": [
            ("Education", "B.A., Accounting — Michigan State University (1990)"),
            ("Law Degree", "J.D. — Maurer School of Law, Indiana University (1993)"),
            ("Experience", "20+ years practicing in Grand Rapids, MI"),
            ("Recognition", "Avvo Client's Choice Award; Distinguished Peer Rated"),
            ("Practice", "Estate Planning, Wills & Trusts, Probate, Elder Law"),
        ],
    },
    {
        "slug": "brian-coles",
        "name": "Brian Coles",
        "role": "Office Administrator",
        "initial": "B",
        "short": "Brian leads firm operations after a career in title industry leadership and a background in finance and organizational psychology.",
        "long": [
            "Brian Coles oversees the day-to-day operations of Coles Law, PLLC, ensuring every client matter is staffed, scheduled, and supported with attention to detail.",
            "Before joining the practice, Brian held several roles at First American Title, most recently as Director of Operations, where he led large multi-state teams.",
            "His combined background in finance and organizational psychology informs the firm's client-first systems and processes.",
        ],
        "credentials": [
            ("Education", "B.A., Industrial & Organizational Psychology — University of Michigan"),
            ("Graduate", "M.S., Finance — Wayne State University"),
            ("Prior Role", "Director of Operations, First American Title"),
        ],
    },
    {
        "slug": "kevin-hansen",
        "name": "Kevin Hansen",
        "role": "Of Counsel Attorney",
        "initial": "K",
        "short": "Kevin brings 20+ years of Grand Rapids legal experience as Of Counsel, supporting clients on estate and trust matters.",
        "long": [
            "Kevin Hansen serves as Of Counsel to Coles Law, PLLC, bringing more than two decades of Grand Rapids legal experience to the firm's estate and trust practice.",
            "He works closely with Jennifer on complex matters and provides additional capacity during high-volume periods, ensuring clients always receive timely, thorough representation.",
        ],
        "credentials": [
            ("Education", "BBA — University of Michigan (1987)"),
            ("Law Degree", "J.D. — Notre Dame Law School (1992)"),
            ("Experience", "20+ years practicing in Grand Rapids, MI"),
        ],
    },
    {
        "slug": "julie-turner",
        "name": "Julie Turner",
        "role": "Client Intake & Bookkeeping",
        "initial": "J",
        "short": "Julie is the welcoming first voice clients hear and the firm's behind-the-scenes accounting backbone.",
        "long": [
            "Julie Turner manages client intake and bookkeeping for Coles Law, PLLC. For most prospective clients, Julie is the first friendly voice they encounter — a role she takes seriously.",
            "Her professional path includes time at the public accounting firm Librand and several years in human resources, giving her a rare combination of financial discipline and people skills.",
        ],
        "credentials": [
            ("Education", "B.S., Business Administration (Accounting) — Central Michigan University"),
            ("Prior Roles", "Public accounting (Librand); HR for multiple firms"),
        ],
    },
]

PRACTICES = [
    {
        "slug": "revocable-living-trust",
        "name": "Revocable Living Trust",
        "icon": "T",
        "tagline": "Secure your estate while retaining full control.",
        "summary": "Secure your estate while retaining full control during your lifetime — flexible planning that adapts as your circumstances change.",
        "pricing_range": "$1,500 – $3,500",
        "pricing_note": "Flat fee depending on complexity, asset count, and whether trust funding is included.",
        "body": [
            "A revocable living trust is one of the most flexible and powerful tools in estate planning. It allows you to retain complete control of your assets during your lifetime while providing a clear, private framework for managing and transferring them when you're no longer able to.",
            "Unlike a will alone, a properly funded revocable trust can help your family avoid the time, cost, and public exposure of probate court — often saving months of delay and significant legal expense.",
        ],
        "benefits": [
            "Avoid probate for assets titled in the trust",
            "Maintain full control and the ability to amend or revoke at any time",
            "Keep your estate's details private (probate is public record)",
            "Plan for incapacity with a successor trustee in place",
            "Coordinate with wills, powers of attorney, and beneficiary designations",
        ],
    },
    {
        "slug": "wills-codicils",
        "name": "Wills & Codicils",
        "icon": "W",
        "tagline": "Make sure your wishes are clearly recorded.",
        "summary": "Create or update your will to reflect your wishes accurately, with codicils to amend existing documents as life evolves.",
        "pricing_range": "$250 – $750",
        "pricing_note": "Flat fee. Simple wills start at the lower end; more involved plans with multiple bequests or guardianship provisions are higher.",
        "body": [
            "Your last will and testament is the foundation of any estate plan. It names guardians for minor children, designates a personal representative for your estate, and directs how your assets should be distributed.",
            "Life changes — marriages, births, deaths, moves, and shifts in financial circumstances all warrant a fresh look at your documents. We help clients prepare new wills and execute codicils (formal amendments) that keep their plans current.",
        ],
        "benefits": [
            "Properly executed wills under Michigan law",
            "Guardianship designations for minor children",
            "Personal representative (executor) appointments",
            "Specific and residuary bequests drafted with clarity",
            "Codicils to update existing wills without rewriting them",
        ],
    },
    {
        "slug": "powers-of-attorney",
        "name": "Powers of Attorney",
        "icon": "A",
        "tagline": "Put trusted decision-makers in place before they're needed.",
        "summary": "Assign someone you trust to act on your behalf for financial and legal decisions when you are unable to do so yourself.",
        "pricing_range": "$150 – $400",
        "pricing_note": "Flat fee per document. Bundled discounts available when prepared alongside a will or trust.",
        "body": [
            "A power of attorney designates a trusted person to act on your behalf for financial, legal, or healthcare matters. Without one in place, your family may need to petition for a court-appointed guardian or conservator — a process that is slow, costly, and public.",
            "We prepare both durable powers of attorney for financial matters and patient advocate designations for healthcare decisions, tailored to your situation and family dynamics.",
        ],
        "benefits": [
            "Durable financial powers of attorney",
            "Patient advocate designations for medical decisions",
            "Clear scope of authority and successor agents",
            "Coordination with your trust and will",
            "Avoid the need for court-supervised guardianship",
        ],
    },
    {
        "slug": "elder-law",
        "name": "Elder Law",
        "icon": "L",
        "tagline": "Counsel for the legal questions aging brings.",
        "summary": "Navigate legal issues unique to aging and elder care — from advance directives to long-term planning.",
        "pricing_range": "Starts at $275/hour",
        "pricing_note": "Most elder law matters are billed hourly. We discuss expected scope and rough budget at the initial consultation.",
        "body": [
            "Elder law sits at the intersection of estate planning, healthcare, and government benefits. Our work in this area focuses on protecting older clients and their families through transitions that often combine emotional, financial, and legal complexity.",
            "We help clients plan ahead for long-term care, evaluate options for skilled nursing or in-home services, and address legal concerns that arise as family roles shift.",
        ],
        "benefits": [
            "Long-term care planning",
            "Advance directives and patient advocate designations",
            "Coordination with financial planners and care providers",
            "Asset protection strategies",
            "Family meetings to align expectations",
        ],
    },
    {
        "slug": "medicaid-medicare",
        "name": "Medicaid & Medicare Planning",
        "icon": "M",
        "tagline": "Plan ahead to protect what you've worked to build.",
        "summary": "Get guidance on Medicaid and Medicare applications and benefits, with planning to help protect what you've worked to build.",
        "pricing_range": "$2,500 – $5,000+",
        "pricing_note": "Flat fee for straightforward applications; crisis planning or asset protection trusts are quoted after an initial review.",
        "body": [
            "Medicaid and Medicare rules are complex, and the cost of getting them wrong can be enormous. We guide clients through the application process and, when appropriate, design planning strategies that help preserve assets while meeting eligibility requirements.",
            "Because Medicaid uses a look-back period for transfers, the earlier we begin planning, the more options remain on the table.",
        ],
        "benefits": [
            "Medicaid eligibility analysis",
            "Spousal protections and the community spouse resource allowance",
            "Asset and income planning strategies",
            "Application preparation and submission support",
            "Coordination with skilled nursing facilities",
        ],
    },
    {
        "slug": "probate-estates",
        "name": "Probate Estates",
        "icon": "P",
        "tagline": "Compassionate guidance through a difficult process.",
        "summary": "Simplify the probate process with expert guidance through every step of administering a loved one's estate.",
        "pricing_range": "$2,500 – $10,000+",
        "pricing_note": "Varies with estate size and complexity. Some matters are billed flat; others by the hour. We discuss the structure that fits before engaging.",
        "body": [
            "Losing a loved one is hard enough without the added weight of legal proceedings. We work alongside personal representatives and families to administer Michigan estates efficiently — from opening the estate to final distribution.",
            "Whether your matter is informal, formal, supervised, or contested, we tailor our involvement to what your family actually needs.",
        ],
        "benefits": [
            "Opening informal or formal probate",
            "Personal representative appointments and bonding",
            "Notice to creditors and claims handling",
            "Inventory, accounting, and final settlement",
            "Will contests and disputed estate matters",
        ],
    },
]

LOCATIONS = [
    {
        "slug": "grand-rapids",
        "name": "Grand Rapids",
        "street": "3501 Lake Eastbrook Blvd. SE",
        "suite": "Suite #140",
        "city": "Grand Rapids",
        "state": "MI",
        "zip": "49546",
        "is_main": True,
        "blurb": "Our flagship office in West Michigan, serving Kent County and the greater Grand Rapids area for over 20 years.",
    },
    {
        "slug": "ann-arbor",
        "name": "Ann Arbor",
        "street": "2723 S. State St.",
        "suite": "Suite #150",
        "city": "Ann Arbor",
        "state": "MI",
        "zip": "48104",
        "is_main": False,
        "blurb": "Convenient Washtenaw County office serving Ann Arbor, Ypsilanti, and the surrounding Southeast Michigan communities.",
    },
    {
        "slug": "east-lansing",
        "name": "East Lansing",
        "street": "120 N. Washington",
        "suite": None,
        "city": "East Lansing",
        "state": "MI",
        "zip": "48933",
        "is_main": False,
        "blurb": "East Lansing office serving Ingham County and Michigan's capital region.",
    },
    {
        "slug": "kalamazoo",
        "name": "Kalamazoo",
        "street": "251 N. Rose St.",
        "suite": "Suite #200",
        "city": "Kalamazoo",
        "state": "MI",
        "zip": "49007",
        "is_main": False,
        "blurb": "Kalamazoo County office serving families across Southwest Michigan.",
    },
    {
        "slug": "battle-creek",
        "name": "Battle Creek",
        "street": "7100 Tower Rd.",
        "suite": None,
        "city": "Battle Creek",
        "state": "MI",
        "zip": "49014",
        "is_main": False,
        "blurb": "Calhoun County office serving Battle Creek, Marshall, and the surrounding region.",
    },
    {
        "slug": "muskegon",
        "name": "Muskegon",
        "street": "800 E. Ellis Rd.",
        "suite": None,
        "city": "Muskegon",
        "state": "MI",
        "zip": "49441",
        "is_main": False,
        "blurb": "Lakeshore office serving Muskegon County and the western Michigan coastline.",
    },
    {
        "slug": "newaygo",
        "name": "Newaygo",
        "street": "1 State Rd.",
        "suite": None,
        "city": "Newaygo",
        "state": "MI",
        "zip": "49337",
        "is_main": False,
        "blurb": "Newaygo County office serving the rural communities north of Grand Rapids.",
    },
]

# Augment each location with SEO data used by the service x city landing
# pages: county, the local probate court name, and a list of nearby
# communities. Stored separately from the LOCATIONS literal to keep that
# literal scannable.
_LOC_SEO = {
    "grand-rapids": {
        "county": "Kent County",
        "probate_court": "Kent County Probate Court",
        "communities": ["Wyoming", "Kentwood", "Caledonia", "Forest Hills", "East Grand Rapids", "Walker", "Rockford", "Cascade", "Ada", "Byron Center", "Hudsonville", "Grandville"],
    },
    "ann-arbor": {
        "county": "Washtenaw County",
        "probate_court": "Washtenaw County Probate Court",
        "communities": ["Ypsilanti", "Saline", "Dexter", "Chelsea", "Pittsfield Township", "Scio Township", "Manchester", "Whitmore Lake"],
    },
    "east-lansing": {
        "county": "Ingham County",
        "probate_court": "Ingham County Probate Court",
        "communities": ["Lansing", "Okemos", "Mason", "Holt", "Williamston", "DeWitt", "Haslett", "Meridian Township", "Grand Ledge"],
    },
    "kalamazoo": {
        "county": "Kalamazoo County",
        "probate_court": "Kalamazoo County Probate Court",
        "communities": ["Portage", "Galesburg", "Comstock", "Parchment", "Oshtemo", "Mattawan", "Vicksburg", "Schoolcraft", "Plainwell"],
    },
    "battle-creek": {
        "county": "Calhoun County",
        "probate_court": "Calhoun County Probate Court",
        "communities": ["Marshall", "Albion", "Springfield", "Bedford", "Augusta", "Pennfield", "Tekonsha", "Homer"],
    },
    "muskegon": {
        "county": "Muskegon County",
        "probate_court": "Muskegon County Probate Court",
        "communities": ["Norton Shores", "North Muskegon", "Whitehall", "Fruitport", "Grand Haven", "Spring Lake", "Roosevelt Park", "Montague"],
    },
    "newaygo": {
        "county": "Newaygo County",
        "probate_court": "Newaygo County Probate Court",
        "communities": ["White Cloud", "Fremont", "Big Rapids", "Grant", "Hesperia", "Bitely", "Croton", "Howard City"],
    },
}
for _loc in LOCATIONS:
    _loc.update(_LOC_SEO[_loc["slug"]])

# Search-keyword services. One page per service x city combination is
# generated for hyper-local SEO; the umbrella "estate-planning-attorney"
# is the broadest term, the others target specific practice areas.
SEO_SERVICES = [
    {
        "slug": "estate-planning-attorney",
        "name": "Estate Planning Attorney",
        "short": "estate planning",
        "practice_slug": None,
        "intro": "Wills, trusts, powers of attorney, and the full picture of how your assets pass to the people you love.",
        "what_we_do": "We help families build complete estate plans — typically a will, a revocable living trust, durable powers of attorney, and a patient advocate designation — coordinated so each piece does its job.",
    },
    {
        "slug": "trust-attorney",
        "name": "Trust Attorney",
        "short": "trusts",
        "practice_slug": "revocable-living-trust",
        "intro": "Revocable living trusts, trust funding, and trust administration designed to avoid probate and keep your estate private.",
        "what_we_do": "We draft revocable living trusts, help fund them properly (the step most plans skip), and administer trusts after a settlor's death.",
    },
    {
        "slug": "wills-attorney",
        "name": "Wills Attorney",
        "short": "wills",
        "practice_slug": "wills-codicils",
        "intro": "Last wills and testaments, codicils, and guardianship designations drafted to Michigan probate code requirements.",
        "what_we_do": "We prepare wills, update existing wills through codicils, and counsel families on choosing personal representatives and guardians.",
    },
    {
        "slug": "probate-attorney",
        "name": "Probate Attorney",
        "short": "probate",
        "practice_slug": "probate-estates",
        "intro": "Compassionate representation of personal representatives and beneficiaries through Michigan's informal and formal probate processes.",
        "what_we_do": "We open estates, manage creditor notice periods, prepare inventories and accountings, and close estates in a timely and orderly way.",
    },
    {
        "slug": "elder-law-attorney",
        "name": "Elder Law Attorney",
        "short": "elder law",
        "practice_slug": "elder-law",
        "intro": "Legal counsel for the questions aging brings — long-term care planning, advance directives, and family transitions.",
        "what_we_do": "We help older clients and their families plan for long-term care, navigate skilled-nursing decisions, and coordinate legal documents with financial planning.",
    },
    {
        "slug": "medicaid-planning-attorney",
        "name": "Medicaid Planning Attorney",
        "short": "Medicaid planning",
        "practice_slug": "medicaid-medicare",
        "intro": "Medicaid eligibility planning under Michigan's rules, including the five-year look-back period and spousal protections.",
        "what_we_do": "We design Medicaid planning strategies that fit your timeline — from advance planning years before need to crisis planning after a sudden diagnosis.",
    },
    {
        "slug": "power-of-attorney-lawyer",
        "name": "Power of Attorney Lawyer",
        "short": "powers of attorney",
        "practice_slug": "powers-of-attorney",
        "intro": "Durable financial powers of attorney and patient advocate designations that put trusted decision-makers in place before they're needed.",
        "what_we_do": "We draft both financial and healthcare powers of attorney, with successor agents and clear scope of authority tailored to your situation.",
    },
]

TESTIMONIALS = [
    {
        "author": "John P.",
        "text": "We've had excellent advice from Jen. She is fantastic at explaining how estates, wills, trusts, and deeds are created, as well as what all the terminology means. She also helped us with advice on other issues that come up, and how to prepare an estate trust so that everything is covered properly. We highly recommend her!",
    },
    {
        "author": "Rebecca K.",
        "text": "Jennifer prepared my estate documents for me. She was very patient in explaining everything to me, and I felt great peace of mind that everything had been covered completely. She was very knowledgeable about MI probate law, and helped me make informed choices regarding my estate. Very calm and pleasant to work with!",
    },
    {
        "author": "Coach M.",
        "text": "My wife and I just finished up our last will and testament and trust documents. We cannot recommend Jennifer and Brian more. They are very thorough and knowledgeable. They made the creation of our family trust a painless process. They even came to us in Ann Arbor.",
    },
    {
        "author": "Sarah F.",
        "text": "We had an excellent experience with Jennifer. Very thorough, professional and detailed. Would highly recommend working with her for any of your legal needs!",
    },
    {
        "author": "Matthew M.",
        "text": "We needed to set up a will and trust. Usually this is arduous and boring. Coles Law made the process easy, understandable, and even enjoyable. I would definitely recommend their services!",
    },
    {
        "author": "Verified Google Review",
        "text": "Getting an estate plan was easier than I thought. I should have done this years ago! Excellent attorney. I met with Jennifer Coles to get a will, power of attorney and patient advocate made. She discussed my options and explained how every document worked. It was a smooth process from start to finish.",
    },
]

BLOG_POSTS = [
    {
        "slug": "do-i-need-a-will-or-a-trust",
        "title": "Do I Need a Will, a Trust, or Both?",
        "date": "2026-04-12",
        "date_display": "April 12, 2026",
        "author": "Jennifer Coles",
        "excerpt": "One of the questions we hear most often. The honest answer: most Michigan families benefit from both, but the right balance depends on your goals.",
        "body": [
            "It's the question that brings most people to our office for the first time: do I need a will, a trust, or both? Like most legal questions, the honest answer is &mdash; it depends. But the framework for deciding is straightforward.",
            "A <strong>will</strong> is a written instruction set that takes effect at your death. It names guardians for minor children, designates the person who will administer your estate (your personal representative), and directs how your assets should be distributed. Wills are familiar, flexible, and relatively inexpensive to prepare.",
            "A <strong>revocable living trust</strong> is more like a container. You move your assets into the trust during your lifetime, keep complete control of them, and name a successor trustee to take over if you become incapacitated or pass away. Properly funded trusts avoid probate entirely.",
            "<h2>When a will alone is enough</h2>",
            "If your estate is modest, your beneficiaries are clear, and you don't mind your family going through probate, a well-drafted will may be sufficient. It's simple, low-cost, and easy to update.",
            "<h2>When a trust is worth the investment</h2>",
            "Trusts make the most sense when you want to: avoid probate (which in Michigan typically takes 6&ndash;12 months), maintain privacy (probate is public record), plan for incapacity, manage assets across generations, or coordinate complex family or business arrangements.",
            "<h2>Most plans use both</h2>",
            "The most common approach is a revocable living trust paired with a <em>pour-over will</em> that catches any assets you forgot to title in the trust. Together with powers of attorney and a patient advocate designation, this is a complete plan that covers the major scenarios.",
            "<h2>Talk it through with us</h2>",
            "Estate planning isn't one-size-fits-all. The right plan depends on your family, your assets, and what you want your legacy to look like. <a href=\"../../contact/\">Schedule a free consultation</a> and we'll help you think it through.",
        ],
    },
    {
        "slug": "michigan-probate-timeline",
        "title": "How Long Does Probate Take in Michigan?",
        "date": "2026-03-08",
        "date_display": "March 8, 2026",
        "author": "Jennifer Coles",
        "excerpt": "Even the most straightforward Michigan probate estate takes months to close. Here's what to expect, and where most delays come from.",
        "body": [
            "Probate is the court-supervised process of administering a deceased person's estate. In Michigan, even the simplest probate matters take time &mdash; usually somewhere between six months and a year. Here's a realistic timeline.",
            "<h2>Months 1&ndash;2: Opening the estate</h2>",
            "After the death, the personal representative named in the will (or, if there's no will, a family member) files a petition with the probate court. The court issues Letters of Authority, which give the personal representative legal power to act on behalf of the estate.",
            "<h2>Months 2&ndash;6: Notice to creditors and asset inventory</h2>",
            "Michigan law requires a four-month notice period during which creditors can file claims against the estate. During this same window, the personal representative inventories the estate's assets, notifies beneficiaries, and begins managing whatever needs managing &mdash; insurance, mortgages, tax filings, and so on.",
            "<h2>Months 6&ndash;9: Resolving claims and preparing for distribution</h2>",
            "Once the creditor period closes, the personal representative pays valid claims, resolves disputes, and prepares a final accounting. If real estate needs to be sold, that often happens during this phase.",
            "<h2>Months 9&ndash;12: Final accounting and closing</h2>",
            "The personal representative files a final accounting with the court, distributes the remaining assets to beneficiaries, and petitions to close the estate.",
            "<h2>What makes it longer</h2>",
            "Common delays include: contested wills, unusual assets (closely-held businesses, real estate in multiple states), tax issues requiring an estate tax return, missing or hard-to-find beneficiaries, and disputes among heirs.",
            "<h2>How to make it easier on your family</h2>",
            "The single best way to spare your family from probate is to do estate planning while you're still well. A properly funded revocable living trust can move most or all of your assets outside the probate process entirely. <a href=\"../../practice-areas/revocable-living-trust/\">Read more about revocable living trusts &rarr;</a>",
        ],
    },
    {
        "slug": "medicaid-five-year-lookback",
        "title": "Michigan Medicaid's Five-Year Look-Back, Explained",
        "date": "2026-02-20",
        "date_display": "February 20, 2026",
        "author": "Jennifer Coles",
        "excerpt": "If you're thinking about Medicaid for long-term care, the five-year look-back is the single most important rule to understand &mdash; and it's why early planning matters so much.",
        "body": [
            "Long-term care is one of the single largest financial risks most families face. A year in a Michigan skilled nursing facility can run $100,000 or more, and Medicare doesn't cover it once the short-term rehabilitation window closes.",
            "Medicaid does cover long-term care, but qualifying for it requires meeting strict income and asset limits. That's where many families run into the <strong>five-year look-back period</strong>.",
            "<h2>What the look-back is</h2>",
            "When you apply for Medicaid long-term care benefits in Michigan, the state reviews your financial transactions for the prior 60 months &mdash; that's the look-back period. Transfers of assets made during this window for less than fair market value can trigger a penalty period during which you're ineligible for benefits.",
            "<h2>Why this matters even if you're healthy now</h2>",
            "Many people assume they'll figure out Medicaid planning if and when they need long-term care. But by then, the look-back rule may have eliminated the most useful strategies. The sooner you plan, the more options stay open.",
            "<h2>What works</h2>",
            "Common approaches include: setting up irrevocable trusts that protect assets while preserving Medicaid eligibility, restructuring asset ownership between spouses to take advantage of community spouse protections, and converting countable assets into exempt assets where appropriate.",
            "<h2>What doesn't work</h2>",
            "Last-minute transfers to children, fake \"loans,\" or simple gifting away of assets within the look-back window will almost always trigger penalties. The state has seen all of it before.",
            "<h2>Start the conversation early</h2>",
            "If long-term care planning is on your mind &mdash; for yourself or for an aging parent &mdash; the best time to talk to an attorney is before there's a crisis. <a href=\"../../practice-areas/medicaid-medicare/\">Read more about our Medicaid planning practice &rarr;</a>",
        ],
    },
    {
        "slug": "powers-of-attorney-vs-guardianship",
        "title": "Powers of Attorney vs. Guardianship: Why the Difference Matters",
        "date": "2026-01-15",
        "date_display": "January 15, 2026",
        "author": "Jennifer Coles",
        "excerpt": "Both tools allow someone else to make decisions on your behalf. But one you choose proactively &mdash; and the other a court chooses for you.",
        "body": [
            "If someone becomes unable to manage their own affairs &mdash; from a stroke, dementia, an accident, or another cause &mdash; someone else has to step in. The legal mechanism for that step-in is either a <strong>power of attorney</strong> that the person established in advance, or a <strong>court-appointed guardian or conservator</strong> if they didn't.",
            "The difference between the two paths is enormous, and it's why every adult should have powers of attorney in place.",
            "<h2>Powers of attorney: you choose, in advance</h2>",
            "A durable power of attorney lets you name a person (your \"agent\") to make financial decisions for you if you can't. A patient advocate designation does the same for healthcare decisions. You choose who. You define the scope. You can revoke or update at any time while you're competent.",
            "<h2>Guardianship: the court chooses, after the fact</h2>",
            "Without powers of attorney, when capacity is lost, the family has to petition the probate court for a guardian (for personal decisions) or a conservator (for financial matters). The court holds hearings, may appoint a guardian ad litem to investigate, and decides who is appointed &mdash; which may or may not be the family member you would have chosen.",
            "<h2>The practical differences</h2>",
            "Guardianship is <em>slow</em> (often months from filing to appointment), <em>expensive</em> (court filings, attorney fees, sometimes a bond), <em>public</em> (everything goes on the court record), and <em>ongoing</em> (annual accountings, court reporting requirements). Powers of attorney avoid all of that.",
            "<h2>What to put in place</h2>",
            "A complete plan typically includes: a durable financial power of attorney, a patient advocate designation, HIPAA authorizations, and clear successor designations in case your first-choice agent is unavailable.",
            "<h2>Get them done</h2>",
            "Powers of attorney are inexpensive to prepare and they expire only on your death (or when you revoke them). If you don't have them in place, this is the single highest-leverage estate planning step you can take today. <a href=\"../../practice-areas/powers-of-attorney/\">Read more about powers of attorney &rarr;</a>",
        ],
    },
]

TRUST_BADGES = [
    {"slug": "avvo", "label": "Avvo", "sub": "Client's Choice 2024", "shape": "circle"},
    {"slug": "super-lawyers", "label": "Super Lawyers", "sub": "Rising Star", "shape": "shield"},
    {"slug": "state-bar-mi", "label": "State Bar", "sub": "of Michigan, Member", "shape": "circle"},
    {"slug": "martindale", "label": "Martindale-Hubbell", "sub": "AV Preeminent", "shape": "shield"},
    {"slug": "bbb", "label": "BBB", "sub": "Accredited Business A+", "shape": "circle"},
]

FAQS = [
    {
        "q": "Do I really need an estate plan if I don't have a lot of assets?",
        "a": "Yes. Estate planning isn't only about wealth. It's about naming guardians for minor children, appointing decision-makers if you become incapacitated, and sparing your family the cost and delay of probate court. Even modest estates benefit from clear documents.",
    },
    {
        "q": "What's the difference between a will and a trust?",
        "a": "A will takes effect at death and typically goes through probate court. A revocable living trust takes effect immediately, can manage your assets if you're incapacitated, and — if properly funded — allows your estate to bypass probate entirely. Most plans use both.",
    },
    {
        "q": "How long does probate take in Michigan?",
        "a": "Even straightforward Michigan probate estates typically take six months to a year, because the law requires notice to creditors and a waiting period for claims. Contested or complex estates can take significantly longer.",
    },
    {
        "q": "How much does it cost to create an estate plan?",
        "a": "Fees depend on the complexity of your plan, the number of documents needed, and whether trust funding is involved. We discuss fees clearly at your initial consultation so you can make an informed decision before engaging us.",
    },
    {
        "q": "What is Medicaid's 'look-back period' and why does it matter?",
        "a": "When you apply for Medicaid long-term care benefits, the state reviews your financial transactions from the prior five years. Transfers made during that window can delay your eligibility. Planning ahead — ideally years in advance — expands your options significantly.",
    },
    {
        "q": "Do you offer free consultations?",
        "a": "Yes. We offer a complimentary initial consultation to discuss your situation and determine whether our firm is the right fit. Reach out by phone or through our contact form to schedule.",
    },
    {
        "q": "Can we meet virtually or do we need to come to an office?",
        "a": "Both. We have seven offices across Michigan and also offer secure video consultations. For some clients (particularly those with mobility challenges), we can arrange in-home visits as well.",
    },
    {
        "q": "What should I bring to my first meeting?",
        "a": "Bring any existing estate planning documents, a general list of your assets and liabilities, and the names of people you'd like to designate as personal representatives, trustees, guardians, or powers of attorney. We'll guide you through the rest.",
    },
]

# -------- Helpers ---------------------------------------------------------

def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def url(path: str) -> str:
    """Return absolute URL for sitemap and JSON-LD."""
    if not path.startswith("/"):
        path = "/" + path
    return SITE_URL + path

def rel(from_depth: int, to: str) -> str:
    """Build a relative link from a page at given directory depth.

    depth = number of directory levels below site root. For the home page
    (index.html at root) depth = 0. For /about/index.html depth = 1, etc.
    """
    to = to.lstrip("/")
    return ("../" * from_depth) + to

def head(title: str, description: str, canonical_path: str, depth: int, extra_schema: list | None = None) -> str:
    """Render <head> common to all pages, with title, meta, OG, JSON-LD."""
    schemas = [organization_schema()] + (extra_schema or [])
    schema_blob = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, indent=2)}</script>'
        for s in schemas
    )
    return dedent(f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>{esc(title)}</title>
          <meta name="description" content="{esc(description)}" />
          <link rel="canonical" href="{url(canonical_path)}" />
          <meta property="og:type" content="website" />
          <meta property="og:url" content="{url(canonical_path)}" />
          <meta property="og:title" content="{esc(title)}" />
          <meta property="og:description" content="{esc(description)}" />
          <meta property="og:image" content="{SITE_URL}/assets/og-image.svg" />
          <meta property="og:site_name" content="{SITE_NAME}" />
          <meta name="twitter:card" content="summary_large_image" />
          <meta name="twitter:title" content="{esc(title)}" />
          <meta name="twitter:description" content="{esc(description)}" />
          <meta name="twitter:image" content="{SITE_URL}/assets/og-image.svg" />
          <link rel="icon" type="image/svg+xml" href="{rel(depth, 'assets/favicon.svg')}" />
          <link rel="preconnect" href="https://fonts.googleapis.com">
          <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
          <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
          <link rel="stylesheet" href="{rel(depth, 'assets/styles.css')}">
          {schema_blob}
        </head>
        """).rstrip()

def site_header(active: str, depth: int) -> str:
    """Top nav. `active` is one of: home, about, team, practice, locations, contact, faq, blog."""
    items = [
        ("about", "About", "about/"),
        ("team", "Our Team", "meet-the-team/"),
        ("practice", "Practice Areas", "practice-areas/"),
        ("locations", "Locations", "locations/"),
        ("expect", "What to Expect", "what-to-expect/"),
        ("faq", "FAQ", "faq/"),
    ]
    li = []
    for key, label, path in items:
        aria = ' aria-current="page"' if key == active else ""
        li.append(f'<li><a href="{rel(depth, path)}"{aria}>{label}</a></li>')
    li.append(f'<li><a class="cta" href="{rel(depth, "contact/")}">Schedule Consultation</a></li>')
    return dedent(f"""\
        <a class="skip-link" href="#main">Skip to content</a>
        <header class="site">
          <div class="container nav">
            <a href="{rel(depth, '')}" class="brand" aria-label="Coles Law Firm home">
              <div class="brand-mark" aria-hidden="true">C</div>
              <div>
                <div class="brand-name">Coles Law Firm</div>
                <div class="brand-sub">Estate Planning &middot; Probate</div>
              </div>
            </a>
            <button class="nav-toggle" aria-label="Toggle menu" onclick="document.querySelector('nav.primary').classList.toggle('open')">
              <span></span><span></span><span></span>
            </button>
            <nav class="primary" aria-label="Primary">
              <ul>
                {chr(10).join('                ' + x for x in li).lstrip()}
              </ul>
            </nav>
          </div>
        </header>
        """).rstrip()

def site_footer(depth: int) -> str:
    practice_links = "\n".join(
        f'              <li><a href="{rel(depth, "practice-areas/" + p["slug"] + "/")}">{p["name"]}</a></li>'
        for p in PRACTICES
    )
    location_links = "\n".join(
        f'              <li><a href="{rel(depth, "locations/" + loc["slug"] + "/")}">{loc["name"]}</a></li>'
        for loc in LOCATIONS
    )
    return dedent(f"""\
        <footer class="site">
          <div class="container">
            <div class="footer-grid">
              <div class="footer-brand">
                <div class="brand" style="margin-bottom: 18px;">
                  <div class="brand-mark" aria-hidden="true">C</div>
                  <div>
                    <div class="brand-name">Coles Law Firm</div>
                    <div class="brand-sub">Estate Planning &middot; Probate</div>
                  </div>
                </div>
                <p>Serving Michigan families with thoughtful estate planning, probate, and elder law counsel for over two decades.</p>
              </div>
              <div>
                <h5>Practice</h5>
                <ul>
        {practice_links}
                </ul>
              </div>
              <div>
                <h5>Offices</h5>
                <ul>
        {location_links}
                </ul>
              </div>
              <div>
                <h5>Contact</h5>
                <ul>
                  <li><a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a></li>
                  <li><a href="mailto:{FIRM_EMAIL}">{FIRM_EMAIL}</a></li>
                  <li>M&ndash;F, 9 AM &ndash; 5 PM</li>
                  <li><a href="{rel(depth, 'contact/')}">Schedule Consultation</a></li>
                </ul>
              </div>
            </div>
            <div class="footer-bottom">
              <div>&copy; 2026 Coles Law Firm, PLLC. All rights reserved.</div>
              <div>Attorney advertising. Prior results do not guarantee a similar outcome.</div>
            </div>
          </div>
        </footer>
        {render_lead_magnet(depth, inline=False)}
        {render_sticky_call_bar(depth)}
        """).rstrip()

def breadcrumbs(depth: int, items: list[tuple[str, str | None]]) -> tuple[str, dict]:
    """Render breadcrumbs HTML and matching BreadcrumbList JSON-LD.

    items: list of (label, href_or_None). The last item should be the
    current page (href_or_None = None).
    """
    lis = []
    list_items = []
    for i, (label, href) in enumerate(items):
        if href is None:
            lis.append(f'<li aria-current="page">{label}</li>')
        else:
            lis.append(f'<li><a href="{rel(depth, href)}">{label}</a></li>')
        list_items.append({
            "@type": "ListItem",
            "position": i + 1,
            "name": label,
            "item": url(href) if href else None,
        })
    # Strip 'item' from last (current page)
    if list_items:
        list_items[-1].pop("item", None)
    schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": list_items,
    }
    html = (
        '<nav class="crumbs" aria-label="Breadcrumb"><div class="container">'
        '<ol>' + "".join(lis) + '</ol></div></nav>'
    )
    return html, schema

# -------- JSON-LD schemas -------------------------------------------------

def organization_schema() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "LegalService",
        "name": SITE_NAME,
        "legalName": "Coles Law, PLLC",
        "url": SITE_URL,
        "telephone": FIRM_PHONE,
        "email": FIRM_EMAIL,
        "image": SITE_URL + "/assets/og-image.svg",
        "logo": SITE_URL + "/assets/og-image.svg",
        "description": "Michigan estate planning, wills, trusts, probate, and elder law attorneys serving clients for over 20 years.",
        "areaServed": {"@type": "State", "name": "Michigan"},
        "address": [
            {
                "@type": "PostalAddress",
                "streetAddress": main_office()["street"] + (
                    ", " + main_office()["suite"] if main_office()["suite"] else ""
                ),
                "addressLocality": main_office()["city"],
                "addressRegion": main_office()["state"],
                "postalCode": main_office()["zip"],
                "addressCountry": "US",
            }
        ],
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "09:00", "closes": "17:00",
        }],
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "5.0",
            "reviewCount": str(len(TESTIMONIALS)),
            "bestRating": "5",
            "worstRating": "1",
        },
        "priceRange": "$$",
        "sameAs": [],
    }

def location_schema(loc: dict) -> dict:
    street = loc["street"] + (", " + loc["suite"] if loc["suite"] else "")
    return {
        "@context": "https://schema.org",
        "@type": "Attorney",
        "name": f"{SITE_NAME} — {loc['name']}",
        "parentOrganization": {"@type": "LegalService", "name": SITE_NAME, "url": SITE_URL},
        "url": url(f"/locations/{loc['slug']}/"),
        "telephone": FIRM_PHONE,
        "email": FIRM_EMAIL,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": street,
            "addressLocality": loc["city"],
            "addressRegion": loc["state"],
            "postalCode": loc["zip"],
            "addressCountry": "US",
        },
        "areaServed": {"@type": "City", "name": loc["city"]},
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "09:00", "closes": "17:00",
        }],
    }

def person_schema(p: dict) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": p["name"],
        "jobTitle": p["role"],
        "worksFor": {"@type": "LegalService", "name": SITE_NAME, "url": SITE_URL},
        "url": url(f"/team/{p['slug']}/"),
        "description": p["short"],
    }

def service_schema(s: dict) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": s["name"],
        "serviceType": s["name"],
        "provider": {"@type": "LegalService", "name": SITE_NAME, "url": SITE_URL},
        "description": s["summary"],
        "areaServed": {"@type": "State", "name": "Michigan"},
        "url": url(f"/practice-areas/{s['slug']}/"),
    }

def faq_schema(faqs: list) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q["q"],
                "acceptedAnswer": {"@type": "Answer", "text": q["a"]},
            } for q in faqs
        ],
    }

def blog_post_schema(post: dict) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "datePublished": post["date"],
        "dateModified": post["date"],
        "author": {"@type": "Person", "name": post["author"]},
        "publisher": {
            "@type": "LegalService",
            "name": SITE_NAME,
            "logo": {"@type": "ImageObject", "url": SITE_URL + "/assets/og-image.svg"},
        },
        "url": url(f"/blog/{post['slug']}/"),
        "description": post["excerpt"],
        "image": SITE_URL + "/assets/og-image.svg",
    }

def review_schemas(reviews: list) -> list[dict]:
    return [{
        "@context": "https://schema.org",
        "@type": "Review",
        "itemReviewed": {"@type": "LegalService", "name": SITE_NAME, "url": SITE_URL},
        "author": {"@type": "Person", "name": r["author"]},
        "reviewBody": r["text"],
        "reviewRating": {"@type": "Rating", "ratingValue": "5", "bestRating": "5"},
    } for r in reviews]

def main_office() -> dict:
    return next(loc for loc in LOCATIONS if loc.get("is_main"))

# -------- Component renderers ---------------------------------------------

def render_practice_grid(depth: int, with_cta: bool = True) -> str:
    cards = []
    for p in PRACTICES:
        cards.append(dedent(f"""\
            <article class="practice-card">
              <div class="practice-icon" aria-hidden="true">{p['icon']}</div>
              <h3>{p['name']}</h3>
              <p>{p['summary']}</p>
              <a class="more" href="{rel(depth, 'practice-areas/' + p['slug'] + '/')}">Learn more &rarr;</a>
            </article>
            """).rstrip())
    if with_cta:
        cards.append(dedent(f"""\
            <article class="practice-card practice-cta-card">
              <div class="practice-icon" aria-hidden="true">?</div>
              <h3>Not sure where to begin?</h3>
              <p>Most clients aren't &mdash; that's what we're here for. Schedule a free consultation and we'll help you map out the right starting point.</p>
              <a class="more" href="{rel(depth, 'contact/')}">Get in touch &rarr;</a>
            </article>
            """).rstrip())
    return '<div class="practice-grid">\n' + "\n".join(cards) + '\n</div>'

def render_team_grid(depth: int) -> str:
    cards = []
    for t in TEAM:
        cards.append(dedent(f"""\
            <article class="team-card">
              <div class="team-photo" aria-hidden="true"><span class="team-initial">{t['initial']}</span></div>
              <h3>{t['name']}</h3>
              <div class="team-role">{t['role']}</div>
              <p class="team-bio">{t['short']}</p>
              <a class="team-link" href="{rel(depth, 'team/' + t['slug'] + '/')}">Read bio &rarr;</a>
            </article>
            """).rstrip())
    return '<div class="team-grid">\n' + "\n".join(cards) + '\n</div>'

def render_locations_grid(depth: int) -> str:
    cards = []
    for loc in LOCATIONS:
        suite = f"<br>{loc['suite']}" if loc['suite'] else ""
        cards.append(dedent(f"""\
            <article class="location-card">
              <h4>{loc['name']}</h4>
              <div class="city-rule"></div>
              <address>
                {loc['street']}{suite}<br>
                {loc['city']}, {loc['state']} {loc['zip']}
              </address>
              <div class="loc-meta">
                <div><strong>Phone:</strong> {FIRM_PHONE}</div>
                <div><strong>Hours:</strong> M&ndash;F, 9 AM &ndash; 5 PM</div>
              </div>
              <a class="loc-link" href="{rel(depth, 'locations/' + loc['slug'] + '/')}">Office details &rarr;</a>
            </article>
            """).rstrip())
    cards.append(dedent(f"""\
        <article class="location-card location-statewide">
          <h4>Statewide</h4>
          <div class="city-rule"></div>
          <p>Virtual consultations available throughout Michigan, with in-home visits arranged on request.</p>
          <a class="loc-link" href="{rel(depth, 'contact/')}">Schedule a meeting &rarr;</a>
        </article>
        """).rstrip())
    return '<div class="locations-grid">\n' + "\n".join(cards) + '\n</div>'

def render_trust_badges(eyebrow: str = "Recognized By") -> str:
    badges = []
    for b in TRUST_BADGES:
        if b["shape"] == "circle":
            svg = (
                '<svg viewBox="0 0 100 100" aria-hidden="true">'
                '<circle cx="50" cy="50" r="46" fill="none" stroke="#b58a3a" stroke-width="2"/>'
                '<circle cx="50" cy="50" r="40" fill="none" stroke="#b58a3a" stroke-width="0.5"/>'
                f'<text x="50" y="42" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="14" font-weight="700" fill="#0f2742">{b["label"]}</text>'
                f'<text x="50" y="62" text-anchor="middle" font-family="Inter, sans-serif" font-size="6" letter-spacing="0.5" fill="#0f2742">{b["sub"].upper()}</text>'
                '</svg>'
            )
        else:  # shield
            svg = (
                '<svg viewBox="0 0 100 100" aria-hidden="true">'
                '<path d="M50 4 L92 18 L92 54 Q92 80 50 96 Q8 80 8 54 L8 18 Z" fill="none" stroke="#b58a3a" stroke-width="2"/>'
                '<path d="M50 10 L86 22 L86 54 Q86 76 50 90 Q14 76 14 54 L14 22 Z" fill="none" stroke="#b58a3a" stroke-width="0.5"/>'
                f'<text x="50" y="46" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="11" font-weight="700" fill="#0f2742">{b["label"]}</text>'
                f'<text x="50" y="62" text-anchor="middle" font-family="Inter, sans-serif" font-size="6" letter-spacing="0.5" fill="#0f2742">{b["sub"].upper()}</text>'
                '</svg>'
            )
        badges.append(f'<div class="trust-badge" title="{esc(b["label"] + " — " + b["sub"])}">{svg}</div>')
    badges_html = "\n          ".join(badges)
    return dedent(f"""\
        <section class="trust-band">
          <div class="container">
            <div class="trust-eyebrow">{eyebrow}</div>
            <div class="trust-badges">
          {badges_html}
            </div>
          </div>
        </section>""")

def render_lead_magnet(depth: int, inline: bool = True) -> str:
    """Subtle, non-pushy lead magnet card. Dismissible if non-inline (banner)."""
    href = rel(depth, "resources/estate-planning-checklist/")
    if inline:
        return dedent(f"""\
            <aside class="lead-magnet" aria-label="Free estate planning resource">
              <div class="lm-mark" aria-hidden="true">&#9776;</div>
              <div class="lm-body">
                <div class="lm-title">A short Michigan estate-planning checklist</div>
                <p>Plain-English. Three pages. The things most families forget, and a few questions to answer before your first meeting. Free to read or download &mdash; no email required.</p>
                <a class="lm-link" href="{href}">Read or download the checklist &rarr;</a>
              </div>
            </aside>""")
    # dismissible bottom banner version
    return dedent(f"""\
        <div id="lead-magnet-banner" class="lead-banner" role="complementary" aria-label="Free resource">
          <button class="lm-close" type="button" aria-label="Dismiss" onclick="this.parentNode.style.display='none'; try{{localStorage.setItem('lm-dismissed','1');}}catch(e){{}}">&times;</button>
          <div class="lm-banner-inner">
            <div>
              <div class="lm-title">A short Michigan estate-planning checklist</div>
              <p>Three pages, plain English, no email required.</p>
            </div>
            <a class="lm-link" href="{href}">Open the checklist &rarr;</a>
          </div>
        </div>
        <script>
          try {{ if (localStorage.getItem('lm-dismissed')) {{
            document.getElementById('lead-magnet-banner').style.display='none';
          }} }} catch(e) {{}}
        </script>""")

def render_sticky_call_bar(depth: int) -> str:
    return dedent(f"""\
        <a class="mobile-call-bar" href="tel:{FIRM_PHONE_TEL}" aria-label="Call Coles Law Firm">
          <span class="mcb-icon" aria-hidden="true">&#9742;</span>
          <span class="mcb-text">Tap to call &mdash; <strong>{FIRM_PHONE}</strong></span>
        </a>""")

CALENDLY_URL = "https://calendly.com/coleslawfirm/new-meeting"

def render_calendly(depth: int) -> str:
    """Inline Calendly scheduling widget.

    Uses Calendly's public inline embed — no API key required. To
    change which event type is shown, update CALENDLY_URL above to
    the new public scheduling URL from the firm's Calendly account.
    """
    return dedent(f"""\
        <div class="calendly-wrapper">
          <div class="calendly-inline-widget"
               data-url="{CALENDLY_URL}?hide_event_type_details=0&hide_gdpr_banner=1&primary_color=0f2742"
               style="min-width:320px;height:760px;"></div>
          <script type="text/javascript" src="https://assets.calendly.com/assets/external/widget.js" async></script>
          <noscript>
            <p style="text-align: center; padding: 24px; background: var(--cream); border: 1px solid var(--rule);">
              Online scheduling requires JavaScript. To book a free consultation, please
              <a href="tel:{FIRM_PHONE_TEL}">call {FIRM_PHONE}</a> or
              email <a href="mailto:{FIRM_EMAIL}">{FIRM_EMAIL}</a>.
            </p>
          </noscript>
        </div>""")

def render_testimonials(limit: int | None = None) -> str:
    items = TESTIMONIALS if limit is None else TESTIMONIALS[:limit]
    cards = []
    for t in items:
        cards.append(dedent(f"""\
            <figure class="testimonial">
              <div class="stars" aria-label="5 out of 5 stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
              <blockquote><p>{t['text']}</p></blockquote>
              <figcaption><cite>&mdash; {t['author']}</cite></figcaption>
            </figure>
            """).rstrip())
    return '<div class="testimonial-grid">\n' + "\n".join(cards) + '\n</div>'

# -------- Pages -----------------------------------------------------------

def page(path: str, html: str):
    out = ROOT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"  wrote {path}")

def home_page():
    depth = 0
    title = "Coles Law Firm | Michigan Estate Planning, Probate & Elder Law Attorneys"
    desc = "Coles Law Firm has served Michigan families for over 20 years with estate planning, wills, trusts, probate, and elder law. Seven offices across Michigan."
    extra = (
        review_schemas(TESTIMONIALS)
        + [location_schema(loc) for loc in LOCATIONS]
    )
    body = dedent(f"""\
        <body>
        {site_header('home', depth)}
        <main id="main">
        <section class="hero">
          <div class="container hero-inner">
            <div class="kicker">Offices in Grand Rapids &middot; Ann Arbor &middot; East Lansing &middot; Kalamazoo &middot; Battle Creek &middot; Muskegon &middot; Newaygo</div>
            <h1>Experienced, proven, and <em>trusted</em>.</h1>
            <p>Make sure your estate is in the right hands. Put your trust in 20+ years of experience and thousands of happy clients across Michigan.</p>
            <div class="hero-actions">
              <a href="{rel(depth, 'contact/')}" class="btn btn-primary">Start Your Estate Plan Today</a>
              <a href="{rel(depth, 'practice-areas/')}" class="btn btn-ghost">Explore Our Services</a>
            </div>
          </div>
        </section>

        <div class="strip">
          <div class="container strip-inner">
            <div class="strip-item"><span class="dot"></span><strong>20+ Years</strong> Serving Michigan</div>
            <div class="strip-item"><span class="dot"></span><span aria-hidden="true" style="color: var(--gold); letter-spacing: 2px;">&#9733;&#9733;&#9733;&#9733;&#9733;</span> <strong>5.0</strong> on Google Reviews</div>
            <div class="strip-item"><span class="dot"></span><strong>Avvo Client's Choice</strong> Award Recipient</div>
            <div class="strip-item"><span class="dot"></span><strong>7 Offices</strong> Across Michigan</div>
          </div>
        </div>

        <section id="about">
          <div class="container">
            <div class="about-grid">
              <div class="about-text">
                <div class="rule" style="margin: 0 0 24px;"></div>
                <h2>A practice built on relationships, not transactions.</h2>
                <p>Founded by attorney Jennifer Coles, our firm has spent more than twenty years helping Michigan families plan for the future and navigate the present with peace of mind. From Grand Rapids to Ann Arbor and points between, we believe estate planning should feel less like paperwork and more like a conversation &mdash; one where your goals, your family, and your values lead the way.</p>
                <p>Whether you're drafting your first will, settling a loved one's estate, or planning for long-term care, we take the time to understand your story before we write a single page.</p>
                <p><a href="{rel(depth, 'about/')}" class="more" style="font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; font-size: 13px;">More about the firm &rarr;</a></p>
                <div class="about-stats">
                  <div class="stat"><div class="num">20+</div><div class="label">Years of Practice</div></div>
                  <div class="stat"><div class="num">1,000+</div><div class="label">Families Served</div></div>
                  <div class="stat"><div class="num">7</div><div class="label">Michigan Offices</div></div>
                  <div class="stat"><div class="num">7</div><div class="label">Practice Areas</div></div>
                </div>
              </div>
              <aside class="about-card">
                <div class="quote-mark" aria-hidden="true">&ldquo;</div>
                <blockquote>Estate planning is, at its heart, an act of love &mdash; a way to take care of the people you care about, long after you're able to be there yourself.</blockquote>
                <cite>&mdash; Jennifer Coles, Founding Attorney</cite>
              </aside>
            </div>
          </div>
        </section>

        <section id="practice" style="background: var(--cream);">
          <div class="container">
            <div class="section-head">
              <div class="eyebrow">What We Do</div>
              <div class="rule"></div>
              <h2>Practice Areas</h2>
              <p>Focused expertise in the legal matters that shape your family's future, your legacy, and your peace of mind.</p>
            </div>
            {render_practice_grid(depth)}
          </div>
        </section>

        <section id="team">
          <div class="container">
            <div class="section-head">
              <div class="eyebrow">Who We Are</div>
              <div class="rule"></div>
              <h2>Meet the Coles Law Team</h2>
              <p>Experienced leadership, dedicated staff, and ambitious interns &mdash; a team that treats every client like a neighbor.</p>
            </div>
            {render_team_grid(depth)}
          </div>
        </section>

        {render_trust_badges()}

        <section class="lead-magnet-band">
          <div class="container">
            {render_lead_magnet(depth, inline=True)}
          </div>
        </section>

        <section id="testimonials" class="testimonials-band">
          <div class="container">
            <div class="section-head">
              <div class="eyebrow">In Their Words</div>
              <div class="rule"></div>
              <h2>What Our Clients Say</h2>
              <p>Two decades of trust, built one family at a time.</p>
            </div>
            {render_testimonials()}
            <div class="reviews-badge">
              <div class="pill">
                <span class="label-tag">Google Reviews</span>
                <span class="pill-stars" aria-hidden="true">&#9733;&#9733;&#9733;&#9733;&#9733;</span>
                <span class="pill-txt">Rated <strong>Excellent</strong> by clients</span>
              </div>
            </div>
          </div>
        </section>

        <section id="locations" class="locations-band">
          <div class="container">
            <div class="section-head">
              <div class="eyebrow">Where to Find Us</div>
              <div class="rule"></div>
              <h2>Seven Michigan Offices</h2>
              <p>From Lake Michigan to mid-state, we meet clients close to home. Call ahead and we'll schedule a visit at the location most convenient for you.</p>
            </div>
            {render_locations_grid(depth)}
          </div>
        </section>

        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("index.html", head(title, desc, "/", depth, extra) + "\n" + body)

def about_page():
    depth = 1
    title = "About Coles Law Firm | 20+ Years Serving Michigan Families"
    desc = "Learn about Coles Law Firm — founded by Jennifer Coles, serving Michigan families with estate planning, probate, and elder law counsel for over two decades."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("About", None)])
    body = dedent(f"""\
        <body>
        {site_header('about', depth)}
        {bc_html}
        <main id="main">
        <div class="container">
          <article class="article">
            <h1>About Coles Law Firm</h1>
            <p class="lede">A small, experienced Michigan law practice built on the belief that estate planning should feel less like paperwork and more like a conversation.</p>

            <p>Coles Law, PLLC was founded by attorney Jennifer Coles to bring careful, plain-spoken legal counsel to Michigan families navigating some of life's most important decisions. For more than twenty years, our practice has focused on estate planning, wills, trusts, probate, elder law, and the legal questions that shape how families care for one another across generations.</p>

            <h2>How we work</h2>
            <p>Most of our clients come to us during a transition: a new baby, a parent's diagnosis, a move into retirement, or the loss of a loved one. We've found that the best legal work in moments like these starts with listening. Before we write a single document, we want to understand your family, your goals, and what keeps you up at night.</p>
            <p>From there, we design plans that are clear, durable, and honest about trade-offs. We explain what each document does, what it costs, and where the limits are. You will never be handed a stack of paper and asked to trust us.</p>

            <h2>Who we serve</h2>
            <p>We serve clients across Michigan from offices in Grand Rapids, Ann Arbor, East Lansing, Kalamazoo, Battle Creek, Muskegon, and Newaygo. For clients who can't easily travel, we offer secure video consultations and, when appropriate, in-home visits.</p>

            <h2>What we believe</h2>
            <p>We believe good estate planning is an act of love &mdash; a way to take care of the people you care about, long after you're able to be there yourself. We believe the legal profession should be approachable, not intimidating. And we believe that twenty years of doing this work is most useful when it's still applied one family at a time.</p>

            <p><a href="{rel(depth, 'contact/')}">Schedule a consultation &rarr;</a></p>
          </article>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("about/index.html", head(title, desc, "/about/", depth, [bc_schema]) + "\n" + body)

def team_index_page():
    depth = 1
    title = "Meet the Team | Coles Law Firm Attorneys & Staff"
    desc = "Meet the attorneys and staff of Coles Law Firm — Jennifer Coles, Brian Coles, Kevin Hansen, Julie Turner, and our team of professionals serving Michigan."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Meet the Team", None)])
    extras = [bc_schema] + [person_schema(t) for t in TEAM]
    body = dedent(f"""\
        <body>
        {site_header('team', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Meet the Coles Law Team</h1>
            <p>Experienced leadership, dedicated staff, and ambitious interns &mdash; serving Michigan families with care.</p>
          </div>
        </section>
        <section>
          <div class="container">
            {render_team_grid(depth)}
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("meet-the-team/index.html", head(title, desc, "/meet-the-team/", depth, extras) + "\n" + body)

def team_member_page(p: dict):
    depth = 2
    title = f"{p['name']} | {p['role']} at Coles Law Firm"
    desc = p["short"]
    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        ("Meet the Team", "meet-the-team/"),
        (p["name"], None),
    ])
    credentials_html = "\n".join(
        f'                  <li><strong>{label}:</strong> {value}</li>'
        for label, value in p["credentials"]
    )
    long_html = "\n".join(f"            <p>{para}</p>" for para in p["long"])
    body = dedent(f"""\
        <body>
        {site_header('team', depth)}
        {bc_html}
        <main id="main">
        <div class="container">
          <div class="profile-grid">
            <div class="profile-photo" aria-hidden="true">
              <span class="initial">{p['initial']}</span>
            </div>
            <div class="profile-info">
              <h1>{p['name']}</h1>
              <div class="role">{p['role']}</div>
        {long_html}
              <div class="profile-credentials">
                <h3>Background</h3>
                <ul>
        {credentials_html}
                </ul>
              </div>
              <p><a href="{rel(depth, 'contact/')}">Contact our team &rarr;</a></p>
            </div>
          </div>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page(f"team/{p['slug']}/index.html", head(title, desc, f"/team/{p['slug']}/", depth, [bc_schema, person_schema(p)]) + "\n" + body)

def practice_index_page():
    depth = 1
    title = "Practice Areas | Michigan Estate Planning, Probate, Elder Law"
    desc = "Coles Law Firm's practice areas: revocable living trusts, wills & codicils, powers of attorney, elder law, Medicaid planning, guardianships, and probate estates."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Practice Areas", None)])
    extras = [bc_schema] + [service_schema(s) for s in PRACTICES]
    body = dedent(f"""\
        <body>
        {site_header('practice', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Practice Areas</h1>
            <p>Focused expertise in the legal matters that shape your family's future, your legacy, and your peace of mind.</p>
          </div>
        </section>
        <section style="background: var(--cream);">
          <div class="container">
            {render_practice_grid(depth)}
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("practice-areas/index.html", head(title, desc, "/practice-areas/", depth, extras) + "\n" + body)

def practice_detail_page(s: dict):
    depth = 2
    title = f"{s['name']} | Michigan Estate Planning | Coles Law Firm"
    desc = s["summary"]
    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        ("Practice Areas", "practice-areas/"),
        (s["name"], None),
    ])
    body_html = "\n".join(f"            <p>{p}</p>" for p in s["body"])
    benefits_html = "\n".join(f"              <li>{b}</li>" for b in s["benefits"])
    # Cross-link to all locations
    loc_links = ", ".join(
        f'<a href="{rel(depth, "locations/" + loc["slug"] + "/")}">{loc["name"]}</a>'
        for loc in LOCATIONS
    )
    # Cross-link to other practice areas
    other_practices = [p for p in PRACTICES if p["slug"] != s["slug"]]
    related_cards = "\n".join(dedent(f"""\
                <a class="related-card" href="{rel(depth, 'practice-areas/' + p['slug'] + '/')}">
                  <span class="related-icon" aria-hidden="true">{p['icon']}</span>
                  <span class="related-name">{p['name']}</span>
                </a>""") for p in other_practices[:4])
    # Relevant FAQs (heuristic: pick first 3)
    relevant = FAQS[:3]
    faqs_html = "\n".join(dedent(f"""\
                <div class="faq-item">
                  <h3>{f['q']}</h3>
                  <p>{f['a']}</p>
                </div>""") for f in relevant)
    body = dedent(f"""\
        <body>
        {site_header('practice', depth)}
        {bc_html}
        <main id="main">
        <div class="container">
          <article class="article">
            <h1>{s['name']}</h1>
            <p class="lede">{s['tagline']}</p>
        {body_html}
            <h2>What we help with</h2>
            <ul>
        {benefits_html}
            </ul>

            <aside class="pricing-callout">
              <div class="pc-label">Typical Investment</div>
              <div class="pc-range">{s['pricing_range']}</div>
              <p class="pc-note">{s['pricing_note']}</p>
              <p class="pc-fine">Full pricing details and what's included are discussed at your free initial consultation. <a href="{rel(depth, 'what-to-expect/')}">See what to expect &rarr;</a></p>
            </aside>

            <h2>Common questions</h2>
            <div class="faq-list" style="margin: 20px 0;">
        {faqs_html}
            </div>

            <h2>Available across Michigan</h2>
            <p>We provide {s['name'].lower()} services at all seven of our Michigan offices: {loc_links}. Virtual consultations are available statewide; in-home visits can be arranged on request.</p>

            <h2>Related practice areas</h2>
            <div class="related-grid">
        {related_cards}
            </div>

            <h2>Ready to begin?</h2>
            <p>The earliest stages of estate planning are usually the most consequential. Schedule a free consultation and we'll talk through whether {s['name']} is the right fit for your situation, or whether a different starting point makes more sense.</p>
            <p><a href="{rel(depth, 'contact/')}" class="btn btn-dark" style="display: inline-block;">Schedule a Consultation</a></p>
          </article>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    extras = [bc_schema, service_schema(s), faq_schema(relevant)]
    page(f"practice-areas/{s['slug']}/index.html", head(title, desc, f"/practice-areas/{s['slug']}/", depth, extras) + "\n" + body)

def locations_index_page():
    depth = 1
    title = "Office Locations | Coles Law Firm | 7 Michigan Offices"
    desc = "Coles Law Firm offices across Michigan: Grand Rapids, Ann Arbor, East Lansing, Kalamazoo, Battle Creek, Muskegon, and Newaygo. Schedule a visit today."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Locations", None)])
    extras = [bc_schema] + [location_schema(loc) for loc in LOCATIONS]
    body = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Seven Michigan Offices</h1>
            <p>From Lake Michigan to mid-state, we meet clients close to home. Schedule a visit at the location most convenient for you.</p>
          </div>
        </section>
        <section class="locations-band">
          <div class="container">
            {render_locations_grid(depth)}
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("locations/index.html", head(title, desc, "/locations/", depth, extras) + "\n" + body)
    # Maps & Directions: legacy WP URL — point at the same content
    legacy = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html.replace('Locations', 'Maps &amp; Directions')}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Maps &amp; Directions</h1>
            <p>Directions to each of our seven Michigan offices. For a guided visit, call us at <a href="tel:{FIRM_PHONE_TEL}" style="color: var(--gold-soft);">{FIRM_PHONE}</a> and we'll meet you at the door.</p>
          </div>
        </section>
        <section class="locations-band">
          <div class="container">
            {render_locations_grid(depth)}
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("maps-directions/index.html", head("Maps & Directions | Coles Law Firm Offices", desc, "/maps-directions/", depth, extras) + "\n" + legacy)

def location_detail_page(loc: dict):
    depth = 2
    city_state = f"{loc['city']}, {loc['state']}"
    title = f"{loc['name']} Estate Planning Attorney | Coles Law Firm Office"
    desc = f"Coles Law Firm's {loc['name']} office at {loc['street']}{', ' + loc['suite'] if loc['suite'] else ''}, {city_state}. Estate planning, wills, trusts, probate, and elder law."
    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        ("Locations", "locations/"),
        (loc["name"], None),
    ])
    suite_inline = (', ' + loc['suite']) if loc['suite'] else ''
    full_address = loc['street'] + (' ' + loc['suite'] if loc['suite'] else '') + ', ' + city_state + ' ' + loc['zip']
    map_query = urllib.parse.quote_plus(full_address)

    services_html = "\n".join(dedent(f"""\
                <li>
                  <a href="{rel(depth, 'practice-areas/' + s['slug'] + '/')}">{s['name']}</a>
                  <span>{s['tagline']}</span>
                </li>""") for s in PRACTICES)

    other_offices = [o for o in LOCATIONS if o["slug"] != loc["slug"]]
    other_chips = "\n".join(
        f'              <a href="{rel(depth, "locations/" + o["slug"] + "/")}">{o["name"]}</a>'
        for o in other_offices
    )

    body = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html}
        <main id="main">

        <section class="location-hero">
          <div class="container">
            <div class="city-label">{city_state} Office</div>
            <h1>{loc['name']} Estate Planning &amp; Probate Attorneys</h1>
            <p class="blurb">{loc['blurb']}</p>
            <div class="quick-meta">
              <div>
                <strong>Address</strong>
                <div class="val">{loc['street']}{suite_inline}, {city_state} {loc['zip']}</div>
              </div>
              <div>
                <strong>Phone</strong>
                <div class="val"><a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a></div>
              </div>
              <div>
                <strong>Hours</strong>
                <div class="val">Monday &ndash; Friday, 9 AM &ndash; 5 PM</div>
              </div>
            </div>
          </div>
        </section>

        <section class="location-map-section">
          <div class="container">
            <div class="map-embed">
              <iframe
                title="Map of Coles Law Firm {loc['name']} office"
                src="https://maps.google.com/maps?q={map_query}&t=&z=15&ie=UTF8&iwloc=&output=embed"
                loading="lazy"
                referrerpolicy="no-referrer-when-downgrade"></iframe>
              <div class="map-embed-caption">
                <span class="addr"><strong>Coles Law Firm &mdash; {loc['name']}</strong> &middot; {loc['street']}{suite_inline}, {city_state} {loc['zip']}</span>
                <a href="https://maps.google.com/?q={map_query}" rel="noopener" target="_blank">Get Directions &rarr;</a>
              </div>
            </div>
          </div>
        </section>

        <section class="location-body">
          <div class="container">
            <div class="content">
              <div class="section-block">
                <h2>Services at our {loc['name']} office</h2>
                <p>Our {loc['name']} office offers the full range of Coles Law Firm services.</p>
                <ul class="services-list">
        {services_html}
                </ul>
              </div>

              <div class="section-block">
                <h2>Our other Michigan offices</h2>
                <p>If {loc['name']} isn't convenient, we may have a location closer to you.</p>
                <div class="other-offices">
        {other_chips}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="location-cta-band">
          <div class="container">
            <h2>Schedule a visit to our {loc['name']} office</h2>
            <p>Consultations are by appointment so our team can give you their full attention. We'll respond within one business day.</p>
            <div class="cta-row">
              <a href="tel:{FIRM_PHONE_TEL}" class="btn btn-primary">Call {FIRM_PHONE}</a>
              <a href="{rel(depth, 'contact/')}" class="btn btn-ghost">Send a Message</a>
            </div>
          </div>
        </section>

        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page(f"locations/{loc['slug']}/index.html", head(title, desc, f"/locations/{loc['slug']}/", depth, [bc_schema, location_schema(loc)]) + "\n" + body)

def contact_page():
    depth = 1
    title = "Contact Us | Coles Law Firm | Free Consultation"
    desc = f"Contact Coles Law Firm to schedule a free consultation. Call {FIRM_PHONE} or email {FIRM_EMAIL}. Seven Michigan offices and virtual consultations available."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Contact", None)])
    contact_schema = {
        "@context": "https://schema.org",
        "@type": "ContactPage",
        "name": "Contact Coles Law Firm",
        "url": url("/contact/"),
        "mainEntity": organization_schema(),
    }
    body = dedent(f"""\
        <body>
        {site_header('contact', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Schedule a Consultation</h1>
            <p>Tell us a little about your situation and we'll be in touch to set up a confidential conversation &mdash; in person, by phone, or by video.</p>
          </div>
        </section>

        <section class="calendly-section">
          <div class="container">
            <div class="section-head" style="margin-bottom: 32px;">
              <div class="eyebrow">Pick a Time</div>
              <h2 style="font-size: clamp(28px, 3.4vw, 38px); margin-bottom: 8px;">Book a free 30-minute consultation</h2>
              <p style="font-size: 16px;">No pressure, no obligation. Choose the time that works for you.</p>
            </div>
            {render_calendly(depth)}
          </div>
        </section>

        <section style="background: var(--cream);">
          <div class="container">
            <div class="section-head" style="margin-bottom: 32px;">
              <div class="eyebrow">Or Send Us a Message</div>
              <h2 style="font-size: clamp(26px, 3vw, 34px);">Prefer to write?</h2>
              <p style="font-size: 16px;">We respond to messages within one business day.</p>
            </div>
            <div class="contact-grid">
              <div class="contact-info">
                <h3>Get in Touch</h3>
                <p class="lead">Schedule a visit at any one of our seven Michigan offices, or arrange a virtual consultation from anywhere statewide.</p>
                <div class="contact-meta">
                  <div><span class="label-cell">Phone</span><span class="val"><a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a></span></div>
                  <div><span class="label-cell">Email</span><span class="val"><a href="mailto:{FIRM_EMAIL}">{FIRM_EMAIL}</a></span></div>
                  <div><span class="label-cell">Hours</span><span class="val">Monday &ndash; Friday, 9:00 AM &ndash; 5:00 PM</span></div>
                </div>
                <p style="margin-top: 32px; color: var(--ink-soft); font-size: 15px;">Prefer to drop in? See our <a href="{rel(depth, 'locations/')}" style="font-weight: 600;">full list of office locations &rarr;</a></p>
              </div>
              <form class="contact-form" onsubmit="event.preventDefault(); alert('Thank you. We will be in touch shortly.'); this.reset();">
                <h3>Request a Consultation</h3>
                <p class="form-sub">All inquiries are confidential. We typically respond within one business day.</p>
                <div class="field"><label for="name">Full Name</label><input id="name" name="name" type="text" required autocomplete="name"></div>
                <div class="field"><label for="email">Email Address</label><input id="email" name="email" type="email" required autocomplete="email"></div>
                <div class="field"><label for="phone">Phone</label><input id="phone" name="phone" type="tel" autocomplete="tel"></div>
                <div class="field"><label for="topic">How Can We Help?</label>
                  <select id="topic" name="topic">
                    <option>Revocable Living Trust</option>
                    <option>Wills &amp; Codicils</option>
                    <option>Powers of Attorney</option>
                    <option>Elder Law</option>
                    <option>Medicaid &amp; Medicare</option>
                    <option>Guardianships</option>
                    <option>Probate Estates</option>
                    <option>Other / Not Sure</option>
                  </select>
                </div>
                <div class="field"><label for="message">Brief Description</label>
                  <textarea id="message" name="message" placeholder="A sentence or two about your situation is plenty &mdash; we'll follow up for the details."></textarea>
                </div>
                <button type="submit" class="form-submit">Send Inquiry</button>
                <p class="disclaimer">Submitting this form does not create an attorney-client relationship. Please do not share confidential information until such a relationship is formally established.</p>
              </form>
            </div>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("contact/index.html", head(title, desc, "/contact/", depth, [bc_schema, contact_schema]) + "\n" + body)

def faq_page():
    depth = 1
    title = "Estate Planning FAQ | Coles Law Firm Michigan"
    desc = "Answers to common questions about Michigan estate planning, wills, trusts, probate, Medicaid planning, and working with Coles Law Firm."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("FAQ", None)])
    items_html = "\n".join(dedent(f"""\
            <div class="faq-item">
              <h3>{f['q']}</h3>
              <p>{f['a']}</p>
            </div>""") for f in FAQS)
    body = dedent(f"""\
        <body>
        {site_header('faq', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Frequently Asked Questions</h1>
            <p>Answers to the questions we hear most often about estate planning, probate, and working with our firm.</p>
          </div>
        </section>
        <section>
          <div class="container">
            <div class="faq-list">
        {items_html}
            </div>
            <p style="text-align: center; margin-top: 48px;">Have a question not answered here? <a href="{rel(depth, 'contact/')}" style="font-weight: 600;">Get in touch &rarr;</a></p>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("faq/index.html", head(title, desc, "/faq/", depth, [bc_schema, faq_schema(FAQS)]) + "\n" + body)

def blog_page():
    depth = 1
    title = "Blog | Coles Law Firm | Estate Planning Insights"
    desc = "Estate planning, probate, and elder law insights from the attorneys at Coles Law Firm in Michigan."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Blog", None)])
    cards = []
    for post in BLOG_POSTS:
        cards.append(dedent(f"""\
            <article class="blog-card">
              <div class="blog-meta">
                <time datetime="{post['date']}">{post['date_display']}</time>
                <span class="dot-sep">&middot;</span>
                <span>{post['author']}</span>
              </div>
              <h2><a href="{rel(depth, 'blog/' + post['slug'] + '/')}">{post['title']}</a></h2>
              <p>{post['excerpt']}</p>
              <a class="blog-more" href="{rel(depth, 'blog/' + post['slug'] + '/')}">Read more &rarr;</a>
            </article>
            """).rstrip())
    cards_html = "\n".join(cards)
    body = dedent(f"""\
        <body>
        {site_header('blog', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>From Our Blog</h1>
            <p>Practical guidance on estate planning, probate, and elder law from the team at Coles Law Firm.</p>
          </div>
        </section>
        <section>
          <div class="container">
            <div class="blog-list">
        {cards_html}
            </div>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("blog/index.html", head(title, desc, "/blog/", depth, [bc_schema]) + "\n" + body)

def blog_post_page(post: dict):
    depth = 2
    title = f"{post['title']} | Coles Law Firm Blog"
    desc = post["excerpt"]
    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        ("Blog", "blog/"),
        (post["title"], None),
    ])
    body_html = "\n".join(
        (f"            {b}" if b.startswith("<h") else f"            <p>{b}</p>")
        for b in post["body"]
    )
    body = dedent(f"""\
        <body>
        {site_header('blog', depth)}
        {bc_html}
        <main id="main">
        <div class="container">
          <article class="article">
            <div class="blog-meta" style="margin-bottom: 12px;">
              <time datetime="{post['date']}">{post['date_display']}</time>
              <span class="dot-sep">&middot;</span>
              <span>By {post['author']}</span>
            </div>
            <h1>{post['title']}</h1>
            <p class="lede">{post['excerpt']}</p>
        {body_html}
            <hr style="margin: 40px 0; border: 0; border-top: 1px solid var(--rule);">
            <p style="font-size: 14px; color: var(--ink-soft);">This article is provided for general information only and does not constitute legal advice. For guidance specific to your situation, please <a href="{rel(depth, 'contact/')}">schedule a consultation</a>.</p>
            <p><a href="{rel(depth, 'blog/')}">&larr; Back to all posts</a></p>
          </article>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page(f"blog/{post['slug']}/index.html", head(title, desc, f"/blog/{post['slug']}/", depth, [bc_schema, blog_post_schema(post)]) + "\n" + body)

def service_city_page(svc: dict, loc: dict):
    """Hyper-local landing page for a service + city combination.

    URL: /{city-slug}-{service-slug}/ — flat structure keeps the
    keyword close to the domain root, which matters for local SEO.
    """
    depth = 1
    slug = f"{loc['slug']}-{svc['slug']}"
    canonical = f"/{slug}/"
    title = f"{loc['name']} {svc['name']} | Coles Law Firm | {loc['county']}, MI"
    desc = (
        f"Looking for a {loc['name']} {svc['name'].lower()}? Coles Law Firm has served "
        f"{loc['county']} families for 20+ years from our {loc['name']} office. "
        f"Free initial consultation."
    )
    full_address = loc['street'] + (' ' + loc['suite'] if loc['suite'] else '') + ', ' + loc['city'] + ', ' + loc['state'] + ' ' + loc['zip']
    map_query = urllib.parse.quote_plus(full_address)

    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        (loc["name"] + " Office", f"locations/{loc['slug']}/"),
        (f"{loc['name']} {svc['name']}", None),
    ])

    communities = loc["communities"]
    communities_chips = "\n".join(
        f'              <span class="community-chip">{c}</span>' for c in communities
    )

    # Cross-link to other SEO services for this city
    other_svcs = [s for s in SEO_SERVICES if s["slug"] != svc["slug"]]
    other_links = "\n".join(
        f'                  <li><a href="{rel(depth, loc["slug"] + "-" + s["slug"] + "/")}">{loc["name"]} {s["name"]}</a></li>'
        for s in other_svcs
    )
    # Cross-link to same service in other cities
    other_cities = [l for l in LOCATIONS if l["slug"] != loc["slug"]]
    other_city_links = "\n".join(
        f'                  <li><a href="{rel(depth, l["slug"] + "-" + svc["slug"] + "/")}">{l["name"]} {svc["name"]}</a></li>'
        for l in other_cities
    )

    practice_href = (
        rel(depth, f"practice-areas/{svc['practice_slug']}/")
        if svc["practice_slug"] else
        rel(depth, "practice-areas/")
    )

    schema_service = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": f"{svc['name']} in {loc['name']}, MI",
        "serviceType": svc["name"],
        "provider": location_schema(loc),
        "description": desc,
        "areaServed": {
            "@type": "City",
            "name": loc["city"],
            "containedInPlace": {"@type": "AdministrativeArea", "name": loc["county"]},
        },
        "url": url(canonical),
    }

    body = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html}
        <main id="main">

        <section class="sc-hero">
          <div class="container">
            <div class="sc-eyebrow">{loc['name']}, MI &middot; {loc['county']}</div>
            <h1>{loc['name']} {svc['name']}</h1>
            <p class="sc-lede">{svc['intro']} Serving {loc['name']} and {loc['county']} for over 20 years from our {loc['name']} office.</p>
            <div class="sc-actions">
              <a href="{rel(depth, 'contact/')}" class="btn btn-primary">Schedule Free Consultation</a>
              <a href="tel:{FIRM_PHONE_TEL}" class="btn btn-ghost">Call {FIRM_PHONE}</a>
            </div>
          </div>
        </section>

        <section class="sc-body">
          <div class="container">
            <div class="sc-grid">
              <article class="sc-content">
                <h2>{svc['name'].split()[0]} services in {loc['name']}</h2>
                <p>{svc['what_we_do']} Our {loc['name']} office handles {svc['short']} matters across {loc['county']} and the surrounding region, from initial consultation through final document signing or court closing.</p>

                <h2>Local court &amp; jurisdiction</h2>
                <p>{loc['name']} {svc['short'].capitalize()} matters that go before a court are typically filed with the <strong>{loc['probate_court']}</strong>. We've worked with the {loc['county']} probate bench for two decades and know the local procedures &mdash; from filing requirements to typical hearing timelines.</p>

                <h2>Communities we serve from our {loc['name']} office</h2>
                <p>Clients reach our {loc['name']} office from across {loc['county']} and nearby communities, including:</p>
                <div class="community-chips">
        {communities_chips}
                </div>

                <h2>Why families in {loc['name']} choose Coles Law</h2>
                <p>For more than twenty years, families in {loc['name']} have trusted Jennifer Coles and our team with their {svc['short']} matters. A few reasons clients tell us they came back &mdash; or referred a friend:</p>
                <ul>
                  <li><strong>Local presence.</strong> Our {loc['name']} office is staffed by attorneys who actually work in {loc['county']} &mdash; not a call center answering from another state.</li>
                  <li><strong>Plain English.</strong> We explain {svc['short']} in language you can understand, with time to ask questions.</li>
                  <li><strong>Flat fees where possible.</strong> No surprise bills. You'll know the cost before we begin work.</li>
                  <li><strong>Long-term relationship.</strong> Estate plans evolve. We're here years from now to update yours as life changes.</li>
                </ul>

                <p style="margin-top: 32px;"><a href="{practice_href}">Read more about our {svc['name'].lower() if svc['practice_slug'] else 'estate planning'} practice &rarr;</a></p>
              </article>

              <aside class="sc-aside">
                <div class="sc-office-card">
                  <div class="card-header">{loc['name']} Office</div>
                  <div class="card-body">
                    <p style="margin-bottom: 14px;">{loc['blurb']}</p>
                    <div class="meta-line"><strong>Address</strong>{loc['street']}{', ' + loc['suite'] if loc['suite'] else ''}<br>{loc['city']}, {loc['state']} {loc['zip']}</div>
                    <div class="meta-line"><strong>Phone</strong><a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a></div>
                    <div class="meta-line"><strong>Hours</strong>Mon&ndash;Fri, 9 AM &ndash; 5 PM</div>
                    <div class="meta-line"><strong>Service area</strong>{loc['county']} &amp; surrounding</div>
                  </div>
                  <div class="card-cta">
                    <a href="{rel(depth, 'locations/' + loc['slug'] + '/')}">Office details &amp; map &rarr;</a>
                  </div>
                </div>

                <div class="sc-related">
                  <div class="sc-related-label">Other {loc['name']} services</div>
                  <ul>
        {other_links}
                  </ul>
                </div>
              </aside>
            </div>

            <div class="sc-related-cities">
              <h3>{svc['name']} in other Michigan cities</h3>
              <ul>
        {other_city_links}
              </ul>
            </div>
          </div>
        </section>

        <section class="location-cta-band">
          <div class="container">
            <h2>{loc['name']} {svc['name']}, ready when you are.</h2>
            <p>Free initial consultation. No pressure. Pick a time or call our {loc['name']} office.</p>
            <div class="cta-row">
              <a href="{rel(depth, 'contact/')}" class="btn btn-primary">Schedule Consultation</a>
              <a href="tel:{FIRM_PHONE_TEL}" class="btn btn-ghost">Call {FIRM_PHONE}</a>
            </div>
          </div>
        </section>

        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page(f"{slug}/index.html", head(title, desc, canonical, depth, [bc_schema, schema_service]) + "\n" + body)


def local_index_page():
    """Hub page listing all city x service combinations as a matrix."""
    depth = 1
    title = "Local Coverage | Coles Law Firm | Michigan City & Service Index"
    desc = "Find a Coles Law Firm landing page for your city and the legal service you need. Estate planning, probate, trusts, elder law and more — across seven Michigan cities."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Local Coverage", None)])

    rows = []
    for loc in LOCATIONS:
        cells = []
        for svc in SEO_SERVICES:
            cells.append(
                f'<a class="mx-cell" href="{rel(depth, loc["slug"] + "-" + svc["slug"] + "/")}">{svc["name"]}</a>'
            )
        rows.append(dedent(f"""\
            <div class="mx-row">
              <div class="mx-city">
                <a href="{rel(depth, 'locations/' + loc['slug'] + '/')}"><strong>{loc['name']}</strong><span>{loc['county']}</span></a>
              </div>
              <div class="mx-cells">
                {''.join(cells)}
              </div>
            </div>"""))

    body = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Local Coverage</h1>
            <p>Every service we offer, broken down by Michigan city. Tap any combination to jump to a page tailored for that area.</p>
          </div>
        </section>
        <section style="background: var(--cream);">
          <div class="container">
            <div class="matrix">
        {chr(10).join(rows)}
            </div>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("local/index.html", head(title, desc, "/local/", depth, [bc_schema]) + "\n" + body)


def not_found_page():
    depth = 0
    title = "Page Not Found | Coles Law Firm"
    desc = "The page you were looking for can't be found. Browse our practice areas, locations, or contact us for help."
    body = dedent(f"""\
        <body>
        {site_header('home', depth)}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container" style="text-align: center;">
            <h1>404 &mdash; Page Not Found</h1>
            <p>The page you were looking for can't be found. It may have moved, or the link may be incorrect.</p>
          </div>
        </section>
        <section>
          <div class="container" style="text-align: center; max-width: 720px;">
            <h2 style="margin-bottom: 16px;">A few helpful places to start:</h2>
            <p style="margin-bottom: 28px;"><a href="{rel(depth, '')}">Home</a> &middot; <a href="{rel(depth, 'practice-areas/')}">Practice Areas</a> &middot; <a href="{rel(depth, 'meet-the-team/')}">Meet the Team</a> &middot; <a href="{rel(depth, 'locations/')}">Locations</a> &middot; <a href="{rel(depth, 'faq/')}">FAQ</a> &middot; <a href="{rel(depth, 'blog/')}">Blog</a></p>
            <p><a href="{rel(depth, 'contact/')}" class="btn btn-dark">Contact Us</a></p>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("404.html", head(title, desc, "/404", depth) + "\n" + body)

def what_to_expect_page():
    depth = 1
    title = "What to Expect | Coles Law Firm | First Consultation"
    desc = "What to expect when you reach out to Coles Law Firm: how the first meeting works, what to bring, how long things take, and what it costs."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("What to Expect", None)])
    body = dedent(f"""\
        <body>
        {site_header('home', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>What to Expect</h1>
            <p>Most people reaching out to a law firm for the first time are a little anxious. Here's exactly how the process works, so there are no surprises.</p>
          </div>
        </section>

        <section>
          <div class="container">
            <div class="wte-grid">
              <div class="wte-step">
                <div class="wte-num">01</div>
                <h3>You reach out</h3>
                <p>Call us, use the contact form, or pick a time directly on the calendar. We'll confirm your appointment within one business day.</p>
              </div>
              <div class="wte-step">
                <div class="wte-num">02</div>
                <h3>Your first consultation is free</h3>
                <p>Thirty to forty-five minutes. Phone, video, or in person at any of our seven Michigan offices. No fee, no pressure, no obligation to hire us.</p>
              </div>
              <div class="wte-step">
                <div class="wte-num">03</div>
                <h3>We listen, then explain</h3>
                <p>You tell us about your family and your goals. We explain how the relevant law works, what options exist, and what each one would cost.</p>
              </div>
              <div class="wte-step">
                <div class="wte-num">04</div>
                <h3>You decide</h3>
                <p>No high-pressure sales. If we're the right fit, we send a clear engagement letter with a flat fee or hourly estimate. If we're not, we'll often suggest who is.</p>
              </div>
              <div class="wte-step">
                <div class="wte-num">05</div>
                <h3>The work begins</h3>
                <p>Most estate plans take 2&ndash;4 weeks from engagement to signing. We send drafts ahead of every meeting so you can review at your own pace.</p>
              </div>
              <div class="wte-step">
                <div class="wte-num">06</div>
                <h3>We stay in touch</h3>
                <p>Your plan should grow with you. We'll check in periodically to review it as your family, finances, or Michigan law changes.</p>
              </div>
            </div>
          </div>
        </section>

        <section style="background: var(--cream);">
          <div class="container">
            <div class="wte-cols">
              <div>
                <h2>What to bring to your first meeting</h2>
                <ul class="wte-list">
                  <li>Any existing estate planning documents (even old ones)</li>
                  <li>A rough list of your assets and approximate values</li>
                  <li>Names of people you'd want as personal representatives, trustees, guardians, or agents</li>
                  <li>Questions &mdash; the more specific, the better</li>
                </ul>
                <p style="color: var(--ink-soft); font-size: 15px;">Don't have all of this yet? That's fine. We can work from what you have and fill in the rest together.</p>
              </div>
              <div>
                <h2>What it costs</h2>
                <p>Most of our work is flat-fee. You'll know the number before you commit. A few matters (such as probate administration) are billed hourly, and we discuss expected budget at the consultation.</p>
                <p class="pricing-disclaimer">Your actual fee is quoted in writing after the initial consultation, with no surprise bills.</p>
              </div>
            </div>
          </div>
        </section>

        <section class="location-cta-band">
          <div class="container">
            <h2>Ready when you are.</h2>
            <p>Free initial consultation. No pressure. Pick a time or send us a note.</p>
            <div class="cta-row">
              <a href="{rel(depth, 'contact/')}" class="btn btn-primary">Schedule Consultation</a>
              <a href="tel:{FIRM_PHONE_TEL}" class="btn btn-ghost">Call {FIRM_PHONE}</a>
            </div>
          </div>
        </section>

        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("what-to-expect/index.html", head(title, desc, "/what-to-expect/", depth, [bc_schema]) + "\n" + body)

def checklist_page():
    depth = 2
    title = "Michigan Estate Planning Checklist | Coles Law Firm"
    desc = "A short, plain-English Michigan estate planning checklist — the things most families forget, and questions to answer before your first attorney meeting. Free, no email required."
    bc_html, bc_schema = breadcrumbs(depth, [
        ("Home", ""),
        ("Resources", "resources/"),
        ("Estate Planning Checklist", None),
    ])
    body = dedent(f"""\
        <body>
        {site_header('home', depth)}
        {bc_html}
        <main id="main">
        <div class="container">
          <article class="article checklist-article">
            <div class="checklist-banner">
              <div>
                <div class="cb-eyebrow">Free Resource &middot; No Email Required</div>
                <h1>Michigan Estate Planning Checklist</h1>
                <p class="lede">A short, plain-English starter. Three sections, no fluff &mdash; the things most families forget, and a few questions to answer before your first attorney meeting.</p>
              </div>
              <div class="cb-actions">
                <button class="btn btn-dark" onclick="window.print()">Print or Save as PDF</button>
              </div>
            </div>

            <h2>1. The five core documents</h2>
            <p>Most complete estate plans rest on five documents. If you have all five, properly executed under Michigan law, you've covered the major scenarios.</p>
            <ul class="check-list">
              <li><strong>Last Will &amp; Testament</strong> &mdash; names guardians for minor children, a personal representative, and directs distribution.</li>
              <li><strong>Revocable Living Trust</strong> &mdash; manages assets during life and avoids probate at death (when properly funded).</li>
              <li><strong>Durable Financial Power of Attorney</strong> &mdash; names someone to handle finances if you're incapacitated.</li>
              <li><strong>Patient Advocate Designation</strong> &mdash; Michigan's healthcare power of attorney.</li>
              <li><strong>HIPAA Authorization</strong> &mdash; lets your loved ones access your medical information.</li>
            </ul>

            <h2>2. Things people commonly forget</h2>
            <ul class="check-list">
              <li><strong>Trust funding.</strong> A trust only works for assets actually titled in its name. Most plans go wrong here, not in the drafting.</li>
              <li><strong>Beneficiary designations.</strong> Retirement accounts, life insurance, and bank PODs pass outside your will. Check them annually.</li>
              <li><strong>Digital assets.</strong> Email, photos, password manager, crypto, social accounts &mdash; make a list, and decide who can access what.</li>
              <li><strong>Pets.</strong> Michigan recognizes pet trusts. Even informally, name a caregiver and provide for their costs.</li>
              <li><strong>Out-of-state property.</strong> Real estate in another state can trigger separate (ancillary) probate. A trust solves this.</li>
              <li><strong>Letters of instruction.</strong> Non-binding, but enormously helpful for your family. Where things are, what your wishes are, who to call.</li>
            </ul>

            <h2>3. Questions to think about before your first attorney meeting</h2>
            <ul class="check-list">
              <li>Who would you name as guardian for any minor children?</li>
              <li>Who would you trust to make financial decisions for you?</li>
              <li>Who would you trust to make medical decisions for you?</li>
              <li>What matters most to you about how your estate is divided?</li>
              <li>Are there family complications &mdash; second marriages, estranged relatives, special-needs beneficiaries &mdash; that need to be addressed?</li>
              <li>What's your rough net worth, and where are your assets held?</li>
              <li>Do you have long-term care concerns for yourself or a parent?</li>
            </ul>

            <hr style="margin: 40px 0; border: 0; border-top: 1px solid var(--rule);">
            <p style="text-align: center; font-size: 14px; color: var(--ink-soft);">Want to talk through any of the above? <a href="{rel(depth, 'contact/')}">Schedule a free 30-minute consultation.</a> No pressure.</p>
          </article>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("resources/estate-planning-checklist/index.html", head(title, desc, "/resources/estate-planning-checklist/", depth, [bc_schema]) + "\n" + body)

def resources_index_page():
    depth = 1
    title = "Resources | Coles Law Firm"
    desc = "Free, plain-English resources from Coles Law Firm: estate planning checklists, FAQs, and articles on Michigan probate and elder law."
    bc_html, bc_schema = breadcrumbs(depth, [("Home", ""), ("Resources", None)])
    body = dedent(f"""\
        <body>
        {site_header('home', depth)}
        {bc_html}
        <main id="main">
        <section class="hero hero-compact">
          <div class="container">
            <h1>Resources</h1>
            <p>Plain-English guides, checklists, and articles. Free to read or share &mdash; no email required.</p>
          </div>
        </section>
        <section>
          <div class="container">
            <div class="resources-grid">
              <a class="resource-card" href="{rel(depth, 'resources/estate-planning-checklist/')}">
                <div class="rc-label">Checklist</div>
                <h2>Michigan Estate Planning Checklist</h2>
                <p>A short, plain-English starter covering the five core documents, common gaps, and questions to think through before your first attorney meeting.</p>
                <span class="rc-link">Open the checklist &rarr;</span>
              </a>
              <a class="resource-card" href="{rel(depth, 'blog/')}">
                <div class="rc-label">Articles</div>
                <h2>From Our Blog</h2>
                <p>Estate planning, probate, Medicaid, and elder law explained without jargon.</p>
                <span class="rc-link">Browse articles &rarr;</span>
              </a>
              <a class="resource-card" href="{rel(depth, 'faq/')}">
                <div class="rc-label">FAQ</div>
                <h2>Frequently Asked Questions</h2>
                <p>Answers to the questions we hear most often from prospective clients.</p>
                <span class="rc-link">Read the FAQ &rarr;</span>
              </a>
            </div>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("resources/index.html", head(title, desc, "/resources/", depth, [bc_schema]) + "\n" + body)

# -------- sitemap & robots ------------------------------------------------

def sitemap():
    urls = [
        "/",
        "/about/",
        "/meet-the-team/",
        "/practice-areas/",
        "/locations/",
        "/maps-directions/",
        "/contact/",
        "/faq/",
        "/blog/",
        "/what-to-expect/",
        "/resources/",
        "/resources/estate-planning-checklist/",
    ]
    urls += [f"/team/{t['slug']}/" for t in TEAM]
    urls += [f"/practice-areas/{p['slug']}/" for p in PRACTICES]
    urls += [f"/locations/{loc['slug']}/" for loc in LOCATIONS]
    urls += [f"/blog/{post['slug']}/" for post in BLOG_POSTS]
    urls += [
        f"/{loc['slug']}-{svc['slug']}/"
        for loc in LOCATIONS for svc in SEO_SERVICES
    ]
    urls += ["/local/"]

    entries = "\n".join(
        f'  <url><loc>{url(u)}</loc><changefreq>monthly</changefreq><priority>{"1.0" if u == "/" else "0.8"}</priority></url>'
        for u in urls
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        '</urlset>\n'
    )
    (ROOT / "sitemap.xml").write_text(body, encoding="utf-8")
    print("  wrote sitemap.xml")

def robots():
    body = dedent(f"""\
        User-agent: *
        Allow: /

        Sitemap: {SITE_URL}/sitemap.xml
        """)
    (ROOT / "robots.txt").write_text(body, encoding="utf-8")
    print("  wrote robots.txt")

# -------- main ------------------------------------------------------------

def main():
    print("Building Coles Law Firm site...")
    home_page()
    about_page()
    team_index_page()
    for t in TEAM:
        team_member_page(t)
    practice_index_page()
    for s in PRACTICES:
        practice_detail_page(s)
    locations_index_page()
    for loc in LOCATIONS:
        location_detail_page(loc)
    contact_page()
    faq_page()
    blog_page()
    for post in BLOG_POSTS:
        blog_post_page(post)
    what_to_expect_page()
    resources_index_page()
    checklist_page()
    for loc in LOCATIONS:
        for svc in SEO_SERVICES:
            service_city_page(svc, loc)
    local_index_page()
    not_found_page()
    sitemap()
    robots()
    print("Done.")

if __name__ == "__main__":
    main()

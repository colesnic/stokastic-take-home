#!/usr/bin/env python3
"""Build the Coles Law Firm static site.

Single source of truth for all page content, navigation, and structured
data. Run with `python3 build.py` from inside the coleslawfirm-site/
directory; pages are written in-place alongside this script.
"""
from __future__ import annotations
import json
import os
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
    {
        "slug": "nicholas-coles",
        "name": "Nicholas Coles",
        "role": "Technology & Software Consultant",
        "initial": "N",
        "short": "Nicholas advises the firm on technology, software, and process automation while pursuing his computer science degree.",
        "long": [
            "Nicholas Coles supports Coles Law, PLLC as the firm's technology and software consultant. He focuses on identifying tools and automations that let the legal team spend more time with clients and less time on administrative work.",
            "Nicholas is currently studying computer science at the University of Michigan and has prior internship experience in marketing and software engineering, including time at the AI startup Knowbl.",
        ],
        "credentials": [
            ("Education", "B.S., Computer Science (in progress) — University of Michigan"),
            ("Prior Work", "Software engineering intern at Knowbl; marketing internships with local businesses"),
        ],
    },
    {
        "slug": "mariya-jahan",
        "name": "Mariya Jahan",
        "role": "Data Entry & Client Outreach Intern",
        "initial": "M",
        "short": "Mariya supports the firm's client outreach and recordkeeping while preparing for a future career in immigration law.",
        "long": [
            "Mariya Jahan handles client outreach and data entry for Coles Law, PLLC, helping the firm stay organized and responsive across all seven Michigan offices.",
            "She is currently studying Politics, Philosophy, and Economics at the University of Michigan and plans to attend law school with the goal of practicing immigration law.",
        ],
        "credentials": [
            ("Education", "B.A., Politics, Philosophy & Economics (in progress) — University of Michigan"),
            ("Goal", "Pursuing law school with a focus on immigration law"),
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
        "slug": "guardianships",
        "name": "Guardianships",
        "icon": "G",
        "tagline": "Protect the vulnerable members of your family.",
        "summary": "Establish guardianship to protect the vulnerable members of your family with compassionate, court-tested counsel.",
        "body": [
            "When a loved one cannot safely make decisions for themselves — due to age, illness, disability, or injury — a guardianship or conservatorship may be the right legal protection.",
            "We represent families through every step: filing the petition, attending court hearings, and meeting the ongoing reporting requirements that come with serving as guardian or conservator.",
        ],
        "benefits": [
            "Adult guardianships and conservatorships",
            "Guardianships for minors",
            "Court petitions, hearings, and reporting",
            "Less restrictive alternatives where appropriate",
            "Coordination with care providers and family members",
        ],
    },
    {
        "slug": "probate-estates",
        "name": "Probate Estates",
        "icon": "P",
        "tagline": "Compassionate guidance through a difficult process.",
        "summary": "Simplify the probate process with expert guidance through every step of administering a loved one's estate.",
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
        "slug": "lansing",
        "name": "Lansing",
        "street": "120 N. Washington",
        "suite": None,
        "city": "Lansing",
        "state": "MI",
        "zip": "48933",
        "is_main": False,
        "blurb": "Downtown Lansing office serving Ingham County and Michigan's capital region.",
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

TESTIMONIALS = [
    {
        "author": "John Pellegrini",
        "text": "We've had excellent advice from Jen. She is fantastic at explaining how estates, wills, trusts, and deeds are created, as well as what all the terminology means. She also helped us with advice on other issues that come up, and how to prepare an estate trust so that everything is covered properly. We highly recommend her!",
    },
    {
        "author": "Rebecca Kitchen",
        "text": "Jennifer prepared my estate documents for me. She was very patient in explaining everything to me, and I felt great peace of mind that everything had been covered completely. She was very knowledgeable about MI probate law, and helped me make informed choices regarding my estate. Very calm and pleasant to work with!",
    },
    {
        "author": "Coach Mason",
        "text": "My wife and I just finished up our last will and testament and trust documents. We cannot recommend Jennifer and Brian more. They are very thorough and knowledgeable. They made the creation of our family trust a painless process. They even came to us in Ann Arbor.",
    },
    {
        "author": "Sarah F.",
        "text": "We had an excellent experience with Jennifer. Very thorough, professional and detailed. Would highly recommend working with her for any of your legal needs!",
    },
    {
        "author": "Matthew Marvin",
        "text": "We needed to set up a will and trust. Usually this is arduous and boring. Coles Law made the process easy, understandable, and even enjoyable. I would definitely recommend their services!",
    },
    {
        "author": "Verified Google Review",
        "text": "Getting an estate plan was easier than I thought. I should have done this years ago! Excellent attorney. I met with Jennifer Coles to get a will, power of attorney and patient advocate made. She discussed my options and explained how every document worked. It was a smooth process from start to finish.",
    },
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
            <div class="kicker">Offices in Grand Rapids &middot; Ann Arbor &middot; Lansing &middot; Kalamazoo &middot; Battle Creek &middot; Muskegon &middot; Newaygo</div>
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
            <div class="strip-item"><span class="dot"></span><strong>Avvo Client's Choice</strong> Award Recipient</div>
            <div class="strip-item"><span class="dot"></span><strong>Distinguished Peer Rated</strong></div>
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
                  <div class="stat"><div class="num">1,000s</div><div class="label">Families Served</div></div>
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
            <p>We serve clients across Michigan from offices in Grand Rapids, Ann Arbor, Lansing, Kalamazoo, Battle Creek, Muskegon, and Newaygo. For clients who can't easily travel, we offer secure video consultations and, when appropriate, in-home visits.</p>

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
            <h2>Ready to begin?</h2>
            <p>The earliest stages of estate planning are usually the most consequential. Schedule a free consultation and we'll talk through whether {s['name']} is the right fit for your situation, or whether a different starting point makes more sense.</p>
            <p><a href="{rel(depth, 'contact/')}">Schedule a consultation &rarr;</a></p>
          </article>
        </div>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page(f"practice-areas/{s['slug']}/index.html", head(title, desc, f"/practice-areas/{s['slug']}/", depth, [bc_schema, service_schema(s)]) + "\n" + body)

def locations_index_page():
    depth = 1
    title = "Office Locations | Coles Law Firm | 7 Michigan Offices"
    desc = "Coles Law Firm offices across Michigan: Grand Rapids, Ann Arbor, Lansing, Kalamazoo, Battle Creek, Muskegon, and Newaygo. Schedule a visit today."
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
    suite = f"<br>{loc['suite']}" if loc['suite'] else ""
    body = dedent(f"""\
        <body>
        {site_header('locations', depth)}
        {bc_html}
        <main id="main">
        <section class="location-detail">
          <div class="container">
            <div class="location-detail-grid">
              <div>
                <div class="city-label">{city_state} Office</div>
                <h1>{loc['name']} Estate Planning Attorneys</h1>
                <p style="font-size: 18px; color: var(--ink-soft); margin: 16px 0 24px;">{loc['blurb']}</p>
                <address>
                  {loc['street']}{suite}<br>
                  {loc['city']}, {loc['state']} {loc['zip']}
                </address>
                <p>Our {loc['name']} office offers the full range of Coles Law Firm services, including:</p>
                <ul>
                  <li>Revocable living trusts and trust funding</li>
                  <li>Wills, codicils, and probate</li>
                  <li>Powers of attorney and patient advocate designations</li>
                  <li>Elder law, Medicaid planning, and guardianships</li>
                </ul>
                <p>Call us at <a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a> to schedule a visit, or use our <a href="{rel(depth, 'contact/')}">contact form</a> to request a consultation.</p>
              </div>
              <aside class="location-card-side">
                <h3>Office Information</h3>
                <div class="meta-line"><strong>Phone</strong><a href="tel:{FIRM_PHONE_TEL}">{FIRM_PHONE}</a></div>
                <div class="meta-line"><strong>Email</strong><a href="mailto:{FIRM_EMAIL}">{FIRM_EMAIL}</a></div>
                <div class="meta-line"><strong>Hours</strong>Monday &ndash; Friday, 9:00 AM &ndash; 5:00 PM</div>
                <div class="meta-line"><strong>Address</strong>{loc['street']}{', ' + loc['suite'] if loc['suite'] else ''}, {city_state} {loc['zip']}</div>
                <p style="margin-top: 24px;"><a href="{rel(depth, 'contact/')}" class="loc-link" style="color: var(--gold-soft); display: inline-block;">Schedule a consultation &rarr;</a></p>
              </aside>
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
        <section>
          <div class="container">
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
            <p style="text-align: center; color: var(--ink-soft); font-size: 17px; max-width: 640px; margin: 0 auto 32px;">New posts coming soon. In the meantime, our <a href="{rel(depth, 'faq/')}">FAQ</a> covers many of the questions clients ask most often.</p>
            <p style="text-align: center;"><a href="{rel(depth, 'contact/')}" class="btn btn-dark">Schedule a Consultation</a></p>
          </div>
        </section>
        </main>
        {site_footer(depth)}
        </body>
        </html>
        """).rstrip()
    page("blog/index.html", head(title, desc, "/blog/", depth, [bc_schema]) + "\n" + body)

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
    ]
    urls += [f"/team/{t['slug']}/" for t in TEAM]
    urls += [f"/practice-areas/{p['slug']}/" for p in PRACTICES]
    urls += [f"/locations/{loc['slug']}/" for loc in LOCATIONS]

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
    sitemap()
    robots()
    print("Done.")

if __name__ == "__main__":
    main()

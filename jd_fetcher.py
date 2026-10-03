"""LinkedIn job search and JD fetching.

Two search modes:
  - Guest  : public jobs-guest API, no login needed (default fallback).
  - Auth   : LinkedIn voyager API using the user's li_at session cookie.
             Gives access to more jobs and better filters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

LINKEDIN_GUEST_API = (
    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
)
LINKEDIN_SEARCH_API = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_VOYAGER_SEARCH = (
    "https://www.linkedin.com/voyager/api/jobs/jobPostings"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# LinkedIn workplace-type filter (f_WT):
#   1 = on-site, 2 = remote, 3 = hybrid (combine with commas)
WORKPLACE_TYPE = {"on-site": "1", "remote": "2", "hybrid": "3"}

DATE_POSTED = {
    "Any time": "",
    "Past 24 hours": "r86400",
    "Past week": "r604800",
    "Past month": "r2592000",
}

EXPERIENCE_LEVEL = {
    "Any level": "",
    "Internship": "1",
    "Entry level": "2",
    "Associate": "3",
    "Mid-Senior": "4",
    "Director": "5",
    "Executive": "6",
}

JOB_TYPE = {
    "Any type": "",
    "Full-time": "F",
    "Part-time": "P",
    "Contract": "C",
    "Temporary": "T",
}

# Europe-focused country list shown in the search UI (display name -> lookup key for GEO_IDS)
EUROPE_COUNTRIES: list[tuple[str, str]] = [
    ("All Europe",   "europe"),
    ("Netherlands",  "netherlands"),
    ("Germany",      "germany"),
    ("Belgium",      "belgium"),
    ("Sweden",       "sweden"),
    ("Poland",       "poland"),
    ("United Kingdom", "united kingdom"),
    ("France",       "france"),
    ("Spain",        "spain"),
    ("Italy",        "italy"),
    ("Switzerland",  "switzerland"),
    ("Austria",      "austria"),
    ("Denmark",      "denmark"),
    ("Finland",      "finland"),
    ("Norway",       "norway"),
    ("Portugal",     "portugal"),
    ("Ireland",      "ireland"),
    ("Czech Republic", "czech republic"),
    ("Hungary",      "hungary"),
    ("Romania",      "romania"),
    ("Greece",       "greece"),
    ("Croatia",      "croatia"),
    ("Slovakia",     "slovakia"),
    ("Bulgaria",     "bulgaria"),
    ("Luxembourg",   "luxembourg"),
    ("Estonia",      "estonia"),
    ("Latvia",       "latvia"),
    ("Lithuania",    "lithuania"),
]

# LinkedIn geo IDs for countries and major cities.
# Without these, the guest API often ignores the location text and returns US jobs.
GEO_IDS: dict[str, str] = {
    # Europe (continent-level)
    "europe": "91000002",
    # Europe
    "netherlands": "102890719",
    "netherland": "102890719",
    "the netherlands": "102890719",
    "the netherland": "102890719",
    "holland": "102890719",
    "germany": "101282230",
    "deutschland": "101282230",
    "united kingdom": "101165590",
    "uk": "101165590",
    "great britain": "101165590",
    "france": "105015875",
    "spain": "105646813",
    "italy": "103350119",
    "belgium": "100565514",
    "switzerland": "106693272",
    "austria": "102671564",
    "poland": "105072130",
    "sweden": "105117694",
    "norway": "103819153",
    "denmark": "104514075",
    "finland": "100456013",
    "portugal": "100364837",
    "ireland": "104738515",
    "greece": "104677530",
    "czech republic": "104508036",
    "czechia": "104508036",
    "hungary": "100288700",
    "romania": "106670623",
    "ukraine": "102264497",
    "russia": "101728204",
    "turkey": "102105699",
    "luxembourg": "104042105",
    "slovakia": "103119917",
    "croatia": "104688944",
    "bulgaria": "105333783",
    "serbia": "101855366",
    "slovenia": "105010403",
    "estonia": "102974008",
    "latvia": "104456144",
    "lithuania": "101464403",
    "iceland": "105238872",
    "malta": "101673588",
    "cyprus": "104796023",
    "belarus": "101705918",
    "moldova": "107610853",
    "albania": "102819819",
    "bosnia and herzegovina": "103783135",
    "bosnia": "103783135",
    # Middle East
    "united arab emirates": "104305776",
    "uae": "104305776",
    "saudi arabia": "102867421",
    "ksa": "102867421",
    "qatar": "104723623",
    "kuwait": "104427440",
    "bahrain": "103379899",
    "oman": "102138449",
    "israel": "101620260",
    "jordan": "101165612",
    "lebanon": "100358611",
    "iraq": "106137774",
    "iran": "102845660",
    # Asia Pacific
    "india": "102713980",
    "singapore": "102454443",
    "japan": "101355337",
    "china": "102890883",
    "south korea": "105149562",
    "korea": "105149562",
    "australia": "101452733",
    "new zealand": "105490917",
    "indonesia": "102478259",
    "malaysia": "102308553",
    "philippines": "103121230",
    "thailand": "105570816",
    "vietnam": "104195383",
    "pakistan": "102257968",
    "bangladesh": "103509549",
    "sri lanka": "103055002",
    "nepal": "104793167",
    "hong kong": "103291313",
    "taiwan": "104187078",
    "cambodia": "104305776",
    "myanmar": "104305776",
    # Africa
    "south africa": "104035573",
    "nigeria": "101011623",
    "egypt": "106139199",
    "kenya": "101126702",
    "ghana": "105153323",
    "ethiopia": "104512481",
    "tanzania": "104475697",
    "uganda": "100996484",
    "morocco": "102757184",
    "tunisia": "102890565",
    "algeria": "104515968",
    # Americas
    "united states": "103644278",
    "usa": "103644278",
    "us": "103644278",
    "america": "103644278",
    "canada": "101174742",
    "brazil": "106057199",
    "brasil": "106057199",
    "mexico": "103323778",
    "argentina": "100446943",
    "colombia": "100876405",
    "chile": "104621616",
    "peru": "102927786",
    "venezuela": "101490751",
    "ecuador": "106373129",
    "uruguay": "104765234",
    "panama": "105688110",
    "guatemala": "100877388",
    "costa rica": "101726397",
    # Major cities
    "amsterdam": "102011674",
    "rotterdam": "100446922",
    "berlin": "106967700",
    "munich": "106967700",
    "hamburg": "106967700",
    "london": "102257491",
    "paris": "105015875",
    "madrid": "100994331",
    "barcelona": "100994331",
    "milan": "103350119",
    "rome": "103350119",
    "dubai": "106204383",
    "abu dhabi": "104305776",
    "toronto": "101174742",
    "vancouver": "101174742",
    "sydney": "105467446",
    "melbourne": "101452733",
    "new york": "103644278",
    "san francisco": "103644278",
    "remote": "105763813",
}


@dataclass
class JobListing:
    id: str
    title: str
    company: str
    location: str
    posted: str
    url: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "posted": self.posted,
            "url": self.url,
        }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _resolve_geo(loc: str) -> str | None:
    key = loc.strip().lower()
    return GEO_IDS.get(key) or GEO_IDS.get(key.rstrip("s"))


def _get_csrf(li_at: str) -> str:
    """Fetch LinkedIn home page with li_at to extract JSESSIONID (csrf token)."""
    resp = requests.get(
        "https://www.linkedin.com/",
        headers={"User-Agent": UA},
        cookies={"li_at": li_at},
        timeout=15,
    )
    jsessionid = resp.cookies.get("JSESSIONID", "")
    return jsessionid.strip('"')


def search_linkedin_jobs_authenticated(
    keywords: str,
    location: str = "",
    workplace_types: list[str] | None = None,
    date_posted: str = "",
    experience_level: str = "",
    job_type: str = "",
    limit: int = 25,
    li_at: str = "",
) -> list[dict]:
    """Search LinkedIn using the voyager API with li_at session cookie."""
    csrf = _get_csrf(li_at)
    geo_id = _resolve_geo(location) if location else None

    f_wt = ",".join(WORKPLACE_TYPE[w] for w in (workplace_types or []) if w in WORKPLACE_TYPE)

    filters: list[str] = []
    if f_wt:
        filters.append(f"f_WT->{f_wt}")
    if date_posted:
        filters.append(f"f_TPR->{date_posted}")
    if experience_level:
        filters.append(f"f_E->{experience_level}")
    if job_type:
        filters.append(f"f_JT->{job_type}")

    collected: list[JobListing] = []
    seen_ids: set[str] = set()
    start = 0

    while len(collected) < limit:
        params: dict[str, str] = {
            "decorationId": "com.linkedin.voyager.deco.jobs.web.shared.WebLimitedJobPosting-65",
            "q": "jsKeywordMatch",
            "keywords": keywords,
            "start": str(start),
            "count": "25",
        }
        if geo_id:
            params["locationUnion"] = f"(geoId:{geo_id})"
        elif location:
            params["location"] = location
        if filters:
            params["selectedFilters"] = ",".join(filters)

        try:
            resp = requests.get(
                LINKEDIN_VOYAGER_SEARCH,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/vnd.linkedin.normalized+json+2.1",
                    "csrf-token": csrf,
                    "x-restli-protocol-version": "2.0.0",
                },
                cookies={"li_at": li_at, "JSESSIONID": f'"{csrf}"'},
                timeout=20,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Network error: {e}") from e

        if resp.status_code in (401, 403):
            raise RuntimeError("LinkedIn session expired or invalid. Please update your li_at cookie.")
        if resp.status_code == 429:
            raise RuntimeError("LinkedIn rate-limited (429). Wait a few minutes.")
        if resp.status_code != 200:
            raise RuntimeError(f"LinkedIn voyager API returned HTTP {resp.status_code}.")

        data = resp.json()
        elements = (
            data.get("data", {}).get("elements", [])
            or data.get("elements", [])
        )
        if not elements:
            break

        for el in elements:
            job_id = str(el.get("jobPostingId") or el.get("entityUrn", "").split(":")[-1])
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            title = el.get("title", "")
            company = (el.get("companyDetails") or {}).get("company", {}).get("name", "") \
                      or el.get("formattedLocation", "")
            loc = el.get("formattedLocation", "") or el.get("location", "")
            posted = el.get("listedAt", "") or el.get("postedAt", "")
            url = f"https://www.linkedin.com/jobs/view/{job_id}"
            collected.append(JobListing(id=job_id, title=title, company=company,
                                        location=loc, posted=str(posted), url=url))
            if len(collected) >= limit:
                break

        if len(elements) < 25:
            break
        start += 25

    return [j.to_dict() for j in collected[:limit]]


def search_linkedin_jobs(
    keywords: str,
    location: str = "",
    workplace_types: list[str] | None = None,
    date_posted: str = "",
    experience_level: str = "",
    job_type: str = "",
    limit: int = 25,
    li_at: str = "",
) -> list[dict]:
    """Search LinkedIn job listings.

    Uses authenticated voyager API if li_at is provided, otherwise falls back
    to the public guest API.
    """
    if not keywords or not keywords.strip():
        raise ValueError("keywords is required")

    if li_at.strip():
        try:
            return search_linkedin_jobs_authenticated(
                keywords=keywords, location=location,
                workplace_types=workplace_types, date_posted=date_posted,
                experience_level=experience_level, job_type=job_type,
                limit=limit, li_at=li_at.strip(),
            )
        except RuntimeError:
            raise
        except Exception:
            pass  # fall through to guest API

    # --- Guest API fallback ---
    f_wt = ",".join(WORKPLACE_TYPE[w] for w in (workplace_types or []) if w in WORKPLACE_TYPE)
    geo_id = _resolve_geo(location) if location else None

    collected: list[JobListing] = []
    seen_ids: set[str] = set()
    start = 0
    page_size = 25

    while len(collected) < limit:
        params: dict[str, str] = {"keywords": keywords, "start": str(start)}
        if geo_id:
            params["geoId"] = geo_id
        elif location:
            params["location"] = location
        if f_wt:
            params["f_WT"] = f_wt
        if date_posted:
            params["f_TPR"] = date_posted
        if experience_level:
            params["f_E"] = experience_level
        if job_type:
            params["f_JT"] = job_type

        try:
            resp = requests.get(
                LINKEDIN_SEARCH_API, params=params,
                headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                timeout=20,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Network error contacting LinkedIn: {e}") from e

        if resp.status_code == 429:
            raise RuntimeError("LinkedIn rate-limited (429). Wait a few minutes and try again.")
        if resp.status_code != 200:
            raise RuntimeError(
                f"LinkedIn search returned HTTP {resp.status_code}. "
                "Try again or paste a JD directly."
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        page_jobs = _parse_search_results(soup)
        if not page_jobs:
            break

        new_jobs = [j for j in page_jobs if j.id not in seen_ids]
        if not new_jobs:
            break

        for job in new_jobs:
            seen_ids.add(job.id)
            collected.append(job)
            if len(collected) >= limit:
                break

        start += page_size

    return [j.to_dict() for j in collected[:limit]]


def _parse_search_results(soup: BeautifulSoup) -> list[JobListing]:
    jobs: list[JobListing] = []

    # Each card is either a <li> or <div> with data-entity-urn pointing at jobPosting
    for el in soup.find_all(attrs={"data-entity-urn": True}):
        urn = el.get("data-entity-urn", "")
        m = re.search(r"jobPosting:(\d+)", urn)
        if not m:
            continue
        job_id = m.group(1)

        title_el = el.select_one(".base-search-card__title") or el.select_one("h3")
        company_el = (
            el.select_one(".base-search-card__subtitle a")
            or el.select_one(".base-search-card__subtitle")
            or el.select_one("h4")
        )
        location_el = el.select_one(".job-search-card__location")
        time_el = el.select_one("time")
        link_el = el.select_one("a.base-card__full-link") or el.select_one("a")

        url = (
            link_el.get("href").split("?")[0]
            if link_el and link_el.get("href")
            else f"https://www.linkedin.com/jobs/view/{job_id}"
        )

        jobs.append(
            JobListing(
                id=job_id,
                title=(title_el.get_text(strip=True) if title_el else ""),
                company=(company_el.get_text(strip=True) if company_el else ""),
                location=(location_el.get_text(strip=True) if location_el else ""),
                posted=(time_el.get_text(strip=True) if time_el else ""),
                url=url,
            )
        )
    return jobs


# ---------------------------------------------------------------------------
# Single-JD fetch
# ---------------------------------------------------------------------------
def _extract_linkedin_job_id(url: str) -> str | None:
    patterns = [
        r"/jobs/view/(\d+)",
        r"currentJobId=(\d+)",
        r"jobPosting/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def fetch_jd_by_id(job_id: str) -> str:
    resp = requests.get(
        LINKEDIN_GUEST_API.format(job_id=job_id),
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        timeout=20,
    )
    if resp.status_code == 429:
        raise RuntimeError("LinkedIn rate-limited (429). Try again shortly.")
    if resp.status_code != 200:
        raise RuntimeError(
            f"LinkedIn returned HTTP {resp.status_code} for job {job_id}. "
            "Open the posting in your browser, copy the JD, and paste it instead."
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    description = soup.select_one(".show-more-less-html__markup") or soup.select_one(
        ".description__text"
    )
    title_el = soup.select_one(".top-card-layout__title") or soup.select_one("h1")
    company_el = soup.select_one(".topcard__org-name-link") or soup.select_one(
        ".topcard__flavor"
    )
    loc_el = soup.select_one(".topcard__flavor--bullet")
    workplace_el = soup.select_one(".topcard__flavor--workplace-type")

    parts: list[str] = []
    if title_el:
        parts.append(f"Title: {title_el.get_text(strip=True)}")
    if company_el:
        parts.append(f"Company: {company_el.get_text(strip=True)}")
    if loc_el:
        parts.append(f"Location: {loc_el.get_text(strip=True)}")
    if workplace_el:
        parts.append(f"Workplace: {workplace_el.get_text(strip=True)}")
    if description:
        parts.append("\n" + description.get_text("\n", strip=True))

    if not parts or not description:
        raise RuntimeError(
            "Could not parse LinkedIn job posting. Open the posting in your browser, "
            "copy the description, and paste it instead."
        )
    return "\n".join(parts)


def fetch_jd(url_or_text: str) -> str:
    text = url_or_text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        if "linkedin.com" in text:
            job_id = _extract_linkedin_job_id(text)
            if not job_id:
                raise ValueError(
                    "Could not extract a LinkedIn job ID from the URL. "
                    "Paste the JD text instead."
                )
            return fetch_jd_by_id(job_id)
        resp = requests.get(text, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup(["script", "style", "nav", "header", "footer"]):
            el.decompose()
        return soup.get_text("\n", strip=True)
    return text

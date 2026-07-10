import os
import json
import logging
import re
import hashlib
import html
import smtplib
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Any
from dataclasses import dataclass
from html.parser import HTMLParser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin, urlparse
import requests
from dotenv import load_dotenv

load_dotenv()

# Production Log formatting configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

DISCOVERY_TERMS = [
    "tender", "rfp", "request for proposal", "request for quotation",
    "rfq", "eoi", "expression of interest", "consultancy",
    "procurement", "bid", "opportunity", "invitation to tender", "call for proposals",
]


class PortalHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.meta_published_time = ""
        self.meta_site_name = ""
        self.links = []
        self.text_blocks = []
        self._capture_tag = None
        self._capture_href = None
        self._buffer = []

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._capture_href = attrs.get("href")
            self._buffer = []
        elif tag in {"title", "h1", "h2", "h3", "p", "li"}:
            self._capture_tag = tag
            self._buffer = []
        elif tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            content = self._clean(attrs.get("content", ""))
            if name in {"description", "og:description",
                        "twitter:description"} and content and not self.meta_description:
                self.meta_description = content
            elif name in {"article:published_time", "og:updated_time", "date", "dc.date",
                          "pubdate"} and content and not self.meta_published_time:
                self.meta_published_time = content
            elif name in {"og:site_name", "application-name"} and content and not self.meta_site_name:
                self.meta_site_name = content

    def handle_data(self, data):
        if self._capture_tag or self._capture_href:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._capture_href:
            text = self._clean(" ".join(self._buffer))
            if text or self._capture_href:
                self.links.append({"href": self._capture_href, "text": text})
            self._capture_href = None
            self._buffer = []
        elif tag == self._capture_tag:
            text = self._clean(" ".join(self._buffer))
            if text:
                if tag == "title" and not self.title:
                    self.title = text
                else:
                    self.text_blocks.append(text)
            self._capture_tag = None
            self._buffer = []

    def close(self):
        super().close()


@dataclass
class TenderOpportunity:
    id: str
    title: str
    company: str
    country: str
    description: str
    apply_url: str
    source_portal: str
    posted_at: datetime


class StudioAturiProcurementHunter:
    def __init__(self):
        self.target_email = "nguginsons@gmail.com"
        self.history_file = "processed_jobs.json"

        self.http_timeout = 20
        self.http_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        }

        self.country_profiles = {
            "Kenya": {
                "keywords": ["Corporate Brand Strategy", "Brand Mergers & Acquisitions", "Fintech Identity",
                             "Financial Services Branding", "FMCG Packaging Design", "Product SKU Design",
                             "Consumer Insights", "Market Discovery", "Corporate Identity Guidelines", "Brand Manual",
                             "Value Proposition Development", "Stakeholder Perception Survey"],
                "urls": ["https://tenderflow.co.ke", "https://developmentaid.org",
                         "https://www.safaricom.co.ke/suppliers/tenders", "https://eastafricatenders.com"]
            },
            "Uganda": {
                "keywords": ["Brand Audit & Diagnostic", "Corporate Profile", "Visual Identity Review",
                             "Customer Experience Strategy", "CX Strategy", "Audience Profiling",
                             "NGO Campaign Branding", "Commercial Product Packaging"],
                "urls": ["https://tenders.unp.me", "https://kazitenders.co.ug", "https://ungm.org"]
            },
            "Tanzania": {
                "keywords": ["Corporate Image", "Reputation Management", "Brand Architecture Development",
                             "Strategic Positioning", "Private Sector Packaging Design",
                             "Insurance & Pensions Private Fund Communication", "Rollout Management",
                             "Brand Launch Activation"],
                "urls": ["https://tanzaniatenders.com", "https://zoomtanzania.com"]
            },
            "Rwanda": {
                "keywords": ["Digital Transformation Branding", "Tech Brand Strategy", "Service Design",
                             "Product Innovation", "Design Thinking Framework", "Human-Centered Design Research",
                             "HCD Research", "Brand Advisory Services", "Organizational Rebranding",
                             "Perception Mapping"],
                "urls": ["https://jobinrwanda.com/tenders", "https://psf.org.rw"]
            },
            "Congo": {
                "keywords": ["Refonte de l'Identité Visuelle", "Identité Corporative", "Stratégie de Marque",
                             "Conception d’Emballage FMCG", "Communication de Changement de Culture",
                             "Creative Direction", "Brand Asset Management"],
                "urls": ["https://mediacongo.net", "https://congovirtuel.com"]
            },
            "Dubai": {
                "keywords": ["Brand Positioning", "Naming Architecture", "Brand Advisory", "Strategy Pivot",
                             "Luxury Packaging Design", "Advanced Marketing", "Creative Strategy",
                             "Customer Experience Strategy", "Journey Mapping", "Value Proposition Development",
                             "Fintech Identity"],
                "urls": ["https://tenderuae.com", "https://tejari.com"]
            },
            "Ethiopia": {
                "keywords": ["Corporate Rebranding and Strategy", "Brand Architecture", "Identity Manual",
                             "Consumer Insights", "Audience Profiling", "Export Product SKU Design",
                             "Strategic Positioning"],
                "urls": ["https://tenders.2merkato.com", "https://thereporterethiopia.com"]
            }
        }
        self.processed_tender_ids = self._load_history()

    def _load_history(self) -> Set[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return set(json.load(f))
            except Exception as e:
                logging.error(f"Error reading history file: {e}")
        return set()

    def _save_history(self):
        try:
            with open(self.history_file, 'w') as f:
                json.dump(list(self.processed_tender_ids), f)
        except Exception as e:
            logging.error(f"Error persisting history file: {e}")

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()

    def _fetch_url(self, url: str) -> str:
        response = requests.get(url, headers=self.http_headers, timeout=self.http_timeout)
        response.raise_for_status()
        return response.text

    def _portal_name(self, url: str, country: str) -> str:
        hostname = urlparse(url).netloc.replace("www.", "")
        return hostname or url

    def _parse_datetime(self, value: str) -> datetime | None:
        if not value:
            return None
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%d/%m/%Y",
                    "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        return None

    def _looks_relevant(self, text: str, country_keywords: List[str]) -> bool:
        haystack = self._clean_text(text).lower()
        if not haystack:
            return False
        if any(term in haystack for term in DISCOVERY_TERMS):
            return True
        return any(keyword.lower() in haystack for keyword in country_keywords)

    def _extract_text_snippet(self, parser: PortalHTMLParser, limit: int = 4) -> str:
        blocks = [block for block in parser.text_blocks if block]
        if not blocks:
            return parser.meta_description or ""
        return " ".join(blocks[:limit])

    def _build_tender_id(self, country: str, apply_url: str, title: str) -> str:
        basis = f"{country}|{apply_url}|{title}".encode("utf-8", errors="ignore")
        return hashlib.sha1(basis).hexdigest()[:16]

    def _scrape_portal(self, portal_url: str, country: str, country_keywords: List[str]) -> List[TenderOpportunity]:
        opportunities: List[TenderOpportunity] = []
        logging.info(f"Scraping portal channel: {portal_url} ({country})")
        try:
            listing_html = self._fetch_url(portal_url)
        except Exception as exc:
            logging.warning(f"Could not fetch portal {portal_url}: {exc}")
            return opportunities

        listing_parser = PortalHTMLParser()
        listing_parser.feed(listing_html)
        listing_parser.close()

        candidate_links = []
        seen_links: Set[str] = set()
        listing_context = " ".join([
            listing_parser.title, listing_parser.meta_description, self._extract_text_snippet(listing_parser, limit=6)
        ])
        page_relevant = self._looks_relevant(listing_context, country_keywords)
        portal_host = urlparse(portal_url).netloc.replace("www.", "")

        for link in listing_parser.links:
            href = self._clean_text(link.get("href", ""))
            text = self._clean_text(link.get("text", ""))
            if not href:
                continue
            absolute_url = urljoin(portal_url, href)
            normalized_url = absolute_url.split("#", 1)[0]
            parsed_url = urlparse(normalized_url)
            if parsed_url.scheme not in {"http", "https"}:
                continue
            if portal_host and parsed_url.netloc.replace("www.", "") not in {portal_host, ""}:
                continue
            if normalized_url in seen_links:
                continue
            if page_relevant or self._looks_relevant(text, country_keywords) or self._looks_relevant(normalized_url,
                                                                                                     country_keywords):
                candidate_links.append((normalized_url, text))
                seen_links.add(normalized_url)

        if not candidate_links and page_relevant:
            candidate_links.append((portal_url, listing_parser.title or portal_url))

        for detail_url, anchor_text in candidate_links[:20]:
            try:
                detail_html = self._fetch_url(detail_url)
            except Exception:
                detail_html = listing_html if detail_url == portal_url else ""

            detail_parser = PortalHTMLParser()
            if detail_html:
                detail_parser.feed(detail_html)
                detail_parser.close()

            combined_title = self._clean_text(detail_parser.title or anchor_text or listing_parser.title or portal_url)
            combined_description = self._clean_text(
                " ".join(part for part in [detail_parser.meta_description, self._extract_text_snippet(detail_parser),
                                           listing_parser.meta_description] if part)
            )

            if not self._looks_relevant(f"{combined_title} {combined_description}", country_keywords):
                continue
            if not combined_title:
                continue

            posted_at = self._parse_datetime(detail_parser.meta_published_time) or self._parse_datetime(
                listing_parser.meta_published_time) or datetime.now(timezone.utc)
            if (datetime.now(timezone.utc) - posted_at) > timedelta(days=30):
                continue

            tender_id = self._build_tender_id(country, detail_url, combined_title)
            if tender_id in self.processed_tender_ids:
                continue

            company = detail_parser.meta_site_name or listing_parser.meta_site_name
            if not company:
                company = urlparse(detail_url).netloc.replace("www.", "") or self._portal_name(portal_url, country)

            opportunities.append(
                TenderOpportunity(
                    id=tender_id, title=combined_title, company=company, country=country,
                    description=combined_description or combined_title, apply_url=detail_url,
                    source_portal=urlparse(portal_url).netloc.replace("www.", "") or portal_url, posted_at=posted_at
                )
            )
        return opportunities

    def scrape_all_opportunities(self) -> List[TenderOpportunity]:
        found_tenders: List[TenderOpportunity] = []
        seen_ids: Set[str] = set()

        for country, profile in self.country_profiles.items():
            country_keywords = profile.get("keywords", [])
            for portal_url in profile.get("urls", []):
                discovered = self._scrape_portal(portal_url, country, country_keywords)
                for tender in discovered:
                    if tender.id in self.processed_tender_ids or tender.id in seen_ids:
                        continue
                    seen_ids.add(tender.id)
                    found_tenders.append(tender)

        logging.info(f"Total novel candidate opportunities discovered: {len(found_tenders)}")
        return found_tenders

    def generate_tender_intelligence(self, tender: TenderOpportunity) -> Dict[str, Any]:
        country_currency = {
            "Kenya": "KES",
            "Uganda": "UGX",
            "Tanzania": "TZS",
            "Rwanda": "RWF",
            "Congo": "CDF",
            "Dubai": "AED",
            "Ethiopia": "ETB",
        }
        currency = country_currency.get(tender.country, "USD")

        return {
            "clean_currency": currency,
            "rfp_reference_no": f"RFP-REF-{tender.id.upper()}",
            "client_address": f"{tender.company} procurement office",
            "summary_markdown": (
                f"- Country: {tender.country}\n"
                f"- Company: {tender.company}\n"
                f"- Source portal: {tender.source_portal}\n"
                f"- Posted at: {tender.posted_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"- Application URL: {tender.apply_url}"
            ),
            "response_angle_markdown": (
                f"1. Confirm fit against the stated scope.\n"
                f"2. Open with a concise capability note tailored to {tender.country}.\n"
                f"3. Attach or link the most relevant Studio Aturi work samples.\n"
                f"4. Ask for clarification on timeline, budget, and submission format."
            ),
            "key_actions_markdown": (
                f"- Review the opportunity text for submission requirements.\n"
                f"- Validate deadlines, contact details, and eligibility criteria.\n"
                f"- Prepare a short, direct response focused on outcomes and delivery."
            ),
            "notes_markdown": (
                "This email is generated without AI. It uses the portal metadata and a fixed response structure."
            ),
        }

    def send_production_email(self, smtp_session: smtplib.SMTP, sender_email: str, tender: TenderOpportunity,
                              intel: Dict[str, Any]):
        """Dispatches a detailed opportunity email over an active SMTP session."""
        bcc_env = os.getenv("BCC_EMAILS", "")
        bcc_list = [email.strip() for email in bcc_env.split(",") if email.strip()]

        email_extract = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', tender.description)
        direct_apply_email = email_extract[0] if email_extract else "Use submission links below"
        safe_description = html.escape(tender.description or "")

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = self.target_email
        msg['Subject'] = f"[SASAFRIK TENDER BOT FOUND NEW TENDER OPPORTUNITY] Lead Alert - {tender.country} ({tender.company})"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #1F2937; line-height: 1.5; margin: 0; padding: 24px; background-color: #F9FAFB;">
            <div style="max-width: 760px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; overflow: hidden;">
                <div style="background: #111827; padding: 20px 24px; color: #FFFFFF;">
                    <div style="font-size: 13px; letter-spacing: 0.04em; text-transform: uppercase; color: #93C5FD;">Studio Aturi Opportunity Alert</div>
                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 700;">{tender.title}</h1>
                </div>
                <div style="padding: 24px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                        <tr><td style="padding: 6px 0; width: 220px; color: #6B7280; font-weight: 600;">Company</td><td style="padding: 6px 0;">{tender.company}</td></tr>
                        <tr><td style="padding: 6px 0; color: #6B7280; font-weight: 600;">Country</td><td style="padding: 6px 0;">{tender.country}</td></tr>
                        <tr><td style="padding: 6px 0; color: #6B7280; font-weight: 600;">Portal</td><td style="padding: 6px 0;">{tender.source_portal}</td></tr>
                        <tr><td style="padding: 6px 0; color: #6B7280; font-weight: 600;">Reference</td><td style="padding: 6px 0;">{intel.get("rfp_reference_no")}</td></tr>
                        <tr><td style="padding: 6px 0; color: #6B7280; font-weight: 600;">Currency hint</td><td style="padding: 6px 0;">{intel.get("clean_currency")}</td></tr>
                    </table>

                    <h3 style="margin: 24px 0 10px 0; font-size: 16px;">Opportunity Summary</h3>
                    <pre style="white-space: pre-wrap; margin: 0; padding: 14px; background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px;">{intel.get("summary_markdown")}</pre>

                    <h3 style="margin: 24px 0 10px 0; font-size: 16px;">Source Description</h3>
                    <pre style="white-space: pre-wrap; margin: 0; padding: 14px; background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px;">{safe_description}</pre>

                    <h3 style="margin: 24px 0 10px 0; font-size: 16px;">Recommended Response</h3>
                    <pre style="white-space: pre-wrap; margin: 0; padding: 14px; background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px;">{intel.get("response_angle_markdown")}</pre>

                    <h3 style="margin: 24px 0 10px 0; font-size: 16px;">Next Actions</h3>
                    <pre style="white-space: pre-wrap; margin: 0; padding: 14px; background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px;">{intel.get("key_actions_markdown")}</pre>

                    <table style="width: 100%; margin-top: 22px; border-top: 1px solid #E5E7EB; padding-top: 16px;">
                        <tr><td style="padding: 4px 0; color: #6B7280; font-weight: 600;">Direct email detected</td><td style="padding: 4px 0;">{direct_apply_email}</td></tr>
                        <tr><td style="padding: 4px 0; color: #6B7280; font-weight: 600;">Portal link</td><td style="padding: 4px 0;"><a href="{tender.apply_url}" style="color: #2563EB; text-decoration: none;">{tender.apply_url}</a></td></tr>
                    </table>
                </div>
                <div style="padding: 14px 24px; background: #F9FAFB; border-top: 1px solid #E5E7EB; color: #6B7280; font-size: 12px;">{intel.get("notes_markdown")}</div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, 'html'))

        recipient_envelope = [self.target_email] + bcc_list
        smtp_session.sendmail(sender_email, recipient_envelope, msg.as_string())
        logging.info(f"[+] Detailed email dispatched for ID: {tender.id} (Bcc elements: {len(bcc_list)})")

    def run(self):
        opportunities = self.scrape_all_opportunities()

        print("\n" + "=" * 95)
        print(
            f" 🎯 STUDIO ATURI AUTOMATED PROCUREMENT MATRICES — RUN EXECUTED AT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 95)

        if not opportunities:
            logging.info("Zero pending matches to process. Closing tracking context.")
            return

        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        smtp_user = os.getenv("SMTP_SENDER_EMAIL")
        smtp_pass = os.getenv("SMTP_SENDER_PASSWORD")

        if not all([smtp_user, smtp_pass]):
            logging.critical("Mail pipeline aborted: Missing SMTP deployment keys in environment.")
            return

        # Initialize the persistent SMTP session pipeline context once
        logging.info(f"Opening shared TCP connection stream to target mail server: {smtp_server}:{smtp_port}")
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                logging.info("Shared SMTP socket verification authentication sequence complete.")

                for idx, tender in enumerate(opportunities, 1):
                    logging.info(f"Processing sequence node [{idx}/{len(opportunities)}] -> ID: {tender.id}")
                    intel = self.generate_tender_intelligence(tender)

                    print(f"\n⚡ [{idx}/{len(opportunities)}] TARGET TERRITORY IDENTIFIED: {tender.country.upper()}")
                    print(f"  ▪️ Opportunity ID : {tender.id}")
                    print(f"  ▪️ Business Entity : {tender.company}")
                    print(f"  ▪️ Pipeline Focus  : {tender.title}")
                    print(f"  ▪️ Intake Portal   : {tender.source_portal}")
                    print(f"  📧 Prepared detailed email content without AI or document generation.")

                    self.send_production_email(server, smtp_user, tender, intel)
                    print(f"  ↳ STATUS: Email dispatch completed.")
                    print("-" * 95)

                    self.processed_tender_ids.add(tender.id)
                    self._save_history()

                    # Proactive RPM/TPM Rate limit smoothing pacing anchor
                    time.sleep(2)

        except Exception as e:
            logging.critical(f"Global operational pipeline failure encountered: {e}")
            return

        print("\n" + "=" * 95)
        print(f" 📈 METRIC TERMINAL REPORT SUMMARY OUTCOME")
        print("=" * 95)
        print(f"  ✔️ Total Active Target Countries Tracked  : {len(self.country_profiles)}")
        print(f"  ✔️ Total Valid Match Opportunities Found  : {len(opportunities)}")
        print(f"  ✔️ Total Detailed Emails Sent            : {len(opportunities)}")
        print("=" * 95 + "\n")


if __name__ == "__main__":
    agent = StudioAturiProcurementHunter()
    agent.run()

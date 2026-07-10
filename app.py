import os
import json
import logging
import re
import hashlib
import zipfile
import smtplib
import time
import io
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Any
from dataclasses import dataclass
from html.parser import HTMLParser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from urllib.parse import urljoin, urlparse
import requests
from dotenv import load_dotenv

# Native Google GenAI SDK (google-genai==2.6.0)
from google import genai
from google.genai import types
from google.genai import errors

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
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            logging.error("CRITICAL: GEMINI_API_KEY environment variable is missing!")

        self.ai_client = genai.Client(api_key=gemini_key) if gemini_key else None
        # self.target_email = "nduhiu254@gmail.com"
        self.target_email = "nguginsons@gmail.com"
        self.history_file = "processed_jobs.json"

        self.fob_template = "Studio_Aturi_Form_of_Bid.docx"
        self.financial_template = "Studio_Aturi_Financial_Proposal.docx"
        self.nda_template = "Studio_Aturi_Mutual_NDA.docx"

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
        fallback_data = {
            "clean_currency": "USD", "phase1_cost": "1,500,000", "phase2_cost": "1,200,000",
            "phase3_cost": "2,000,000", "phase4_cost": "1,000,000", "total_cost": "5,700,000",
            "total_cost_words": "FIVE MILLION SEVEN HUNDRED THOUSAND",
            "rfp_reference_no": f"RFP-REF-{tender.id.upper()}",
            "client_address": "Main Commercial Enterprise Plaza",
            "application_steps_markdown": "1. Format submission envelope details.\n2. Dispatch proposal package elements.",
            "inferred_requirements_markdown": "• Strategic Advisory Discovery\n• Scaled Execution Rollout Plan",
            "inferred_details_markdown": "A comprehensive creative consulting delivery frame focused on long-term value realization profiles."
        }

        if not self.ai_client:
            return fallback_data

        prompt = f"""
        Analyze the following corporate RFP opportunity:
        Title: {tender.title}
        Company: {tender.company}
        Country: {tender.country}
        Description: {tender.description}

        Generate a structured JSON configuration layout containing metadata mappings to customize corporate template blocks.
        The extracted currency should follow localized context (e.g., KES for Kenya, AED for Dubai, USD for global NGOs).

        Return ONLY a JSON object matching this schema exactly:
        {{
           "clean_currency": "USD",
           "phase1_cost": "1,200,000",
           "phase2_cost": "950,000",
           "phase3_cost": "1,500,000",
           "phase4_cost": "800,000",
           "total_cost": "4,450,000",
           "total_cost_words": "FOUR MILLION FOUR HUNDRED AND FIFTY THOUSAND",
           "rfp_reference_no": "RFP-REF-7721",
           "client_address": "Corporate Business Office HQ",
           "application_steps_markdown": "Step 1: Core discovery evaluation\\nStep 2: Executive review submission",
           "inferred_requirements_markdown": "- Technical asset blueprint manual\\n- Production packaging designs",
           "inferred_details_markdown": "Deep descriptive summary analysis of the organizational scope transformation parameters"
        }}
        """

        max_retries = 3
        backoff_delay = 26

        for attempt in range(max_retries):
            try:
                response = self.ai_client.models.generate_content(
                    model='gemini-2.5-flash', contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.15)
                )
                return json.loads(response.text)
            except errors.APIError as e:
                if e.code == 429:
                    logging.warning(
                        f"Quota rate limit hit (429). Attempt {attempt + 1}/{max_retries}. Backing off for {backoff_delay}s...")
                    time.sleep(backoff_delay)
                else:
                    logging.error(f"APIError occurred processing {tender.id}: {e}")
                    break
            except Exception as e:
                logging.error(f"Unexpected parsing exception for {tender.id}: {e}")
                break

        logging.error(f"Failed to acquire Gemini metrics for {tender.id}. Using production fallback structures.")
        return fallback_data

    def process_docx_to_memory(self, template_path: str, intel: Dict[str, Any],
                               tender: TenderOpportunity) -> io.BytesIO | None:
        """Processes docx templates completely in memory, avoiding heavy local storage reads/writes."""
        if not os.path.exists(template_path):
            logging.error(f"Template path missing from system context: {template_path}")
            return None
        try:
            replacements = {
                "[Insert Date]": datetime.now().strftime("%B %d, %Y"),
                "[Insert RFP Ref No.]": intel.get("rfp_reference_no", "RFP-REF-GEN"),
                "[Insert Project Name (e.g., Corporate Rebranding & Strategy Advisory)]": tender.title,
                "[Insert Client Company Name & Procurement Committee Address]": f"{tender.company} - {intel.get('client_address', 'Main Corporate Office')}",
                "[INSERT CLIENT COMPANY NAME]": tender.company,
                "[Insert Country/Jurisdiction]": tender.country,
                "[Insert Address]": intel.get('client_address', 'Corporate Headquarters'),
                "[Insert Preferred Jurisdiction, e.g., the Republic of Kenya / Dubai (DIFC)]": f"the Republic of {tender.country}" if tender.country != "Dubai" else "Dubai (DIFC)",
                "[Insert Currency, e.g., KES / USD / AED]": intel.get("clean_currency", "USD"),
                "[Insert Currency and Total Numeric Amount]": f"{intel.get('clean_currency')} {intel.get('total_cost')}",
                "[Insert Amount in Words]": intel.get("total_cost_words", "SPECIFIED AMOUNT"),
                "[Insert Total]": intel.get("total_cost"),
                "[Insert Amount]": intel.get("phase1_cost", "As Agreed")
            }

            memory_buffer = io.BytesIO()
            with zipfile.ZipFile(template_path, 'r') as zin:
                with zipfile.ZipFile(memory_buffer, 'w', zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        if any(x in item.filename for x in ["document.xml", "header", "footer"]):
                            xml_content = data.decode('utf-8', errors='ignore')
                            for placeholder, replacement in replacements.items():
                                xml_content = xml_content.replace(placeholder, str(replacement))
                            data = xml_content.encode('utf-8')
                        zout.writestr(item, data)

            memory_buffer.seek(0)
            return memory_buffer
        except Exception as e:
            logging.error(f"Failed to generate in-memory structural template {template_path}: {e}")
            return None

    def create_informational_docx_in_memory(self, template_path: str, title: str,
                                            content_markdown: str) -> io.BytesIO | None:
        if not os.path.exists(template_path):
            return None
        try:
            clean_content = content_markdown.replace("\n", " ").replace('"', '\\"').replace("<", "&lt;").replace(">",
                                                                                                                 "&gt;")
            memory_buffer = io.BytesIO()
            with zipfile.ZipFile(template_path, 'r') as zin:
                with zipfile.ZipFile(memory_buffer, 'w', zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        if "document.xml" in item.filename:
                            document_wireframe = (
                                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                                '<w:body>'
                                '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>{doc_title}</w:t></w:r></w:p>'
                                '<w:p><w:r><w:t>{doc_content}</w:t></w:r></w:p>'
                                '</w:body></w:document>'
                            ).format(doc_title=title, doc_content=clean_content)
                            data = document_wireframe.encode('utf-8')
                        zout.writestr(item, data)
            memory_buffer.seek(0)
            return memory_buffer
        except Exception as e:
            logging.error(f"In-memory markdown document tracking failure: {e}")
            return None

    def send_production_email(self, smtp_session: smtplib.SMTP, sender_email: str, tender: TenderOpportunity,
                              intel: Dict[str, Any], memory_attachments: Dict[str, io.BytesIO]):
        """Dispatches email payloads securely over an active, persistent SMTP stream session."""
        bcc_env = os.getenv("BCC_EMAILS", "")
        bcc_list = [email.strip() for email in bcc_env.split(",") if email.strip()]

        email_extract = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', tender.description)
        direct_apply_email = email_extract[0] if email_extract else "Use submission links below"

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = self.target_email
        msg['Subject'] = f"🎯 [Match Found] Lead Alert - {tender.country} ({tender.company})"

        html_content = f"""
        <html>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #2D3748; line-height: 1.6; margin: 0; padding: 20px; background-color: #F7FAFC;">
            <div style="max-width: 650px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                <div style="background: #1A365D; padding: 25px; color: #FFFFFF; text-align: center;">
                    <h1 style="margin: 0; font-size: 22px; font-weight: 600; letter-spacing: 0.5px;">Studio Aturi Intelligence Pipeline</h1>
                    <p style="margin: 5px 0 0 0; color: #90CDF4; font-size: 14px; text-transform: uppercase; font-weight: bold;">Private Sector Match Confirmed</p>
                </div>
                <div style="padding: 30px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; width: 30%; color: #4A5568;">Territory Source</td>
                            <td style="padding: 8px 0; color: #1A202C;"><span style="background: #EBF8FF; color: #2B6CB0; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 13px;">{tender.country.upper()}</span></td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; color: #4A5568;">Enterprise Client</td>
                            <td style="padding: 8px 0; color: #1A202C; font-weight: 500;">{tender.company}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; color: #4A5568;">Opportunity Title</td>
                            <td style="padding: 8px 0; color: #2D3748; font-weight: 500;">{tender.title}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; color: #4A5568;">Sourcing Channel</td>
                            <td style="padding: 8px 0; color: #718096; font-size: 14px;">{tender.source_portal}</td>
                        </tr>
                    </table>

                    <h3 style="color: #2C5282; border-bottom: 2px solid #E2E8F0; padding-bottom: 8px; margin-top: 0;">📋 Raw Opportunity Context</h3>
                    <p style="background: #F8FAFC; padding: 15px; border-radius: 6px; border-left: 4px solid #CBD5E0; font-size: 14px; color: #4A5568; margin-bottom: 25px;">{tender.description}</p>

                    <h3 style="color: #2C5282; border-bottom: 2px solid #E2E8F0; padding-bottom: 8px;">🚀 Technical Application Roadmap</h3>
                    <div style="background: #EDF2F7; padding: 15px; border-radius: 6px; font-family: 'Courier New', Courier, monospace; font-size: 13px; color: #2D3748; white-space: pre-wrap; margin-bottom: 25px;">{intel.get("application_steps_markdown")}</div>

                    <table style="width: 100%; margin-top: 20px; background: #F7FAFC; padding: 15px; border-radius: 6px;">
                        <tr>
                            <td style="font-size: 14px; color: #4A5568;"><strong>Direct Target Email:</strong> {direct_apply_email}</td>
                        </tr>
                        <tr>
                            <td style="font-size: 14px; color: #4A5568; padding-top: 5px;"><strong>Portal Hyperlink:</strong> <a href="{tender.apply_url}" style="color: #3182CE; text-decoration: none; font-weight: 500;">{tender.apply_url}</a></td>
                        </tr>
                    </table>
                </div>
                <div style="background: #EDF2F7; padding: 15px 30px; text-align: center; border-top: 1px solid #E2E8F0;">
                    <p style="margin: 0; font-size: 11px; color: #718096; font-style: italic;">Automated generation pipeline pass complete. 5 bespoke proposal documents attached below.</p>
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, 'html'))

        for file_name, memory_stream in memory_attachments.items():
            if memory_stream is not None:
                try:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(memory_stream.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={file_name}")
                    msg.attach(part)
                    # Reset buffer read head position for structural re-entry checks if needed
                    memory_stream.seek(0)
                except Exception as e:
                    logging.error(f"Error packing file stream memory buffer allocation {file_name}: {e}")

        recipient_envelope = [self.target_email] + bcc_list
        smtp_session.sendmail(sender_email, recipient_envelope, msg.as_string())
        logging.info(
            f"[+] Direct Payload Dispatched via Open SMTP Stream for ID: {tender.id} (Bcc elements: {len(bcc_list)})")

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

                    # Allocate unique output names
                    fob_name = f"Studio_Aturi_Form_of_Bid_{tender.id}.docx"
                    fin_name = f"Studio_Aturi_Financial_Proposal_{tender.id}.docx"
                    nda_name = f"Studio_Aturi_Mutual_NDA_{tender.id}.docx"
                    details_name = f"Opportunity_Details_{tender.id}.docx"
                    reqs_name = f"Opportunity_Requirements_{tender.id}.docx"

                    # Generate virtual in-memory file buffers
                    memory_attachments = {
                        fob_name: self.process_docx_to_memory(self.fob_template, intel, tender),
                        fin_name: self.process_docx_to_memory(self.financial_template, intel, tender),
                        nda_name: self.process_docx_to_memory(self.nda_template, intel, tender),
                        details_name: self.create_informational_docx_in_memory(self.nda_template,
                                                                               f"Details - {tender.title}",
                                                                               intel.get("inferred_details_markdown",
                                                                                         "")),
                        reqs_name: self.create_informational_docx_in_memory(self.nda_template,
                                                                            f"Requirements - {tender.title}",
                                                                            intel.get("inferred_requirements_markdown",
                                                                                      ""))
                    }

                    print(f"\n⚡ [{idx}/{len(opportunities)}] TARGET TERRITORY IDENTIFIED: {tender.country.upper()}")
                    print(f"  ▪️ Opportunity ID : {tender.id}")
                    print(f"  ▪️ Business Entity : {tender.company}")
                    print(f"  ▪️ Pipeline Focus  : {tender.title}")
                    print(f"  ▪️ Intake Portal   : {tender.source_portal}")
                    print(f"  📦 Generated Valid Virtual Artifact Package Components inside RAM Workspace Allocation.")

                    # Push via current open execution pipeline context block
                    self.send_production_email(server, smtp_user, tender, intel, memory_attachments)

                    # Force closing memory buffers instantly to reclaim platform heap space dynamically
                    for buf in memory_attachments.values():
                        if buf:
                            buf.close()

                    print(
                        f"  ↳ STATUS: Node pipeline execution completed. Safe virtual memory buffers unlinked cleanly.")
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
        print(f"  ✔️ Total Output Word Files Compiled      : {len(opportunities) * 5}")
        print("=" * 95 + "\n")


if __name__ == "__main__":
    agent = StudioAturiProcurementHunter()
    agent.run()
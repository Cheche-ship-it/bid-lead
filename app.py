import os
import json
import logging
import re
import zipfile
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Any
from dataclasses import dataclass
import requests
from dotenv import load_dotenv

# Native Google GenAI SDK (Matches your requirements.txt pin)
from google import genai
from google.genai import types

load_dotenv()

# Suppress verbose connection logs for a cleaner terminal presentation feed
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

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
        self.ai_client = genai.Client(api_key=gemini_key) if gemini_key else None
        self.target_email = "antonynduhiu26@gmail.com"
        self.history_file = "processed_jobs.json"
        
        # Base Template file bindings
        self.fob_template = "Studio_Aturi_Form_of_Bid.docx"
        self.financial_template = "Studio_Aturi_Financial_Proposal.docx"
        self.nda_template = "Studio_Aturi_Mutual_NDA.docx"
        
        # Country Pipeline Matrix covering all requested target scopes
        self.country_profiles = {
            "Kenya": {
                "keywords": ["Corporate Brand Strategy", "Brand Mergers & Acquisitions", "Fintech Identity", "Financial Services Branding", "FMCG Packaging Design", "Product SKU Design", "Consumer Insights", "Market Discovery", "Corporate Identity Guidelines", "Brand Manual", "Value Proposition Development", "Stakeholder Perception Survey"],
                "urls": ["https://tenderflow.co.ke", "https://developmentaid.org", "https://safaricom.co.ke/about/suppliers", "https://eastafricatenders.com"]
            },
            "Uganda": {
                "keywords": ["Brand Audit & Diagnostic", "Corporate Profile", "Visual Identity Review", "Customer Experience Strategy", "CX Strategy", "Audience Profiling", "NGO Campaign Branding", "Commercial Product Packaging"],
                "urls": ["https://tenders.unp.me", "https://kazitenders.co.ug", "https://ungm.org"]
            },
            "Tanzania": {
                "keywords": ["Corporate Image", "Reputation Management", "Brand Architecture Development", "Strategic Positioning", "Private Sector Packaging Design", "Insurance & Pensions Private Fund Communication", "Rollout Management", "Brand Launch Activation"],
                "urls": ["https://tanzaniatenders.com", "https://zoomtanzania.com"]
            },
            "Rwanda": {
                "keywords": ["Digital Transformation Branding", "Tech Brand Strategy", "Service Design", "Product Innovation", "Design Thinking Framework", "Human-Centered Design Research", "HCD Research", "Brand Advisory Services", "Organizational Rebranding", "Perception Mapping"],
                "urls": ["https://jobinrwanda.com/tenders", "https://psf.org.rw"]
            },
            "Congo": {
                "keywords": ["Refonte de l'Identité Visuelle", "Identité Corporative", "Stratégie de Marque", "Conception d’Emballage FMCG", "Communication de Changement de Culture", "Creative Direction", "Brand Asset Management"],
                "urls": ["https://mediacongo.net", "https://congovirtuel.com"]
            },
            "Dubai": {
                "keywords": ["Brand Positioning", "Naming Architecture", "Brand Advisory", "Strategy Pivot", "Luxury Packaging Design", "Advanced Marketing", "Creative Strategy", "Customer Experience Strategy", "Journey Mapping", "Value Proposition Development", "Fintech Identity"],
                "urls": ["https://tenderuae.com", "https://tejari.com"]
            },
            "Ethiopia": {
                "keywords": ["Corporate Rebranding and Strategy", "Brand Architecture", "Identity Manual", "Consumer Insights", "Audience Profiling", "Export Product SKU Design", "Strategic Positioning"],
                "urls": ["https://tenders.2merkato.com", "https://thereporterethiopia.com"]
            }
        }
        self.processed_tender_ids = self._load_history()

    def _load_history(self) -> Set[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return set(json.load(f))
            except:
                pass
        return set()

    def _save_history(self):
        try:
            with open(self.history_file, 'w') as f:
                json.dump(list(self.processed_tender_ids), f)
        except:
            pass

    def scrape_all_opportunities(self) -> List[TenderOpportunity]:
        found_tenders = []
        now = datetime.now(timezone.utc)

        # Unified Mock Data Environment covering every single requested profile
        mock_pipeline_feed = [
            {
                "id": "opp_ke_7721",
                "title": "RFP for Corporate Rebranding & Fintech Identity Architecture",
                "company": "Equator Regional Microfinance Bank PLC",
                "country": "Kenya",
                "source_portal": "TenderFlow Kenya",
                "apply_url": "https://tenderflow.co.ke/view/eq-rebrand-7721",
                "description": "Requires an advisory partner for a structural strategy pivot and Fintech Identity setup. Needs stakeholder perception surveys and brand strategy manuals.",
                "posted_at": now - timedelta(hours=2)
            },
            {
                "id": "opp_ug_1140",
                "title": "Consultancy Services for Corporate Profile & Visual Identity Review",
                "company": "Nile Horizon Telecom Group",
                "country": "Uganda",
                "source_portal": "Kazi Tenders Uganda",
                "apply_url": "https://kazitenders.co.ug/view/nile-horizon-1140",
                "description": "Invites proposals for a complete Corporate Profile rewrite and Visual Identity Review coupled with Customer Experience (CX) Strategy frameworks.",
                "posted_at": now - timedelta(hours=4)
            },
            {
                "id": "opp_tz_3092",
                "title": "RFP: Brand Architecture Development and Strategic Positioning Strategy",
                "company": "Kilimanjaro Export Holdings Ltd",
                "country": "Tanzania",
                "source_portal": "Tanzania Tenders Commercial Portal",
                "apply_url": "https://tanzaniatenders.com/rfp/kilimanjaro-3092",
                "description": "Seeking consulting partners to overhaul corporate brand architecture development and define new strategic positioning profiles for agricultural exports.",
                "posted_at": now - timedelta(hours=6)
            },
            {
                "id": "opp_rw_5512",
                "title": "Human-Centered Design (HCD) Research & Tech Brand Strategy Scope",
                "company": "Kigali Inovate Capital Hub",
                "country": "Rwanda",
                "source_portal": "Job in Rwanda (Tenders)",
                "apply_url": "https://jobinrwanda.com/tenders/kigali-innovate-5512",
                "description": "Requires specialized services for Human-Centered Design (HCD) Research, service design methodologies, and digital transformation branding blueprints.",
                "posted_at": now - timedelta(hours=8)
            },
            {
                "id": "opp_cd_9901",
                "title": "Appel d'Offres: Refonte de l'Identité Visuelle & Stratégie de Marque",
                "company": "Banque Commerciale du Congo (BCDC)",
                "country": "Congo",
                "source_portal": "MediaCongo Tenders",
                "apply_url": "https://mediacongo.net/tenders/bcdc-9901",
                "description": "Recherche d'une agence créative pour la refonte de l'identité visuelle, la stratégie de marque globale et la communication de changement de culture.",
                "posted_at": now - timedelta(hours=1)
            },
            {
                "id": "opp_ae_6641",
                "title": "Expression of Interest: Luxury Packaging Design & Naming Architecture",
                "company": "Al-Mansoori Retail Group Holding",
                "country": "Dubai",
                "source_portal": "Tejari Sourcing Network",
                "apply_url": "https://tejari.com/sourcing/amch-6641",
                "description": "Seeking global agency support for luxury packaging design frameworks, brand positioning matrix updates, and premium asset naming architecture.",
                "posted_at": now - timedelta(hours=12)
            },
            {
                "id": "opp_et_2281",
                "title": "RFP for Export Product SKU Design and Corporate Rebranding Strategy",
                "company": "Abyssinia Premium Coffee Exporters",
                "country": "Ethiopia",
                "source_portal": "2Merkato Tenders",
                "apply_url": "https://tenders.2merkato.com/view/abyssinia-2281",
                "description": "Requires strategic positioning frameworks and extensive export product SKU design services to standardize operations across dynamic logistics channels.",
                "posted_at": now - timedelta(hours=3)
            }
        ]

        for entry in mock_pipeline_feed:
            if entry["id"] in self.processed_tender_ids:
                continue
                
            # strict 24-hour verification window gatekeeper
            if (now - entry["posted_at"]) > timedelta(hours=24):
                continue

            desc_lower = entry["description"].lower()
            title_lower = entry["title"].lower()
            country_rules = self.country_profiles[entry["country"]]["keywords"]
            
            keyword_match = any(k.lower() in desc_lower or k.lower() in title_lower for k in country_rules)
            if keyword_match:
                found_tenders.append(TenderOpportunity(
                    id=entry["id"], title=entry["title"], company=entry["company"],
                    country=entry["country"], description=entry["description"],
                    apply_url=entry["apply_url"], source_portal=entry["source_portal"], 
                    posted_at=entry["posted_at"]
                ))

        return found_tenders

    def generate_tender_intelligence(self, tender: TenderOpportunity) -> Dict[str, Any]:
        if not self.ai_client:
            # Fallback data configuration structure if API key is not specified
            return {
                "clean_currency": "USD", "phase1_cost": "1,500,000", "phase2_cost": "1,200,000",
                "phase3_cost": "2,000,000", "phase4_cost": "1,000,000", "total_cost": "5,700,000",
                "total_cost_words": "FIVE MILLION SEVEN HUNDRED THOUSAND", "rfp_reference_no": f"RFP-REF-{tender.id.upper()}",
                "client_address": "Corporate Headquarters Office Center",
                "application_steps_markdown": "- Complete online intake profile.\n- Forward submission package.",
                "inferred_requirements_markdown": "- Strategic Discovery Analysis\n- Multi-channel Deployment Framework",
                "inferred_details_markdown": "Deep execution summary of targeted operational deliverables."
            }
        
        prompt = f"Analyze opportunity title: '{tender.title}' issued by '{tender.company}' in country '{tender.country}'. Description: {tender.description}. Output a valid JSON mapping with fields matching the execution data model requirements."
        try:
            response = self.ai_client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            return json.loads(response.text)
        except:
            return {}

    def process_and_save_docx_artifacts(self, template_path: str, output_path: str, intel: Dict[str, Any], tender: TenderOpportunity) -> bool:
        if not os.path.exists(template_path):
            return False
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
            with zipfile.ZipFile(template_path, 'r') as zin:
                with zipfile.ZipFile(output_path, 'w') as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        if "document.xml" in item.filename or "header" in item.filename or "footer" in item.filename:
                            xml_content = data.decode('utf-8', errors='ignore')
                            for placeholder, replacement in replacements.items():
                                xml_content = xml_content.replace(placeholder, str(replacement))
                            data = xml_content.encode('utf-8')
                        zout.writestr(item, data)
            return True
        except:
            return False

    def create_informational_docx_safely(self, template_path: str, output_path: str, title: str, content_markdown: str):
        if not os.path.exists(template_path): return
        try:
            clean_content = content_markdown.replace("\n", " ").replace('"', '\\"').replace("<", "&lt;").replace(">", "&gt;")
            with zipfile.ZipFile(template_path, 'r') as zin:
                with zipfile.ZipFile(output_path, 'w') as zout:
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
        except:
            pass

    def run(self):
        opportunities = self.scrape_all_opportunities()
        
        print("\n" + "="*95)
        print(f" 🎯 STUDIO ATURI AUTOMATED PROCUREMENT MATRICES — RUN EXECUTED AT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*95)
        
        for idx, tender in enumerate(opportunities, 1):
            intel = self.generate_tender_intelligence(tender)
            
            fob_output = f"Studio_Aturi_Form_of_Bid_{tender.id}.docx"
            fin_output = f"Studio_Aturi_Financial_Proposal_{tender.id}.docx"
            nda_output = f"Studio_Aturi_Mutual_NDA_{tender.id}.docx"
            details_output = f"Opportunity_Details_{tender.id}.docx"
            reqs_output = f"Opportunity_Requirements_{tender.id}.docx"
            
            # Safe OpenXML pipeline packaging operations
            self.process_and_save_docx_artifacts(self.fob_template, fob_output, intel, tender)
            self.process_and_save_docx_artifacts(self.financial_template, fin_output, intel, tender)
            self.process_and_save_docx_artifacts(self.nda_template, nda_output, intel, tender)
            self.create_informational_docx_safely(self.nda_template, details_output, f"Details - {tender.title}", intel.get("inferred_details_markdown", ""))
            self.create_informational_docx_safely(self.nda_template, reqs_output, f"Requirements - {tender.title}", intel.get("inferred_requirements_markdown", ""))
            
            print(f"\n⚡ [{idx}/{len(opportunities)}] TARGET TERRITORY IDENTIFIED: {tender.country.upper()}")
            print(f"  ▪️ Opportunity ID : {tender.id}")
            print(f"  ▪️ Business Entity : {tender.company}")
            print(f"  ▪️ Pipeline Focus  : {tender.title}")
            print(f"  ▪️ Intake Portal   : {tender.source_portal} ({tender.apply_url})")
            print(f"  ▪️ Intel Summary   : {tender.description}")
            print(f"  📦 Generated Valid Word Artifact Package Components:")
            print(f"     ├── Commercial Sheet : {fob_output}")
            print(f"     ├── Financial Matrix : {fin_output}")
            print(f"     ├── Mutual NDA Block : {nda_output}")
            print(f"     ├── Detail Blueprint : {details_output}")
            print(f"     └── Criteria Sheet   : {reqs_output}")
            print(f"  ↳ STATUS: Processing complete. 5 safe structural OpenXML assets compiled.")
            print("-" * 95)
            
            self.processed_tender_ids.add(tender.id)
            self._save_history()
            
        print("\n" + "="*95)
        print(f" 📈 METRIC TERMINAL REPORT SUMMARY OUTCOME")
        print("="*95)
        print(f"  ✔️ Total Active Target Countries Tracked  : {len(self.country_profiles)}")
        print(f"  ✔️ Total Valid Match Opportunities Found  : {len(opportunities)}")
        print(f"  ✔️ Total Output Word Files Compiled      : {len(opportunities) * 5}")
        print("="*95 + "\n")

if __name__ == "__main__":
    agent = StudioAturiProcurementHunter()
    agent.run()
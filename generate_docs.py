import os
import zipfile

def create_valid_executive_docs():
    output_filename = "Studio_Aturi_Project_Hunter_Documentation.docx"
    
    # 1. Main Document Content
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="48"/><w:color w:val="1A365D"/></w:rPr><w:t>STUDIO ATURI</w:t></w:r></w:p>
            <w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="4A5568"/></w:rPr><w:t>PROJECT HUNTER — BOT DOCUMENTATION</w:t></w:r></w:p>
            <w:p/>
            <w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="2C5282"/></w:rPr><w:t>1. Executive Summary</w:t></w:r></w:p>
            <w:p><w:r><w:t>Project Hunter is an automated intelligence agent engineered to secure high-value private sector accounts for Studio Aturi across premium economic hubs (East Africa, UAE). By eliminating manual sourcing friction, the bot intercepts corporate requests for proposals (RFPs), processes client requirements via the Gemini 2.5 Flash Large Language Model, and instantly generates complete, context-aware pitch artifact packages.</w:t></w:r></w:p>
            <w:p/>
            <w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="2C5282"/></w:rPr><w:t>3. Architecture &amp; Functional Workflow</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>[1] INGESTION PHASE</w:t></w:r></w:p>
            <w:p><w:r><w:t>  └── Scrape &amp; Filter regional feeds (Zero Duplicates cross-reference)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>[2] COGNITIVE ANALYSIS PHASE</w:t></w:r></w:p>
            <w:p><w:r><w:t>  └── Gemini Telemetry Parsing (Extract Cost, Currency, &amp; Address)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>[3] MANUFACTURING PHASE</w:t></w:r></w:p>
            <w:p><w:r><w:t>  └── OpenXML File Synthesis (Assembly of 5 custom pitch docs)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>[4] DISPATCH &amp; PURGE PHASE</w:t></w:r></w:p>
            <w:p><w:r><w:t>  └── Encrypted SMTP Routing &amp; BCC (Immediate secure disk scratch purge)</w:t></w:r></w:p>
            <w:p/>
            <w:p><w:r><w:rPr><w:b/><w:sz w:val="22"/><w:color w:val="2C5282"/></w:rPr><w:t>Generated Document Suite:</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>• Document 1: Form of Bid</w:t></w:r><w:r><w:t> (Studio_Aturi_Form_of_Bid_[ID].docx)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>• Document 2: Financial Proposal</w:t></w:r><w:r><w:t> (Studio_Aturi_Financial_Proposal_[ID].docx)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>• Document 3: Mutual NDA</w:t></w:r><w:r><w:t> (Studio_Aturi_Mutual_NDA_[ID].docx)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>• Document 4: Opportunity Details</w:t></w:r><w:r><w:t> (Opportunity_Details_[ID].docx)</w:t></w:r></w:p>
            <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>• Document 5: Opportunity Requirements</w:t></w:r><w:r><w:t> (Opportunity_Requirements_[ID].docx)</w:t></w:r></w:p>
        </w:body>
    </w:document>"""

    # 2. Relationship Architecture Mapping (Tells Word how to parse it)
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
    </Relationships>"""

    # 3. Global Content Types Mapping
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    </Types>"""

    # Write structural layout safely into target container
    with zipfile.ZipFile(output_filename, 'w') as docx:
        docx.writestr("[Content_Types].xml", content_types_xml)
        docx.writestr("_rels/.rels", rels_xml)
        docx.writestr("word/document.xml", document_xml)
        
    print(f"[+] Document repaired successfully! Saved to: '{output_filename}'")

if __name__ == "__main__":
    create_valid_executive_docs()
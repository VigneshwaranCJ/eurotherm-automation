"""Create a shorter prose-led revision of the storage explanation."""
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "Eurotherm_Reviewer_C_Drive_Storage_Explanation.docx"
OUTPUT = ROOT / "docs" / "Eurotherm_Reviewer_Storage_Note.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
parts = []


def paragraph(text, style="Normal"):
    parts.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')


def heading(text):
    paragraph(text, "Heading2")


def next_page():
    parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')


paragraph("Why Eurotherm Reviewer needs space on C:", "Heading1")
paragraph("A note on the report failure and the storage setup on this PC", "Subtitle")
paragraph("14 October 2026", "Small")

paragraph(r"The question came up because the automation saves reports in D:\Ceiyone\downloads, yet the report failed with a low-space warning for C:. Both observations are correct. The PDF is saved on D:, while Reviewer keeps the data it uses to prepare that PDF on C:.")
paragraph("Changing the report folder controls where the finished file goes. Reviewer still needs access to its archive, database and working files before the download can happen. On this PC, those internal files are stored under the Eurotherm folder in ProgramData on C:.")

heading("Where the files actually go")
paragraph(r"The Python project is in D:\Ceiyone\EurothermReviewerAutomationPython. The selected UHH recording is in D:\Ceiyone\uhh_files, and the completed PDF is intended for D:\Ceiyone\downloads. These locations are controlled by the automation.")
paragraph(r"Reviewer has its own storage under C:\ProgramData\Eurotherm\Reviewer. That folder contains the imported UHH archive, database files, application logs and several processing queues. The selected recording was found in the archive there, and its contents matched the input file on D:.")
paragraph("The database location is also written explicitly in the installed Elasticsearch configuration:")
paragraph(r"path.data: C:\ProgramData\Eurotherm\Reviewer\es7\data", "Code")
paragraph(r"path.logs: C:\ProgramData\Eurotherm\Reviewer\es7\logs", "Code")
paragraph("These settings explain why C: remains involved. The Python output-folder setting does not change either of them. The folder name ‘es7’ is simply the path in the configuration; it is not enough to identify the running database version.")

heading("Why was C: chosen?")
paragraph("The installation is currently configured that way. The files reviewed do not show whether those paths came from an installer default or were selected by someone during setup. They also do not show that Reviewer has to use C: on every PC. Answering whether this installation can use a different drive requires the supported procedure for its version and edition.")

next_page()
paragraph("What stopped this report", "Heading1")

paragraph("The command started correctly. It opened Reviewer, read the UHH metadata, found the right Group 6 recording and verified that the file was already imported. The failure happened during the readiness check, before the chart and report preview were opened.")
paragraph("In the captured status, Reviewer reported about 2.06 GB free, a minimum free-space setting of 5 GB, and indexing disabled. It also returned ErrorDiskFull for both its disk and indexing-service status. The automation read those values and stopped rather than continuing with a report it could not verify.")
paragraph("This was the state recorded at about 3:11 PM IST on 14 October 2026. Available space will change as the PC is used, so the figure should be checked again before the next attempt. ErrorDiskFull is the application’s status label; it does not mean that C: had literally reached zero free bytes.")

heading("Where the 5 GB figure comes from")
paragraph("Reviewer returned the value in a field called settings_MinFreeDiskSpace. The automation did not set it to 5 GB and did not change it during testing. It compares the available space with the value Reviewer supplies, then checks whether indexing is enabled.")
paragraph("The logs do not tell us who chose the value or when it was set. It may be a product default or a site setting, but there is no record here that establishes either explanation. That question needs the installation records, an applicable configuration audit, or confirmation from Eurotherm support.")
paragraph("Reviewer’s 5 GB setting should also be kept separate from Elasticsearch’s own disk-allocation settings. The local configuration file includes a disabled Elasticsearch disk-allocation threshold setting, but Reviewer still reported its own low-space condition. Editing a database-engine setting would not establish that Reviewer is ready to generate reports.")

heading("There is a separate issue with the selected dates")
paragraph("The command also requested an October interval, while the matched Group 6 recording ends on 1 August 2026. That is why the normal run included a missing-data error alongside the disk errors.")
paragraph("The historical test selected available August data successfully. Its missing-data error went away, but the low-space and indexing errors remained. This is useful: it shows that choosing available dates solves the date problem, while the storage problem still needs attention. Recovering disk space will not create the missing October Group 6 samples.")
paragraph("No new PDF was produced by these failed attempts. The logs show that preflight stopped the automation; they do not establish that every manual Reviewer screen or every manual report operation is unavailable.")

next_page()
paragraph("What to do before trying again", "Heading1")

paragraph("The first step is to recover capacity on C: or increase the size of that volume. At the recorded reading, roughly another 2.94 GB would reach the 5 GB minimum. Leaving additional room would avoid returning to the same limit after a small amount of normal activity.")
paragraph("IT should first identify what is using the space. The current findings do not show that Reviewer is responsible for most of the occupied C: drive. Windows, other applications and user files may also contribute. Reviewer’s database and archive should be treated as application data, rather than ordinary files to remove during cleanup.")
paragraph("Once space has been restored, check Reviewer again. The important result is that it reports indexing enabled and a healthy disk/indexing state. Then run the Python diagnostics and test a report using an interval with available data. A completed PDF still needs its instrument, channels and start/end times checked.")

heading("Would moving Reviewer’s data to D: help?")
paragraph("It could provide more capacity if Eurotherm supports that layout for the installed version. The inspected Reviewer API file reports version 5.3.0. A move would need to account for the database, archive, configuration, queues, service permissions and recovery procedure. Moving the PDF folder alone does not cover these items.")
paragraph("Before a change, ask Eurotherm support for the supported migration and backup procedure. Elastic’s guidance warns against modifying its data directory and describes supported snapshot/restore methods. A manual folder copy or a change to one path should not be treated as a complete Reviewer migration.")
paragraph("The automation would also need a small configuration review. Both the Python and TypeScript versions currently look for the archive under the C: ProgramData path and explicitly consider C: free space in their readiness checks. Those assumptions would need updating and testing if the approved storage layout changes.")
paragraph("For now, the report destination can remain on D:. The immediate task is to restore healthy Reviewer storage and indexing, then use dates that belong to the selected recording.")

heading("Basis for this note")
paragraph("The explanation uses the 14 October Python run log, the installed elasticsearch.yml file, the local Reviewer data folders and the automation source. The installed Eurotherm README, HA033274 Issue 5.3, page 14, identifies the ProgramData Reviewer folder as containing archived UHH files and logs. Its disk-capacity guidance is separate from the 5 GB setting reported during this run.", "Small")
paragraph(r"Run log: D:\Ceiyone\EurothermReviewerAutomationPython\logs\run-2026-10-14T09-41-27-669Z.jsonl", "CodeSmall")
paragraph("Further reading: Eurotherm Data Reviewer product information; Elastic’s Path settings guide. These explain product/storage behavior generally and do not replace a version-specific Eurotherm migration procedure.", "Small")
paragraph("https://www.eurotherm.com/en/reviewer/", "Link")
paragraph("https://www.elastic.co/guide/en/elasticsearch/reference/8.19/path-settings-overview.html", "Link")

document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>{''.join(parts)}<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="850" w:right="900" w:bottom="850" w:left="900" w:header="350" w:footer="350"/></w:sectPr></w:body></w:document>'''
header = f'<w:hdr xmlns:w="{W}"><w:p><w:pPr><w:pStyle w:val="Small"/></w:pPr><w:r><w:rPr><w:color w:val="526579"/><w:sz w:val="16"/></w:rPr><w:t>Eurotherm Reviewer | Storage note</w:t></w:r></w:p></w:hdr>'
footer = f'<w:ftr xmlns:w="{W}"><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t>Page </w:t></w:r><w:fldSimple w:instr="PAGE"/></w:p></w:ftr>'
with ZipFile(SOURCE) as original:
    files = {name: original.read(name) for name in original.namelist()}
files.update({"word/document.xml": document.encode("utf-8"), "word/header1.xml": header.encode("utf-8"), "word/footer1.xml": footer.encode("utf-8")})
with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
    for name, content in files.items():
        if name.endswith(".xml") or name.endswith(".rels"):
            ET.fromstring(content)
        archive.writestr(name, content)
with ZipFile(OUTPUT) as archive:
    assert archive.testzip() is None
    root = ET.fromstring(archive.read("word/document.xml"))
    text = " ".join(node.text or "" for node in root.iter(f"{{{W}}}t"))
    assert "settings_MinFreeDiskSpace" in text
    assert len(list(root.iter(f"{{{W}}}tbl"))) == 0
    print(f"Created: {OUTPUT}\nWords: {len(text.split())}\nOOXML validation: passed")

# -*- coding: utf-8 -*-
"""Regenerate the project drill-down section from the verified per-project data."""
import io, re

P = [
dict(code="P1", cls="rose", id="p1", title="Rogers CBU Wireless · Y.IN2100170",
 sub="Denied on eligibility · timesheets and contractor invoices now in hand",
 tag='<span class="tag rose">Not eligible</span>', amount="$740,825",
 brief="""Modernisation of a legacy telecom Business Support System to give near-real-time visibility of subscriber usage. The filed narrative frames it as validating a real-time rating and metering system <em>without access to the system of record</em> — guessing Kafka payload serialisation, offset tracking and message ordering from partial documentation, and substituting for a VoMS voucher retrieval path throttled by a 14–20 day ticketing SLA. CRA read the same work as file-based ingestion, an SFTP pipeline and scripted workarounds. Reviewed over two sessions, May 5 and 7.""",
 grades=[("d","Evidence","Reference 5 is ten slides of architecture and status reporting. CRA's words: no evidence of an experiment, experimental data, or analysis of such data."),
         ("f","Narrative","Section 244 claimed timestamp-skew, message-ordering and Kafka-runtime investigation with hypothesis-driven cycles. None demonstrated. The narrative also quotes 79,173.75 hours — every hour booked to the project — as investigative effort, against a claim asserting 15%."),
         ("d","Financial","Downgraded from B. The salary breakdown was submitted and received, but we now know what was behind it: 96 employees at a flat 15%, applied to capacity hours rather than booked hours. Seven of the 96 are unnamed in the workbook.")],
 fin=[("$613,223","Salaries claimed — 15% of $4,088,153 project payroll"),
      ("$127,602","Arm's-length contracts — 26 individuals, invoices held"),
      ("79,173.8","Hours booked in the timesheet system, 48 employees, 12 months"),
      ("$189,201","Share of credits at stake — 31.8%, the largest")],
 records="""<span class="sb">Timesheets:</span> 79,173.8 hours booked across 48 employees over all twelve months, of which 43,244.8 carry Approved status. <span class="sb">The claim:</span> 96 employees in the workbook at a flat 15% — more employees than booked time to the project — applied to 128,093 capacity hours rather than the 79,174 actually booked. Against hours actually recorded the claim works out at <span class="sb">19.3% or 24.3%</span> — the workbook carries two different SR&amp;ED-hour figures for this project (15,272 and 19,214) and does not reconcile them. Neither is 15%. <span class="sb">Contractors:</span> 26 named individuals, invoices tagged to this project code, and a reconcilable SAP payment trail. But the agreements are weaker than they first looked — three of the seven vendors' agreements begin after FY2024 ended, and the largest, NextGen at $674,706, is a US agreement between Tech Mahindra (Americas) and a US LLC. See <a href="#contractors">section 06</a>.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Wireless-Audit_CRA-Updated.pptx</span> — 22 slides, ~1,800 words. CDR validation background, an optimisation framework, a challenges-and-remedies table, RTRM end-to-end architecture, testing phases, Openet ECS standalone testing, on-premises Kafka producer system testing, and risk-based test scoping.</li>
<li><span class="sb">Screenshot Proof-R&amp;D_Audit-Rogers.pptx</span> — 10 slides, 13 images. This is CRA's Reference 5: E2E architecture, SharePoint archive, test-plan approvals, and four slides of daily status reports. Slides 5–12 of the Wireless deck duplicate it.</li>
<li><span class="sb">Project 1 Wireless - Evidence.pptx</span> (May 4) and <span class="sb">Tech M - SRED_Methodology 1.pdf</span> (June 4).</li>
<li><span class="sb">T661 Part 2 narrative</span> — lines 242, 244, 246, prepared by an external consultant, three named key employees.</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column in the June 4 workbook: total cost $5,396,895, FTE cost $4,088,153, subcon cost $1,308,742, Net QRE % 0.15.</li>
<li><span class="sb">96 employee rows</span> on the Emp Cost sheet with cost, rate, FTE hours and QRE hours per person.</li>
<li><span class="sb">26 subcontractor individuals</span> named with per-person cost on the Subcon sheet.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">78 employees</span> listed with employee id, name, designation, band, function, work location, project, contract type, customer, gross salary and total hours for the year — $4,088,153 in total.</li>
<li><span class="sb">7 subcontractor vendors</span> with SAP vendor ids and amounts: NextGen Consulting $674,706; Vy Systems Canada $148,224; TechDoQuest $129,823; Pragra $113,170; SAPSOL Technologies Canada $106,944; J &amp; M Group $98,787; XpertVantage Canada $37,088.</li>
<li><span class="sb">Not submitted:</span> monthly hour breakdown (the columns were #REF!), hourly wages, and any SR&amp;ED versus non-SR&amp;ED split.</li>
</ul></div></div>''',
 opts=[("stop","CONCEDE — RECOMMENDED","Unchanged, and now better founded. The eligibility finding stands, the narrative overstates investigative effort about fivefold against the company's own claim, and the allocation cannot be defended as a measurement."),
       ("hold","CORRECTION ON THE CONTRACTOR POSITION","We previously recorded P1's $127,602 as the one contract claim with real support behind it. Having read the agreements, that was too optimistic: the payment trail is excellent, but only Pragra's agreement clearly covers FY2024 with the right parties. If eligibility is ever reopened at objection, the agreements need fixing first, not just the invoices producing."),
       ("","ARTEFACT HUNT — STILL WORTH 48 HOURS","The one-minute versus two-minute CDR interval discovery and the six-second timing buffer remain the strongest candidates for genuine uncertainty anywhere in the file. Dated commits or defect tickets would change this project's posture. Nothing else will.")]),

dict(code="P2", cls="rose", id="p2", title="CBT Scotia QA Managed Service · Y.IN2201961",
 sub="Denied on eligibility · zero hours in 846,994 rows · concede without qualification",
 tag='<span class="tag rose">Not eligible</span>', amount="$559,305",
 brief="""Scotiabank's transition to a Tech Mahindra-managed quality engineering service across more than 500 legacy banking applications. The narrative names two uncertainties: a technical void in automating QA for mainframe and batch systems where Selenium, LeanFT and UFT failed entirely, and a managed-service launch coinciding with severe subject-matter-expert attrition that left business logic locked in undocumented shell scripts and COBOL. Delivery is roughly 500 people — about 35% Toronto, 8–10% Mexico, the rest India.""",
 grades=[("f","Evidence","References 10–16: a KPI dashboard, a demo screenshot, a tools slide, a Confluence page and three portal captures. Operational collateral, not R&amp;D evidence."),
         ("f","Narrative","Schema-agnostic parsers, checkpoint markers, buffer delay handling, telemetry injection, anomaly clustering, adaptive script logic — none surfaced in review. The narrative quotes 1,823 hours whose source we cannot locate in any system."),
         ("f","Financial","Downgraded from B. The project code appears nowhere in 846,994 rows of Canadian timesheet data, and the claimant's own workbook records Total Hours: 0 for it — while sheet 3 of the same workbook shows 252,897 hours. The workbook contradicts itself.")],
 fin=[("$548,729","Salaries claimed — 15% of $3,658,196 project payroll"),
      ("$10,576","Arm's-length contracts — 2 individuals"),
      ("0.0","Hours booked in the timesheet system. Zero rows, zero employees, zero months"),
      ("$154,404","Share of credits at stake — 26.0%")],
 records="""<span class="sb">Timesheets:</span> none. Y.IN2201961 does not appear in any of the six monthly exports. <span class="sb">The claim:</span> 169 employee rows — the largest headcount of any project — at a flat 15%, of which <span class="sb">46 are unnamed</span>, recorded only as &ldquo;Not in source&rdquo;. That is 27% of the claimed headcount that cannot currently be identified. <span class="sb">Contractors:</span> two individuals, $10,576; invoices exist for this code, which is more than P3 to P6 can say.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">CRA Walkthrough.pptx</span> — 9 slides, ~570 words, <span class="sb">no images and no tables</span>: agenda, project overview, uncertainties, work performed, advancements, technology stack, a slide titled Supporting Evidence that describes evidence rather than being it, and a thank-you slide.</li>
<li><span class="sb">Project 2 …_CRA.docx</span> — <span class="sb">253 words in total</span>, one image. It answers the three T661 questions in a few sentences each and then lists hardware, languages, frameworks and IDEs.</li>
<li><span class="sb">Seven PNG screenshots</span> — CRA's References 10–16: automation coverage, an automation demo, a tools slide, info-share sessions, and three knowledge-management captures.</li>
<li><span class="sb">Read the docx before defending this project.</span> It tells CRA the primary challenge was &ldquo;the limited availability of internal skill sets&rdquo; and that the response was onboarding specialised resources. That describes a staffing problem solved by hiring. CRA's conclusion follows directly from our own document.</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column: total cost $3,766,670, FTE cost $3,658,196, subcon cost $108,474, Net QRE % 0.15.</li>
<li><span class="sb">169 employee rows</span>, of which <span class="sb">46 carry no name</span> — recorded only as &ldquo;Not in source&rdquo;.</li>
<li><span class="sb">Total Hours: 0</span> in the same workbook that claims $548,729.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">174 employees</span> listed with the same columns as P1 — $3,658,196 in total. The largest resource list submitted for any project.</li>
<li><span class="sb">2 subcontractor vendors</span>: Vy Systems Canada $55,944 and TES Contract Services $52,530.</li>
<li><span class="sb">Not submitted:</span> any hours at all. The employee list carries a total-hours column, but the project has no time booked to it in the source system.</li>
</ul></div></div>''',
 opts=[("stop","CONCEDE WITHOUT QUALIFICATION","Changed from &ldquo;recommended concede&rdquo;. This is now the weakest project in the case on both limbs — no eligibility, and no hours at all. A document request would produce nothing. Conceding it cleanly and early is the single cheapest way to demonstrate good faith on the rest of the file."),
       ("stop","DO NOT ATTEMPT THE SALVAGE CHECK","The Appium-to-Selenium synchronisation question is no longer worth 48 hours. Even if the code exists, there are no Canadian hours to attach a claim to."),
       ("hold","ONE THING TO RESOLVE INTERNALLY","Understand where the 252,897 workbook hours and the narrative's 1,823 hours came from, if not from the time system. We need the answer for our own quality process even though we are conceding the project.")]),

dict(code="P3", cls="amber", id="p3", title="Rogers QE Channels · Y.IN2100171",
 sub="Never reviewed · best records in the file · but the narrative describes a cloud migration",
 tag='<span class="tag amber">No review</span>', amount="$495,321",
 brief="""No technical description exists in the CRA file — the Advisor never reviewed it. The filed narrative, which we have now read, does not describe quality engineering at all. It describes <span class="sb">a migration of containerised telecom microservices from Amazon EKS to Azure AKS</span> across live billing systems, naming three uncertainties: identity propagation between AWS IAM and Azure AD RBAC, instability in undocumented third-party APIs (Semafone, Britebill, OneView) that changed DNS bindings without notice, and whether the AKS autoscaler could sustain telecom-scale concurrency.""",
 grades=[("f","Evidence","Nothing on file. Not assessed by CRA, and nothing was given to assess."),
         ("d","Narrative","Upgraded from unassessable now that we have read it — and the reading is not encouraging. A platform-to-platform migration is the fact pattern CRA has already rejected on P1 as integration rather than advancement. The claimed outputs (an authentication sidecar, a DNS drift logger, a load harness) are the same class of mechanism CRA found undemonstrated on P1 and P2. The narrative also quotes all 90,831.98 booked hours as investigative."),
         ("c","Financial","Upgraded from F. Hours are now fully traceable — 49 employees, twelve months, 71,404 of 90,832 hours Approved. The allocation is not: a flat 15% across all 64 workbook employees.")],
 fin=[("$474,329","Salaries claimed — 15% of $3,162,194 project payroll"),
      ("$20,992","Arm's-length contracts — 4 individuals, no invoices"),
      ("90,832.0","Hours booked, 49 employees, 12 months — the best-covered project"),
      ("$135,173","Share of credits at stake — 22.7%, the largest recoverable")],
 records="""<span class="sb">Timesheets:</span> the strongest in the file — 90,832 hours across 49 employees over twelve months, 71,404 of them Approved. <span class="sb">The claim:</span> 64 workbook employees at a flat 15% applied to 115,390 capacity hours; against hours actually booked that is <span class="sb">15.2% or 19.1%</span>, on the workbook's two unreconciled SR&amp;ED-hour figures (13,841 and 17,309). Three employees are unnamed. <span class="sb">Contractors:</span> four individuals, $215,298 gross reduced to $20,992 claimed — and <span class="sb">no invoices</span> for this project code.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Nothing.</span> No deck, no document, no screenshot, no walkthrough. CRA's Appendix 1 lists sixteen documents received and not one relates to this project.</li>
<li><span class="sb">T661 Part 2 narrative only</span> — the EKS-to-AKS migration description, filed with the return. It is the sole technical statement CRA holds about the largest recoverable project in the claim.</li>
<li>Three key employees named on the narrative: Subha Venkatesh (Delivery Manager), Venkata Srinivas Rao K (Product Lead), Vinit Nandkishore Joshi (Senior Project Manager) — all management roles, each described only as &ldquo;10+ years of Software Experience&rdquo;.</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column in the June 4 workbook: total cost $3,377,492, FTE cost $3,162,194, subcon cost $215,298, Net QRE % 0.15. This much CRA did receive.</li>
<li><span class="sb">64 employee rows</span> with cost, rate and hours per person on the Emp Cost sheet.</li>
<li><span class="sb">4 subcontractor individuals</span> named on the Subcon sheet.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">No employee list.</span> The list submitted covers Y.IN2100170 and Y.IN2201961 only.</li>
<li><span class="sb">No vendor detail.</span> The subcontractor pivot submitted covers the same two projects only.</li>
<li><span class="sb">No hours.</span> The monthly breakdown columns were #REF! for every employee on every project, this one included.</li>
<li>So CRA received a cost column and a percentage, and nothing to test either against. Its finding is the only one available on that record.</li>
</ul></div></div>''',
 opts=[("go","CONTEST — STILL PRIORITY 1, ON THE HOURS","The hours half of the May 7 request can be answered in full and well. Produce the per-employee monthly reconciliation from the time system, tied to this project code and reconciled to payroll."),
       ("hold","BUT THE NARRATIVE IS NOW THE RISK, NOT THE RECORDS","Substantiation delivers this project to an eligibility review that will read an EKS-to-AKS migration against the P1 precedent, decided by the same Advisor. Do not assume the records win it. Build the eligibility position before submitting, not after."),
       ("hold","RESOLVE THE TITLE-VERSUS-WORK QUESTION FIRST","The 49 people booked here were booked to a quality-engineering project. The narrative describes infrastructure migration. Establish which of those people did the migration work before claiming their hours — CRA will ask, and it is a fair question."),
       ("go","THEN BUILD THE ALLOCATION HONESTLY","Per employee, against what that person actually did. It may come out well below 15%. That is an acceptable outcome; an indefensible 15% is not.")]),

dict(code="P4", cls="amber", id="p4", title="Rogers QE Media · Y.IN2100190",
 sub="Never reviewed · the most defensible narrative of the unreviewed set",
 tag='<span class="tag amber">No review</span>', amount="$176,632",
 brief="""Automating video playback validation across web, Android and iOS for Rogers' media streaming applications. The narrative is the most technically credible in the whole claim: whether frame-accurate playback validation — audio-video sync, buffering behaviour, user-triggered seek and pause — could be automated at all when Selenium and Appium cannot detect actual playback, GPU rendering freezes or desynchronisation, and returned false positives; then the divergence when emulator success failed to reproduce on Sauce Labs real devices under thermal throttling and frame jitter.""",
 grades=[("f","Evidence","Nothing on file."),
         ("c","Narrative","The best grade any narrative in this claim earns, and it moved up on reading. This is a genuine capability gap in commercial tooling, not a migration between two vendor platforms, and the emulator-versus-real-device divergence is the kind of unknown outcome SR&amp;ED contemplates. It still asserts all 13,696 booked hours as investigative, and it still needs artefacts."),
         ("c","Financial","Upgraded from F on hours — 10 employees, twelve months, fully traceable. The contractor half is the problem.")],
 fin=[("$108,344","Salaries claimed — 15% of $722,292 project payroll"),
      ("$68,288","Arm's-length contracts — 15 individuals, 39% of project cost, no invoices"),
      ("13,696.0","Hours booked, 10 employees, 12 months"),
      ("$40,006","Share of credits at stake — 6.7%")],
 records="""<span class="sb">Timesheets:</span> 13,696 hours across 10 employees over twelve months, 8,167 Approved. A small, clean population — ten people is a technical review that can actually be done properly. <span class="sb">The claim:</span> 26 workbook employees against 10 with booked time; flat 15% on 21,182 capacity hours, giving <span class="sb">20.9% or 23.2% of hours booked</span> on the workbook's two figures (2,861 and 3,177). Two employees unnamed. <span class="sb">Contractors:</span> 15 individuals, $700,386 gross reduced to $68,288 claimed, no invoices, no residency evidence.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Nothing.</span> No document relating to this project appears in CRA's Appendix 1.</li>
<li><span class="sb">T661 Part 2 narrative only</span> — the frame-accurate video playback validation description. On our reading it is the most defensible narrative in the claim, and CRA has never been shown anything to support it.</li>
<li>Three key employees named: Subhadeep Ghosh (Operations Manager), Milind Rajaram Joshi (Delivery Manager), Edmund Bulaclac (Associate Team Lead).</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column: total cost $1,422,679, FTE cost $722,292, subcon cost $700,387, Net QRE % 0.15.</li>
<li><span class="sb">26 employee rows</span>, against 10 people with time actually booked to the project.</li>
<li><span class="sb">15 subcontractor individuals</span> named — subcontractors are 49% of this project's total cost, the highest ratio in the claim.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">No employee list, no vendor detail, no hours.</span> Same position as P3.</li>
<li>The gap that matters most here is the contractor one: $68,288 claimed against $700,387 of gross subcontractor cost, with no statement of work, no invoice and no evidence going to the taxable-supplier status of the ultimate performers.</li>
</ul></div></div>''',
 opts=[("go","UPGRADE TO PRIORITY 2 — AHEAD OF P7","Changed. On the records this project is small and clean; on eligibility it has the only narrative in the set that does not describe a platform migration. Ten employees makes an honest per-person allocation cheap. This is the best value-to-effort eligibility bet among the unreviewed projects."),
       ("hold","TRIAGE THE CONTRACTORS SEPARATELY AND EARLY","$68,288 across 15 individuals with no invoices and no residency evidence. Ask for the invoices; if they do not arrive within the week, concede the contractor portion and contest the salaries alone. Do not let the contractor half delay the salary half."),
       ("go","RECONCILE 26 WORKBOOK EMPLOYEES AGAINST 10 WITH BOOKED TIME","The gap needs explaining before submission, not after.")]),

dict(code="P5", cls="amber", id="p5", title="Rogers R4B 40633",
 sub="Never reviewed · shares one narrative with P6 · contractor-heavy",
 tag='<span class="tag amber">No review</span>', amount="$127,237",
 brief="""Migration of Rogers' integration middleware from MuleSoft to a Spring Boot stack on Azure. The narrative — which this project <span class="sb">shares with P6</span>, one document covering two separately claimed projects — names the architectural gap between MuleSoft's declarative orchestration and hand-built Spring Boot equivalents, limited prior experience with Azure API Management, Key Vault, DNS routing and Service Bus at throughput, and the absence of a native rollback path making blue-green deployment by DNS toggle an open question.""",
 grades=[("f","Evidence","Nothing on file."),
         ("d","Narrative","Assessable now, and weak. A migration between two commercially supported integration platforms is squarely the pattern CRA rejects. It is also filed as one narrative covering two claimed projects, which invites the question of why they were claimed separately."),
         ("c","Financial","Upgraded from F on hours — 6 employees, twelve months. Contractors remain unsupported.")],
 fin=[("$73,519","Salaries claimed — 15% of $490,124 project payroll"),
      ("$53,718","Arm's-length contracts — 8 individuals, 42% of project cost, no invoices"),
      ("7,921.0","Hours booked, 6 employees, 12 months"),
      ("$28,208","Share of credits at stake — 4.7%")],
 records="""<span class="sb">Timesheets:</span> 7,921 hours across 6 employees over twelve months, but only 3,900 Approved — <span class="sb">the weakest approval ratio in the claim at 49%</span>. <span class="sb">The claim:</span> 15 workbook employees against 6 with booked time; flat 15% on 13,820 capacity hours, giving <span class="sb">22.8% or 26.2% of hours booked</span> on the workbook's two figures (1,804 and 2,073) — the highest ratio of the 15% projects either way. <span class="sb">Contractors:</span> 8 individuals, $550,958 gross reduced to $53,718, no invoices.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Nothing.</span> No document relating to this project appears in CRA's Appendix 1.</li>
<li><span class="sb">A shared T661 narrative</span> — one Part 2 document covers this project and P6 together, describing the MuleSoft-to-Spring-Boot migration. Two separately claimed projects, one description.</li>
<li>Three key employees named across the shared narrative: Nitin Ruhela and Mehul Dilipkumar Patel (Project Managers), Narendrakumar Gunnam (Project Lead).</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column: total cost $1,041,082, FTE cost $490,124, subcon cost $550,958, Net QRE % 0.15.</li>
<li><span class="sb">15 employee rows</span>, against 6 people with time booked.</li>
<li><span class="sb">8 subcontractor individuals</span> named — subcontractors are 53% of project cost.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">No employee list, no vendor detail, no hours.</span></li>
<li>Note the project code carries no Y.IN prefix — it is plain <span class="num">40633</span>, and appears zero-padded to fifteen digits in the time system. Any extract must normalise it or the project will look empty.</li>
</ul></div></div>''',
 opts=[("hold","RIDE-ALONG ON THE P3 AND P4 WORK","Include in the consolidated extract at zero marginal cost. Do not commission separate technical review at $28,208 of credit value."),
       ("stop","CONCEDE THE CONTRACTOR PORTION UNLESS INVOICES ARRIVE","$53,718 with no invoices and no residency evidence, on a project that will not justify chasing them."),
       ("hold","THE SHARED NARRATIVE NEEDS A DECISION","P5 and P6 were claimed as two projects on one description. Either explain the split or present them as one project in the representation. Leaving it unaddressed is worse than either.")]),

dict(code="P6", cls="amber", id="p6", title="Rogers R4B Digital · Y.IN2031013",
 sub="Never reviewed · smallest project · contractor-majority · project code discrepancy",
 tag='<span class="tag amber">No review</span>', amount="$41,715",
 brief="""The digital-channel half of the MuleSoft-to-Spring-Boot migration described above; it shares P5's single narrative. The smallest project in the claim, and the only one whose contractor cost exceeds its salary cost. <span class="sb">Note a discrepancy to resolve:</span> CRA's schedules cite Y.IN2031013 while the client's narrative file and workbook both use Y.IN2301013 — transposed digits. The timesheet system has hours under the latter.""",
 grades=[("f","Evidence","Nothing on file."),
         ("d","Narrative","Shares P5's migration narrative and carries the same weakness, with even less claimed value to justify defending it."),
         ("c","Financial","Upgraded from F on hours — 3 employees, twelve months. At this size the finding barely matters.")],
 fin=[("$18,139","Salaries claimed — 15% of $120,924 project payroll"),
      ("$23,576","Arm's-length contracts — 3 individuals, the majority of project cost"),
      ("4,332.0","Hours booked, 3 employees, 12 months"),
      ("$8,444","Share of credits at stake — 1.4%")],
 records="""<span class="sb">Timesheets:</span> 4,332 hours across 3 employees over twelve months, 3,412 Approved — a good ratio on a tiny population. <span class="sb">The claim:</span> 6 workbook employees against 3 with booked time; flat 15% on 7,191 capacity hours, giving <span class="sb">19.9% or 24.9% of hours booked</span> on the workbook's two figures (863 and 1,079). One of the six is unnamed. <span class="sb">Contractors:</span> 3 individuals, $241,799 gross reduced to $23,575, no invoices.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Nothing.</span> No document relating to this project appears in CRA's Appendix 1.</li>
<li><span class="sb">Half a shared narrative</span> — the same Part 2 document as P5. Nothing in it distinguishes the digital-channel work from the rest.</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column: total cost $362,723, FTE cost $120,924, subcon cost $241,799, Net QRE % 0.15.</li>
<li><span class="sb">6 employee rows</span>, one of them unnamed, against 3 people with time booked.</li>
<li><span class="sb">3 subcontractor individuals</span> named — subcontractors are 67% of project cost, the highest proportion in the claim.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">No employee list, no vendor detail, no hours.</span></li>
<li>The code the workbook submitted was <span class="num">Y.IN2301013</span>. CRA's schedules record <span class="num">Y.IN2031013</span>. One of the two is wrong and it has never been reconciled.</li>
</ul></div></div>''',
 opts=[("hold","RIDE-ALONG OR CONCEDE","Unchanged. Zero-marginal-cost inclusion in the consolidated extract; no bespoke effort at $8,444 of credit value."),
       ("go","FIX THE PROJECT CODE IN ANY SUBMISSION","Y.IN2031013 on CRA's schedules against Y.IN2301013 in our own records. Whichever is right, a representation that quotes a code CRA cannot match to its file starts badly. Confirm which the T661 actually carried.")]),

dict(code="P7", cls="amber", id="p7", title="Mt_Cc_Fp_Legacy_Ticketing · #38370",
 sub="Never reviewed · salary only · the 50% rate now needs its own justification",
 tag='<span class="tag amber">No review</span>', amount="$139,854",
 brief="""Modernisation of a legacy ticketing and middleware platform from WebSphere and DMaaP into stateless microservices. The narrative names four uncertainties: untangling session logic embedded in WebSphere portlets and replicating it through stateless APIs; containerising Apache Spark on AKS where the in-memory model repeatedly failed under Kubernetes resource limits; migrating DMaaP to Kafka with duplicate processing, inconsistent ordering and replay storms; and OpenID Connect and SAML migration producing redirect loops and session persistence failures.""",
 grades=[("f","Evidence","Nothing on file."),
         ("d","Narrative","Assessable now. Another platform migration — WebSphere to microservices, DMaaP to Kafka — and the Kafka ordering and replay language is close kin to the P1 narrative CRA has already rejected as undemonstrated. This lowers our earlier read that P7 sat outside the ruled-against pattern."),
         ("c","Financial","Upgraded from F, and the cleanest financial structure in the claim: four named employees, no contractors, and hours that tie exactly. But the rate is now the issue, not the hours.")],
 fin=[("$139,854","Salaries claimed — 50% of $279,708 project payroll"),
      ("$0","Contracts — none claimed, no contractor exposure"),
      ("8,182.6","Hours booked, 4 employees, 12 months — the only project where claimed and booked hours tie exactly"),
      ("$38,965","Share of credits at stake — 6.6%")],
 records="""<span class="sb">Timesheets:</span> 8,182.6 hours across 4 employees over twelve months, 6,700.6 Approved. Uniquely in this claim, the workbook's hours for P7 equal the hours actually booked — every other project used capacity hours instead. No employees unnamed. <span class="sb">The claim:</span> four employees at a flat <span class="sb">50%</span>, the only departure from 15% anywhere in the file, giving 4,091 SR&amp;ED hours — exactly half of all time booked to the project. <span class="sb">Contractors:</span> none.""",
 submitted='''<div class="subgrid">
<div class="subcard"><div class="sh">Technical</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">Nothing.</span> No document relating to this project appears in CRA's Appendix 1.</li>
<li><span class="sb">T661 Part 2 narrative only</span> — the WebSphere and DMaaP to stateless microservices description, including Spark on AKS and the DMaaP-to-Kafka migration.</li>
<li>Three key employees named: Sandeep Kumar Senapati (Associate Tech Specialist Manager), Swadheen Kumar Jena (Technical Architect), Jyoti Prakash Acharya (Test Lead / Program Manager).</li>
</ul></div>
<div class="subcard"><div class="sh">Financial</div><ul class="clean" style="font-size:12.6px">
<li>Project column: total cost $279,708, all of it FTE cost, no subcontractors, <span class="sb">Net QRE % 0.50</span> — the only project not at 0.15, and CRA received the figure without any explanation attached to it.</li>
<li><span class="sb">4 employee rows</span>, all named, each at 50%: Vishal Singh, Jyoti Prakash Acharya, Swadheen Kumar Jena, Sandeep Kumar Senapati.</li>
<li>Uniquely, the hours on the Emp Cost sheet tie exactly to hours booked — 8,182.56.</li>
</ul></div>
<div class="subcard"><div class="sh">Resources</div><ul class="clean" style="font-size:12.6px">
<li><span class="sb">No employee list submitted</span> — though at four people this is the easiest gap in the claim to close, and three of the four are the same people named on the narrative.</li>
<li><span class="sb">No contractors</span>, so nothing missing on that side.</li>
<li><span class="sb">No hours breakdown</span> and, more pointedly, no basis for the 50%.</li>
</ul></div></div>''',
 opts=[("hold","DOWNGRADE TO PRIORITY 3 — BEHIND P3 AND P4","Changed. Our earlier read was that P7 sat outside the ruled-against Rogers pattern. Having read the narrative, it is another platform migration with Kafka ordering language close to P1's. And the 50% is now the exposed flank."),
       ("hold","THE 50% NEEDS ITS OWN JUSTIFICATION BEFORE ANYTHING IS FILED","Asserting that half of everything four people did for a year was experimental development is a strong claim. It may be true — a four-person team on a migration could plausibly spend half its time on genuinely uncertain work. But it has to be established person by person, and if it cannot be, the number must come down before CRA asks."),
       ("go","STILL THE CHEAPEST HONEST TEST IN THE FILE","Four named people, one cost type, twelve months of clean hours. If a defensible allocation can be built anywhere in this claim, it can be built here fastest. Run it early precisely because it is cheap — the answer will tell us what the method produces before we spend on P3.")]),
]

def render():
    out = io.StringIO()
    w = out.write
    w('''
<!-- ============ 07 PROJECTS ============ -->
<section id="projects">
  <div class="sechead">
    <div class="eyebrow">Section 07</div>
    <h2>Project-by-project analysis</h2>
    <p class="lede">Rewritten August 26 against the client records. Each project now carries what the filed narrative actually says, what the timesheets show, what rate the claim applied, and where the contractor evidence stands. <span class="sb">Evidence</span> — do contemporaneous artefacts of experimentation exist? <span class="sb">Narrative</span> — does the filed description survive reading? <span class="sb">Financial</span> — are the claimed costs substantiated and traceable? Grades run A strong, B adequate, C weak, D poor, F absent or failed. Several moved this week, in both directions.</p>
  </div>
''')
    for p in P:
        w(f'''
  <details class="proj" id="{p['id']}">
    <summary>
      <span class="pcode {p['cls']}">{p['code']}</span>
      <span class="ptitle"><span class="pn">{p['title']}</span><span class="pd">{p['sub']}</span></span>
      <span class="pamt">{p['amount']}</span><span class="chev">&#9654;</span>
    </summary>
    <div class="pbody">
      <div><h4>Overall project brief</h4><p>{p['brief']}</p></div>

      <div><h4>Quality of R&amp;D evidence and narrative</h4>
      <div class="grades">''')
        for mark, label, text in p['grades']:
            g = mark.upper() if mark != 'q' else '?'
            w(f'''
        <div class="grade"><div class="gh"><span class="gmark {mark}">{g}</span><span class="gl">{label}</span></div><div class="gt">{text}</div></div>''')
        w(f'''
      </div></div>

      <div><h4>What the records show now</h4><p>{p['records']}</p></div>

      <div><h4>What was submitted to CRA</h4>{p['submitted']}</div>

      <div><h4>Financials</h4>
      <div class="figs">''')
        for v, l in p['fin']:
            w(f'''
        <div class="fig"><div class="fv num">{v}</div><div class="fl">{l}</div></div>''')
        w('''
      </div></div>

      <div><h4>Proposed next steps</h4>
      <div class="stack">''')
        for cls, label, text in p['opts']:
            w(f'''
        <div class="opt {cls}"><div class="ol">{label}</div><p>{text}</p></div>''')
        w('''
      </div></div>
    </div>
  </details>
''')
    w('</section>\n')
    return out.getvalue()

if __name__ == "__main__":
    html = open("TM_SRED_Audit_Defence_Report.html").read()
    start = html.index('\n<!-- ============ 07 PROJECTS ============ -->')
    end = html.index('<!-- ============ 08 PLAN ============ -->')
    if end < start:
        raise SystemExit("markers out of order")
    open("TM_SRED_Audit_Defence_Report.html", "w").write(html[:start] + render() + "\n" + html[end:])
    print("projects section regenerated")

# CRA findings — verbatim

Tech Mahindra Limited · Reference case 31874271 · Tax year-end 2024-03-31

Transcribed from the CRA package received 2026-07-29. Page headers, footers and the PROTECTED B
markings are removed, and words or sentences split across a page or line break are rejoined.
Nothing else is changed — spacing oddities such as `project ,` are the Agency's own.

---

## Project Eligibility Report

Prepared by Tony Brunner, Research and Technology Advisor. Approved by Emmanuel Seitelbach, Research and Technology Manager. Dated 16 July 2026.

### 5.1.3 Eligibility determination — Project 1: Rogers CBU Wireless Y.IN2100170

Based on the technical information gathered during this review, the work carried out by the Company does not meet the criteria for SR&ED experimental development. No technological uncertainty was encountered.
The activities described are primarily focused on system modernization, automation, and data pipeline implementation.
The Company enhanced a legacy BSS to provide near real-time usage visibility by introducing cloud-based processing, file-based data ingestion (SFTP), and automated validation processes. While the reduction in processing time from several hours to minutes represents a significant operational improvement, it reflects performance optimization and system integration, rather than the resolution of a technological uncertainty through experimental investigation.
The use of simulated CDR data was described as a testing and quality assurance mechanism, where a “golden dataset” was generated to verify that expected attributes (e.g., 72 fields) were correctly represented. This simulation activity was not presented as an effort to investigate unknown system behaviour, but rather as a means of confirming known requirements in a controlled environment. Similarly, issues encountered during the project , such as file parsing errors, newline misinterpretation, null field validation, and differences in CDR generation intervals, were addressed through script adjustments and incorporation of known business rules, not through hypothesis -driven experimentation.
The challenges related to Kafka integration, SFTP data transfer delays, and voucher file decryption were also described as implementation constraints or access limitations, addressed through temporary scripts and workarounds. These efforts represent engineering solutions to integration and infrastructure limitations, rather than the advancement of technological knowledge.
Overall, the work as described reflects engineering activities, including system configuration, data processing, validation scripting, and integration of existing technologies. There is no clear evidence of a systematic investigation aimed at resolving uncertainties in the underlying technology, nor of new knowledge being generated beyond the specific implementation context.
Furthermore, several key elements described in section 244 of the project description - particularly those related to timestamp skew, message ordering behaviour, Kafka runtime uncertainty, and hypothesis -driven experimentation - were not explicitly addressed or demonstrated during the review. As a result, there is a notable gap between the detailed technical characterization of the work in the project description and the facts gathered during the review.
Documentation:
Reference 5 contains 10 slides covering the E2E architecture, project SharePoint site, test plan approvals, daily status reports, and RTRM project status report. The document does not contain evidence of an experiment, experimental data or analysis of such data in an attempt to uncover new technological knowledge.
Since there is no work to resolve scientific or technological uncertainty, it follows that the work claimed was not for the advancement of scientific knowledge nor for the purpose of achieving technological advancement .
The work claimed in the project does not meet the definition of SR&ED in subsection 248(1) of the Income Tax Act.

### 5.2.3 Eligibility determination — Project 2: CBT SCOTIA_QA Managed Service Y.IN2201961

The claimed work did not attempt to resolve scientific or technological uncertainty.
Based on the work as presented in the review meeting, a technological knowledge gap has not been clearly identified.
The activities discussed relate to the application and integration of established quality assurance tools and practices, including Appium for mobile testing, Selenium for web testing, Postman for API validation, LeanFT/UFT for mainframe screen automation, and the orchestration of these tools to achieve end-to-end test coverage. While the environment is complex due to the number of applications, technologies, and integration points, the challenges described are consistent with known limitations of heterogeneous enterprise systems and legacy mainframe environments. The work described reflects engineering adaptation, configuration, and coordination of existing technologies rather than an attempt to advance technological knowledge or resolve an uncertainty that could not be addressed through standard software engineering practices.
In addition, there is a material mismatch between the work described during the review meeting and the activities outlined in section 244 of the project description. The review discussion remained at a high-level and focused on overall testing scope, tool selection, authentication flows, batch timing considerations, and operational sequencing across mobile, web, API, and mainframe systems. In contrast, section 244 describes highly specific, failure-driven experimental activities, including schema-agnostic parsers, checkpoint markers, buffer delay handling, telemetry injection, anomaly clustering, and adaptive script logic. These detailed mechanisms and experimentation cycles were not evidenced or demonstrated in the review discussion, nor were concrete technical artifacts or implementation details presented to substantiate them. As a result, the review discussion does not support the level of technological experimentation or advancement implied in the project description.
Documentation:
References 10-16 were provided as supporting documents. These documents cover a KPI Dashboard, a screen shot of the home page of an automation tool-stack demo, a slide showing a number of tools, an info share confluence page, and three screen shots of a web portals. The documents do not contain evidence of an experiment, experimental data or analysis of such data in an attempt to uncover new technological knowledge.
Since there is no work to resolve scientific or technological uncertainty, it follows that the work claimed was not for the advancement of scientific knowledge nor for the purpose of achieving technological advancement.
The work claimed in the project does not meet the definition of SR&ED in subsection 248(1) of the Income Tax Act .

### Section 6 — Recommendations for future claims

The Company should be prepared to clearly explain the work described in the project description during technical reviews.
The activities discussed in the review should align closely with the work outlined in the submitted documentation, including the technical challenges, approaches taken, and outcomes achieved. Consistency between the written project description and verbal explanations is essential to demonstrate that the claimed work accurately reflects the actual activities performed.

---

## Audit Adjustments working paper — Kitty Leung, 22 July 2026

### Note 1 — salaries, Projects 1 and 2, and contracts, Projects 1 and 2

Adjustments as per Project Eligibility Report.

### Note 2 — non-specified employee salaries, Projects 3 to 7

A request was made for salary breakdown of all projects in the request for additional information letter dated May 7, 2026. Documentation was submitted for
Project 1 and Project 2, but no documentation was provided by the claimant for the salary breakdowns for Project 3 to Project 7. The hours and salaries claimed for SR&ED in Project 3 to Project 7 are unsubstantiated since breakdown of hours or support by activity was not provided. There is no distinction between regular work and SR&ED work. No information was provided to verify which employees were involved in each project.
For future claims, the categorization of amounts claimed per project in the T661 must match the data that is provided by the documentation provided. There needs to be a breakdown of monthly hours for each employee claimed indicating SR&ED and non-SR&ED activities for each project.

### Note 2 — arm's length contracts, Projects 3 to 6

A request for additional information letter dated May 7, 2026 was sent requesting documentation to substantiate the arm's length contract claimed. No documentation was submitted and contracts claimed were not supported. Extent of hours claimed per contractor cannot be verified. There was no distinction between SR&ED and R&D activities. No documentation provided to verify the taxable status of ultimate performers.

### Note 3 — arm's length contracts, Project 7

No contracts claimed.


---

## Proposal letter — Kitty Leung, Financial Reviewer, 30 July 2026

We have completed the review of your SR&ED claim. Based on the information provided during our review, we have determined that not all of the work claimed meets the requirements of the Income Tax Act. Please see the attached
Project Eligibility Report for a detailed explanation of our evaluation of the work claimed.
We are proposing to make adjustments to the SR&ED expenditures and investment tax credit(s) (ITC) claimed as follows:
Tax year-end: 2024-03-31
Filed Revised by CRA Difference
Total allowable SR&ED expenditures (A-32) $ 2,280,889 $ 0 $ 2,280,889
Qualified SR&ED expenditures (A-32) $ 3,191,076 $ 0 $ 3,191,076
Federal investment tax credits (ITC) earned (A-31) $ 478,661 $ 0 $ 478,661
Provincial/territorial tax credit (ORDTC) (A-508) $ 115,738 $ 0 $ 115,738
Net Income (loss) for tax purposes (A-1) $ 21,777,058 $ 21,407,483 $ 369,575
Taxable income (A-1) $ 21,777,058 $ 21,407,483 $ 369,575
The amount on line 435 in the T661 (A-32) was adjusted from Filed $467,727 to Revised by CRA $175,850.The revised amount is based on the adjusted amount of ITCs reassessed in the 2023-03-31 taxation year. This recapture of SR&ED expenditures from the T661 has adjusted your Net Income for Tax Purposes and Taxable Income.
The proposed adjustments are explained the attached Summary of adjustments.
Details of the proposed adjustments and the associated financial and tax implications are provided in the additional attached documents.
We will delay processing these proposed adjustments until August 31, 2026, in order to give you an opportunity to accept the proposed adjustments or to provide written representations and additional information that you would like us to consider.

### On the right to respond

If you would like us to process the claim prior to August 31, 2026, please sign and return the attached Summary of adjustments. If you do not respond by this date, we will proceed with the proposed adjustments explained above and in the Summary of adjustments and an assessment will follow in due course.
If you feel that your concerns have not been satisfactorily addressed after discussions with the research and technology advisor or the financial reviewer and their respective managers, you can request an Administrative Review. You will find information about the Administrative Review at Guidelines for resolving claimants’ SR&ED concerns - Canada.ca.

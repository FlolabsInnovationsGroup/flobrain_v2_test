"""Control catalog: SOC 2 Trust Services Criteria (2017, revised points of focus 2022) and ISO/IEC 27001:2022
Annex A (93 controls in 4 themes).

Identifiers and short names only, with our own one-line paraphrases. The official criteria and control
text are copyrighted (AICPA, ISO/IEC) and are not reproduced here. Sources used to verify numbering and
names (checked 2026-10-21):

- ISO/IEC 27001:2022 Annex A list: https://www.dataguard.com/knowledge/iso-27001-controls-annex-a/
  (37 organizational, 8 people, 14 physical, 34 technological = 93)
- SOC 2 series headings: https://www.tcsa.in/frameworks/soc-2/trust-service-criteria and
  https://secureframe.com/hub/soc-2/common-criteria.md (33 common criteria in CC1 to CC9)

``checks`` names the automated checks in ``compliance.checks`` that give evidence for a control. A
control with no checks needs a person's attestation (manual evidence). The mapping is about what
FloBrain can show for access and AI governance *inside FloBrain*; it is not a full control set.
"""

SOC2 = "soc2"
ISO = "iso27001"
FRAMEWORKS = {
    SOC2: {"name": "SOC 2 (Trust Services Criteria)", "short": "SOC 2"},
    ISO: {"name": "ISO/IEC 27001:2022 Annex A", "short": "ISO 27001"},
}

# --- SOC 2 ---------------------------------------------------------------------------------------
# (id, group, short name, paraphrase, checks)
_SOC2 = [
    ("CC1.1", "CC1", "Integrity and ethics", "Leadership shows a commitment to integrity and ethical values.", ["policies_acknowledged"]),
    ("CC1.2", "CC1", "Board oversight", "An independent body oversees how internal control is run.", []),
    ("CC1.3", "CC1", "Structure and authority", "Management sets reporting lines, roles and authority.", ["admin_count"]),
    ("CC1.4", "CC1", "Competence", "The organization attracts, develops and keeps competent people.", []),
    ("CC1.5", "CC1", "Accountability", "People are held accountable for their control duties.", ["policies_acknowledged"]),
    ("CC2.1", "CC2", "Quality information", "Relevant, good quality information supports internal control.", ["audit_log"]),
    ("CC2.2", "CC2", "Internal communication", "Control objectives and duties are communicated inside the organization.", ["policies_acknowledged"]),
    ("CC2.3", "CC2", "External communication", "Matters affecting controls are communicated to outside parties.", ["trust_center"]),
    ("CC3.1", "CC3", "Clear objectives", "Objectives are clear enough to identify related risks.", []),
    ("CC3.2", "CC3", "Risk identification", "Risks to objectives are identified and analysed.", []),
    ("CC3.3", "CC3", "Fraud risk", "The potential for fraud is considered when assessing risk.", []),
    ("CC3.4", "CC3", "Change impact", "Changes that could affect internal control are identified and assessed.", []),
    ("CC4.1", "CC4", "Ongoing evaluations", "Controls are evaluated to confirm they are present and working.", ["access_review_recent", "audit_log"]),
    ("CC4.2", "CC4", "Deficiency follow-up", "Control gaps are reported and fixed on time.", ["incidents"]),
    ("CC5.1", "CC5", "Control activities", "Control activities are chosen to bring risks to acceptable levels.", ["ai_approvals"]),
    ("CC5.2", "CC5", "Technology controls", "General controls over technology are selected and built.", ["ai_approvals", "ai_data_policy"]),
    ("CC5.3", "CC5", "Policies and procedures", "Controls are deployed through policies and procedures.", ["policies_acknowledged"]),
    ("CC6.1", "CC6", "Logical access security", "Access to information assets is protected by logical access controls.", ["sso_enforced", "owner_mfa", "encryption"]),
    ("CC6.2", "CC6", "User registration and removal", "Users are registered, authorized and removed in a controlled way.", ["scim", "dormant_members", "leavers_access", "access_review_recent"]),
    ("CC6.3", "CC6", "Role-based access", "Access is granted, changed and removed by role, with least privilege.", ["admin_count", "pending_requests", "access_review_recent"]),
    ("CC6.4", "CC6", "Physical access", "Physical access to facilities and assets is restricted.", []),
    ("CC6.5", "CC6", "Asset disposal", "Data protection continues until assets are disposed of.", ["retention_policy"]),
    ("CC6.6", "CC6", "External threats", "Logical access from outside system boundaries is controlled.", ["external_agents"]),
    ("CC6.7", "CC6", "Data in transit and at rest", "Information is protected when moved, transmitted or stored.", ["encryption"]),
    ("CC6.8", "CC6", "Malicious software", "Unauthorized or malicious software is prevented or detected.", []),
    ("CC7.1", "CC7", "Configuration monitoring", "Configuration changes and new vulnerabilities are detected.", []),
    ("CC7.2", "CC7", "Anomaly monitoring", "System components are monitored for anomalies and attacks.", ["audit_log"]),
    ("CC7.3", "CC7", "Event evaluation", "Security events are evaluated to decide if they are incidents.", ["incidents"]),
    ("CC7.4", "CC7", "Incident response", "Incidents are contained, fixed and communicated through a defined process.", ["incidents"]),
    ("CC7.5", "CC7", "Incident recovery", "Recovery from incidents is planned and carried out.", ["incidents", "backup_export"]),
    ("CC8.1", "CC8", "Change management", "Changes to systems are authorized, tested, approved and recorded.", ["ai_approvals"]),
    ("CC9.1", "CC9", "Business disruption", "Risks from business disruption are identified and mitigated.", ["backup_export"]),
    ("CC9.2", "CC9", "Vendors and partners", "Risks from vendors and business partners are assessed and managed.", ["external_agents"]),
    ("A1.1", "A1", "Capacity", "Capacity is monitored and planned to meet availability commitments.", []),
    ("A1.2", "A1", "Backup and recovery infrastructure", "Environmental protections, backups and recovery infrastructure are in place.", ["backup_export"]),
    ("A1.3", "A1", "Recovery testing", "Recovery plan procedures are tested.", []),
    ("C1.1", "C1", "Identify confidential information", "Confidential information is identified and kept to meet commitments.", ["ai_data_policy", "data_region"]),
    ("C1.2", "C1", "Dispose of confidential information", "Confidential information is disposed of when no longer needed.", ["retention_policy"]),
    ("PI1.1", "PI1", "Processing definitions", "Information about processing objectives and data is defined and used.", []),
    ("PI1.2", "PI1", "Input controls", "System inputs are complete and accurate.", []),
    ("PI1.3", "PI1", "Processing controls", "Processing is complete, accurate and timely.", ["ai_approvals"]),
    ("PI1.4", "PI1", "Output controls", "Outputs are complete, accurate and delivered as intended.", []),
    ("PI1.5", "PI1", "Stored data", "Stored inputs and outputs are complete, accurate and protected.", ["backup_export"]),
    ("P1", "P", "Notice", "People are told about privacy practices.", ["trust_center"]),
    ("P2", "P", "Choice and consent", "Choices about personal information are offered and consent recorded.", []),
    ("P3", "P", "Collection", "Personal information is collected only for stated purposes.", ["ai_data_policy"]),
    ("P4", "P", "Use, retention and disposal", "Personal information is used, kept and disposed of as stated.", ["retention_policy"]),
    ("P5", "P", "Access", "People can see and correct their personal information.", []),
    ("P6", "P", "Disclosure and notification", "Disclosures to third parties and breaches are handled and notified.", ["incidents", "trust_center"]),
    ("P7", "P", "Quality", "Personal information is kept accurate and complete.", []),
    ("P8", "P", "Monitoring and enforcement", "Privacy compliance is monitored and complaints are handled.", []),
]
SOC2_GROUPS = {
    "CC1": "Control environment",
    "CC2": "Communication and information",
    "CC3": "Risk assessment",
    "CC4": "Monitoring activities",
    "CC5": "Control activities",
    "CC6": "Logical and physical access",
    "CC7": "System operations",
    "CC8": "Change management",
    "CC9": "Risk mitigation",
    "A1": "Availability",
    "C1": "Confidentiality",
    "PI1": "Processing integrity",
    "P": "Privacy",
}

# --- ISO/IEC 27001:2022 Annex A ------------------------------------------------------------------
# (id, short name, paraphrase, checks); the theme comes from the number (5, 6, 7, 8).
_ISO = [
    ("5.1", "Policies for information security", "Security policy is defined, approved, published and acknowledged.", ["policies_acknowledged"]),
    ("5.2", "Information security roles and responsibilities", "Security roles are defined and assigned.", ["admin_count"]),
    ("5.3", "Segregation of duties", "Conflicting duties are split between people.", ["admin_count"]),
    ("5.4", "Management responsibilities", "Managers make staff apply security policy.", ["policies_acknowledged"]),
    ("5.5", "Contact with authorities", "Contacts with relevant authorities are kept.", []),
    ("5.6", "Contact with special interest groups", "Contacts with security forums and groups are kept.", []),
    ("5.7", "Threat intelligence", "Information about threats is gathered and analysed.", []),
    ("5.8", "Information security in project management", "Security is built into project management.", []),
    ("5.9", "Inventory of information and other associated assets", "Information and assets have an inventory and owners.", []),
    ("5.10", "Acceptable use of information and other associated assets", "Rules for acceptable use, including AI use, are set and followed.", ["policies_acknowledged", "ai_approvals"]),
    ("5.11", "Return of assets", "Assets are returned when people leave or change roles.", ["leavers_access"]),
    ("5.12", "Classification of information", "Information is classified by its protection needs.", []),
    ("5.13", "Labelling of information", "Information is labelled according to its classification.", []),
    ("5.14", "Information transfer", "Rules protect information transferred inside and outside.", ["encryption"]),
    ("5.15", "Access control", "Access rules are set from business and security needs.", ["sso_enforced", "access_review_recent"]),
    ("5.16", "Identity management", "The full life cycle of identities is managed.", ["sso_enforced", "scim"]),
    ("5.17", "Authentication information", "Passwords and other secrets are allocated and handled safely.", ["sso_enforced", "owner_mfa"]),
    ("5.18", "Access rights", "Access rights are granted, reviewed, changed and removed.", ["access_review_recent", "pending_requests", "dormant_members"]),
    ("5.19", "Information security in supplier relationships", "Supplier security risks are managed.", ["external_agents"]),
    ("5.20", "Addressing information security within supplier agreements", "Supplier agreements set security requirements.", []),
    ("5.21", "Managing information security in the ICT supply chain", "Risks in the ICT supply chain are managed.", []),
    ("5.22", "Monitoring, review and change management of supplier services", "Supplier services are monitored and reviewed.", []),
    ("5.23", "Information security for use of cloud services", "Using and leaving cloud services follows security requirements.", ["data_region", "external_agents"]),
    ("5.24", "Information security incident management planning and preparation", "Incident management is planned, with roles.", ["incidents"]),
    ("5.25", "Assessment and decision on information security events", "Events are assessed to decide if they are incidents.", ["incidents"]),
    ("5.26", "Response to information security incidents", "Incidents are handled with documented procedures.", ["incidents"]),
    ("5.27", "Learning from information security incidents", "Lessons from incidents improve controls.", ["incidents"]),
    ("5.28", "Collection of evidence", "Evidence about events is collected and preserved.", ["audit_log"]),
    ("5.29", "Information security during disruption", "Security is kept at an appropriate level during disruption.", []),
    ("5.30", "ICT readiness for business continuity", "ICT readiness is planned and tested for continuity.", ["backup_export"]),
    ("5.31", "Legal, statutory, regulatory and contractual requirements", "Legal and contractual security requirements are identified and met.", ["data_region"]),
    ("5.32", "Intellectual property rights", "Intellectual property rights are protected.", []),
    ("5.33", "Protection of records", "Records are protected from loss, tampering and early deletion.", ["retention_policy", "audit_log"]),
    ("5.34", "Privacy and protection of PII", "Personal data is protected as law and contracts require.", ["ai_data_policy", "retention_policy"]),
    ("5.35", "Independent review of information security", "Security is reviewed independently at planned intervals.", []),
    ("5.36", "Compliance with policies, rules and standards for information security", "Compliance with security policy is reviewed regularly.", ["policies_acknowledged", "access_review_recent"]),
    ("5.37", "Documented operating procedures", "Operating procedures are documented and available.", []),
    ("6.1", "Screening", "Candidates are background checked before joining.", []),
    ("6.2", "Terms and conditions of employment", "Employment terms state security responsibilities.", []),
    ("6.3", "Information security awareness, education and training", "People get security awareness and training.", ["policies_acknowledged"]),
    ("6.4", "Disciplinary process", "A disciplinary process covers policy violations.", []),
    ("6.5", "Responsibilities after termination or change of employment", "Duties that continue after leaving are enforced.", ["leavers_access", "scim"]),
    ("6.6", "Confidentiality or non-disclosure agreements", "Confidentiality agreements are in place and reviewed.", []),
    ("6.7", "Remote working", "Remote work is protected by security measures.", []),
    ("6.8", "Information security event reporting", "People can report security events quickly.", ["incidents"]),
    ("7.1", "Physical security perimeters", "Perimeters protect areas holding information.", []),
    ("7.2", "Physical entry", "Secure areas have entry controls.", []),
    ("7.3", "Securing offices, rooms and facilities", "Offices and facilities are physically secured.", []),
    ("7.4", "Physical security monitoring", "Premises are monitored for unauthorized access.", []),
    ("7.5", "Protecting against physical and environmental threats", "Facilities are protected from physical and environmental threats.", []),
    ("7.6", "Working in secure areas", "Rules apply to work inside secure areas.", []),
    ("7.7", "Clear desk and clear screen", "Desks and screens are kept clear of sensitive information.", []),
    ("7.8", "Equipment siting and protection", "Equipment is placed and protected safely.", []),
    ("7.9", "Security of assets off-premises", "Assets used off site are protected.", []),
    ("7.10", "Storage media", "Storage media are managed through their life cycle.", []),
    ("7.11", "Supporting utilities", "Facilities are protected from utility failures.", []),
    ("7.12", "Cabling security", "Power and data cables are protected.", []),
    ("7.13", "Equipment maintenance", "Equipment is maintained correctly.", []),
    ("7.14", "Secure disposal or re-use of equipment", "Data is removed before equipment is disposed of or reused.", []),
    ("8.1", "User endpoint devices", "Information on user devices is protected.", []),
    ("8.2", "Privileged access rights", "Privileged access is restricted and managed.", ["admin_count", "access_review_recent"]),
    ("8.3", "Information access restriction", "Access to information follows the access policy.", ["ai_approvals", "pending_requests"]),
    ("8.4", "Access to source code", "Access to source code and tools is managed.", []),
    ("8.5", "Secure authentication", "Authentication technologies and procedures are secure.", ["sso_enforced", "owner_mfa"]),
    ("8.6", "Capacity management", "Resource use is monitored and planned.", []),
    ("8.7", "Protection against malware", "Protection against malware is in place.", []),
    ("8.8", "Management of technical vulnerabilities", "Technical vulnerabilities are found and fixed.", []),
    ("8.9", "Configuration management", "Secure configurations are set, recorded and reviewed.", ["encryption"]),
    ("8.10", "Information deletion", "Information is deleted when no longer needed.", ["retention_policy"]),
    ("8.11", "Data masking", "Data is masked where policy requires.", ["ai_data_policy"]),
    ("8.12", "Data leakage prevention", "Measures prevent sensitive data leaking.", ["ai_data_policy", "external_agents"]),
    ("8.13", "Information backup", "Backups are kept and tested.", ["backup_export"]),
    ("8.14", "Redundancy of information processing facilities", "Processing facilities have enough redundancy.", []),
    ("8.15", "Logging", "Activity logs are produced, protected and analysed.", ["audit_log"]),
    ("8.16", "Monitoring activities", "Systems are monitored for unusual behaviour.", ["audit_log"]),
    ("8.17", "Clock synchronization", "System clocks are synchronized.", []),
    ("8.18", "Use of privileged utility programs", "Powerful utility programs are restricted.", []),
    ("8.19", "Installation of software on operational systems", "Software installation on live systems is controlled.", []),
    ("8.20", "Networks security", "Networks are secured and managed.", []),
    ("8.21", "Security of network services", "Network service security is defined and monitored.", []),
    ("8.22", "Segregation of networks", "Groups of services and users are separated on networks.", []),
    ("8.23", "Web filtering", "Access to external websites is managed.", []),
    ("8.24", "Use of cryptography", "Cryptography and key management follow defined rules.", ["encryption"]),
    ("8.25", "Secure development life cycle", "Secure development rules are applied.", []),
    ("8.26", "Application security requirements", "Security requirements are set for applications.", ["ai_approvals"]),
    ("8.27", "Secure system architecture and engineering principles", "Secure engineering principles are applied.", []),
    ("8.28", "Secure coding", "Secure coding practices are applied.", []),
    ("8.29", "Security testing in development and acceptance", "Security testing is part of development.", []),
    ("8.30", "Outsourced development", "Outsourced development is directed and monitored.", []),
    ("8.31", "Separation of development, test and production environments", "Development, test and production are kept apart.", []),
    ("8.32", "Change management", "Changes follow change management procedures.", ["ai_approvals"]),
    ("8.33", "Test information", "Test data is chosen and protected.", []),
    ("8.34", "Protection of information systems during audit testing", "Audit tests on live systems are planned and agreed.", []),
]
ISO_THEMES = {"5": "Organizational", "6": "People", "7": "Physical", "8": "Technological"}


def _build():
    rows = []
    for cid, group, name, summary, checks in _SOC2:
        rows.append({"framework": SOC2, "id": cid, "group": group, "group_name": SOC2_GROUPS[group], "name": name, "summary": summary, "checks": list(checks)})
    for cid, name, summary, checks in _ISO:
        theme = cid.split(".")[0]
        rows.append({"framework": ISO, "id": cid, "group": theme, "group_name": ISO_THEMES[theme], "name": name, "summary": summary, "checks": list(checks)})
    return rows


CONTROLS = _build()
BY_KEY = {(c["framework"], c["id"]): c for c in CONTROLS}


def controls(framework=None):
    return [c for c in CONTROLS if framework is None or c["framework"] == framework]


def control(framework, control_id):
    return BY_KEY.get((framework, control_id))

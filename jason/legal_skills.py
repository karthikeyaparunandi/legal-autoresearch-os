from __future__ import annotations

from dataclasses import dataclass


PRIMARY_LEGAL_SOURCE_TYPES = {"statute", "case_law", "agency_guidance", "regulation", "official_material"}

LEGAL_AUTHORITY_HIERARCHY = (
    "controlling statutes and constitutional text",
    "binding appellate or trial-court decisions",
    "final regulations and agency guidance",
    "procedural rules and official forms",
    "persuasive cases, secondary sources, and expert analysis",
)

LEGAL_TRIGGER_TERMS = (
    "legal",
    "law",
    "lawyer",
    "attorney",
    "counsel",
    "jurisdiction",
    "statute",
    "regulation",
    "case law",
    "court",
    "contract",
    "agreement",
    "nda",
    "msa",
    "dpa",
    "terms",
    "privacy",
    "compliance",
    "copyright",
    "trademark",
    "patent",
    "ip ",
    "litigation",
    "lawsuit",
    "subpoena",
    "employment",
    "termination",
    "worker classification",
    "ai governance",
    "impact assessment",
    "regulatory",
)


@dataclass(frozen=True)
class LegalSource:
    source_type: str
    title: str
    url: str
    excerpt: str
    reliability: float

    def as_worker_source(self) -> tuple[str, str, str, str, float]:
        return (self.source_type, self.title, self.url, self.excerpt, self.reliability)


@dataclass(frozen=True)
class LegalSkill:
    name: str
    description: str
    triggers: tuple[str, ...]
    subquestions: tuple[str, ...]
    required_source_types: tuple[str, ...]
    output_checks: tuple[str, ...]
    authorities: tuple[LegalSource, ...]


COMMON_LEGAL_OUTPUT_CHECKS = (
    "Identify jurisdiction, governing law, and authority date before applying the rule.",
    "Separate binding authority from persuasive or operational guidance.",
    "Quote or summarize only authority that directly supports the linked claim.",
    "Flag missing facts, unsettled doctrine, deadlines, and human-review requirements.",
    "Do not present the report as legal advice.",
)


GENERAL_LEGAL_RESEARCH = LegalSkill(
    name="general_legal_research",
    description="Issue-spotting, authority hierarchy, jurisdiction scoping, and risk framing for legal research.",
    triggers=("legal", "law", "jurisdiction", "statute", "case law", "court", "regulation"),
    subquestions=(
        "Which jurisdiction, governing law, and authority hierarchy control the question?",
        "What primary authorities directly support or contradict each material claim?",
        "Which facts, dates, procedural posture, or missing records could change the answer?",
    ),
    required_source_types=("statute", "case_law", "regulation", "agency_guidance", "official_material"),
    output_checks=COMMON_LEGAL_OUTPUT_CHECKS,
    authorities=(
        LegalSource(
            "official_material",
            "GovInfo United States Code",
            "https://www.govinfo.gov/app/collection/uscode",
            "GovInfo is the official publication platform for the United States Code and supports statute-first research.",
            0.94,
        ),
        LegalSource(
            "regulation",
            "Electronic Code of Federal Regulations",
            "https://www.ecfr.gov/",
            "The eCFR provides current federal regulatory text for agency-rule analysis.",
            0.93,
        ),
        LegalSource(
            "official_material",
            "Federal Register",
            "https://www.federalregister.gov/",
            "The Federal Register publishes proposed rules, final rules, notices, and agency guidance with dates and agency provenance.",
            0.9,
        ),
    ),
)


LEGAL_SKILLS: tuple[LegalSkill, ...] = (
    LegalSkill(
        name="commercial_legal",
        description="Contract review, NDA triage, SaaS/vendor terms, deviation summaries, and fallback-position analysis.",
        triggers=("contract", "agreement", "nda", "msa", "vendor", "saas", "subscription", "terms", "redline"),
        subquestions=(
            "Which contract type, counterparty posture, governing law, and playbook position control review?",
            "Which clauses create material risk, require fallback language, or need escalation?",
            "Which renewal, termination, liability, data, IP, or assignment terms affect business stakeholders?",
        ),
        required_source_types=("official_material", "statute", "case_law"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Map every issue to clause text, playbook position, risk level, and proposed fallback.",),
        authorities=(
            LegalSource(
                "official_material",
                "Uniform Law Commission Uniform Commercial Code",
                "https://www.uniformlaws.org/acts/ucc",
                "The UCC is a common starting point for sales and commercial transaction rules before checking enacted state law.",
                0.84,
            ),
            LegalSource(
                "official_material",
                "SEC EDGAR company filings",
                "https://www.sec.gov/edgar",
                "SEC filings can provide public examples of commercial agreements and disclosed contract-risk language.",
                0.83,
            ),
        ),
    ),
    LegalSkill(
        name="corporate_legal",
        description="M&A diligence, board materials, governance, disclosure schedules, and entity-compliance review.",
        triggers=("m&a", "merger", "acquisition", "diligence", "board", "governance", "disclosure schedule", "closing checklist"),
        subquestions=(
            "Which entity, transaction posture, governance document, and approval threshold control the analysis?",
            "Which diligence issues are material, consent-triggering, disclosure-schedule-worthy, or closing blockers?",
            "Which board, shareholder, securities, or entity-compliance records are missing?",
        ),
        required_source_types=("statute", "regulation", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Separate legal blockers from diligence follow-ups and business-consent items.",),
        authorities=(
            LegalSource(
                "statute",
                "Delaware General Corporation Law",
                "https://delcode.delaware.gov/title8/c001/",
                "The DGCL is a common primary source for Delaware corporate governance and approval requirements.",
                0.92,
            ),
            LegalSource(
                "regulation",
                "SEC Rules and Regulations for Securities and Exchange Commission",
                "https://www.ecfr.gov/current/title-17/chapter-II",
                "Title 17, Chapter II of the eCFR contains federal securities regulations relevant to public-company and transaction analysis.",
                0.91,
            ),
        ),
    ),
    LegalSkill(
        name="employment_legal",
        description="Jurisdiction-aware hiring, termination, worker classification, leave, investigation, and policy review.",
        triggers=("employment", "employee", "termination", "hire", "leave", "worker classification", "contractor", "flsa", "eeoc"),
        subquestions=(
            "Which worker location, employer footprint, classification, and policy source controls?",
            "Which wage-hour, anti-discrimination, leave, notice, or termination requirements apply?",
            "Which deadlines, protected categories, investigation records, or state supplements need review?",
        ),
        required_source_types=("statute", "regulation", "agency_guidance", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Separate federal baseline requirements from state or local supplements.",),
        authorities=(
            LegalSource(
                "agency_guidance",
                "U.S. Department of Labor Fair Labor Standards Act resources",
                "https://www.dol.gov/agencies/whd/flsa",
                "DOL FLSA resources support wage-hour, overtime, and worker-classification analysis.",
                0.91,
            ),
            LegalSource(
                "agency_guidance",
                "U.S. Equal Employment Opportunity Commission guidance",
                "https://www.eeoc.gov/guidance",
                "EEOC guidance supports anti-discrimination, harassment, accommodation, and retaliation analysis.",
                0.9,
            ),
        ),
    ),
    LegalSkill(
        name="privacy_legal",
        description="DPA review, PIA/DPIA triage, DSAR timelines, privacy-policy drift, and data-processing risk.",
        triggers=("privacy", "dpa", "dpia", "pia", "dsar", "data subject", "ccpa", "cpra", "gdpr", "personal data"),
        subquestions=(
            "Which data types, data subjects, processing purposes, vendors, and jurisdictions are in scope?",
            "Which notice, consent, DPA, DSAR, retention, transfer, and security duties apply?",
            "Does the privacy policy, product behavior, and vendor paper stay aligned?",
        ),
        required_source_types=("statute", "regulation", "agency_guidance", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Track statutory timelines and policy-practice drift explicitly.",),
        authorities=(
            LegalSource(
                "official_material",
                "California Privacy Protection Agency CCPA regulations",
                "https://cppa.ca.gov/regulations/",
                "The CPPA publishes California privacy regulations and rulemaking materials for CCPA/CPRA analysis.",
                0.91,
            ),
            LegalSource(
                "official_material",
                "European Commission data protection rules",
                "https://commission.europa.eu/law/law-topic/data-protection_en",
                "European Commission materials support GDPR-oriented privacy analysis and cross-border data-transfer scoping.",
                0.88,
            ),
        ),
    ),
    LegalSkill(
        name="product_legal",
        description="Product launch review, marketing-claims substantiation, feature review, and business-readable risk translation.",
        triggers=("product", "launch", "marketing claim", "substantiation", "advertising", "feature review", "can we do this"),
        subquestions=(
            "Which product behavior, user promise, audience, and jurisdiction are in scope?",
            "Which claims need substantiation, disclosure, consent, or risk escalation?",
            "Which legal risks block launch versus require mitigation or business acceptance?",
        ),
        required_source_types=("agency_guidance", "regulation", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Translate findings into launch blockers, mitigations, and owner-ready next actions.",),
        authorities=(
            LegalSource(
                "agency_guidance",
                "FTC business guidance",
                "https://www.ftc.gov/business-guidance",
                "FTC business guidance supports marketing, advertising, consumer-protection, and substantiation review.",
                0.89,
            ),
            LegalSource(
                "official_material",
                "Federal Trade Commission policy statements",
                "https://www.ftc.gov/legal-library/browse/policy-statements",
                "FTC policy statements help distinguish consumer-protection rules and enforcement priorities.",
                0.88,
            ),
        ),
    ),
    LegalSkill(
        name="regulatory_legal",
        description="Regulatory monitoring, rule diffs, comment deadlines, gap analysis, and compliance update drafting.",
        triggers=("regulatory", "regulation", "rulemaking", "comment deadline", "compliance", "policy update", "audit"),
        subquestions=(
            "Which regulator, rule stage, effective date, comment deadline, and materiality threshold apply?",
            "What changed against the current policy or control library?",
            "Which obligations, gaps, owners, and review deadlines should be tracked?",
        ),
        required_source_types=("regulation", "agency_guidance", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Record effective dates, comment periods, and update owners.",),
        authorities=(
            LegalSource(
                "official_material",
                "Federal Register",
                "https://www.federalregister.gov/",
                "The Federal Register provides dated proposed rules, final rules, notices, and comment-period records.",
                0.9,
            ),
            LegalSource(
                "regulation",
                "Electronic Code of Federal Regulations",
                "https://www.ecfr.gov/",
                "The eCFR provides current codified federal regulatory text for compliance-gap analysis.",
                0.93,
            ),
        ),
    ),
    LegalSkill(
        name="ai_governance_legal",
        description="AI use-case triage, impact assessments, vendor AI terms, model-policy review, and governance tiers.",
        triggers=("ai governance", "ai policy", "impact assessment", "model policy", "vendor ai", "ai use case", "automated decision"),
        subquestions=(
            "Which AI use case, risk tier, user impact, data source, and vendor responsibility are in scope?",
            "Which impact-assessment, transparency, safety, privacy, and human-oversight controls apply?",
            "Does the policy framework match actual AI deployment and procurement practice?",
        ),
        required_source_types=("official_material", "agency_guidance", "regulation"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Flag high-impact use cases and anything requiring specialist review.",),
        authorities=(
            LegalSource(
                "official_material",
                "NIST AI Risk Management Framework",
                "https://www.nist.gov/itl/ai-risk-management-framework",
                "NIST AI RMF materials support AI governance, risk-tiering, documentation, and oversight analysis.",
                0.86,
            ),
            LegalSource(
                "agency_guidance",
                "FTC artificial intelligence business guidance",
                "https://www.ftc.gov/business-guidance/blog/2023/02/keep-your-ai-claims-check",
                "FTC AI business guidance supports review of AI claims, deception risk, and substantiation obligations.",
                0.85,
            ),
        ),
    ),
    LegalSkill(
        name="ip_legal",
        description="Trademark clearance, FTO triage, DMCA takedowns, OSS compliance, IP clause review, invention intake, and portfolio tracking.",
        triggers=("copyright", "trademark", "patent", "ip ", "intellectual property", "dmca", "oss", "open source", "invention", "freedom to operate"),
        subquestions=(
            "Which IP right, asset, owner, jurisdiction, and chain of title are in scope?",
            "Which registration, infringement, license, clearance, or ownership authorities control?",
            "Which specialist-review guardrails apply before any enforcement or filing action?",
        ),
        required_source_types=("statute", "case_law", "agency_guidance", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Escalate filings, opinions, enforcement threats, and specialist-only determinations.",),
        authorities=(
            LegalSource(
                "agency_guidance",
                "U.S. Copyright Office artificial intelligence initiative",
                "https://www.copyright.gov/ai/",
                "The Copyright Office AI page collects agency materials on copyright registration, authorship, and AI-generated material.",
                0.93,
            ),
            LegalSource(
                "official_material",
                "USPTO Trademark Manual of Examining Procedure",
                "https://tmep.uspto.gov/",
                "The TMEP is an official USPTO examination reference for trademark clearance and prosecution questions.",
                0.9,
            ),
        ),
    ),
    LegalSkill(
        name="litigation_legal",
        description="Matter intake, legal holds, demand letters, subpoena triage, chronologies, deposition prep, privilege logs, claim charts, and brief drafting.",
        triggers=("litigation", "lawsuit", "pleading", "motion", "brief", "deposition", "subpoena", "discovery", "privilege", "claim chart"),
        subquestions=(
            "Which forum, procedural posture, claims, defenses, deadlines, and record materials are in scope?",
            "Which rules, pleadings, facts, and authority control the next litigation step?",
            "Which privilege, preservation, discovery, or deadline risks require lawyer review?",
        ),
        required_source_types=("statute", "case_law", "regulation", "official_material"),
        output_checks=COMMON_LEGAL_OUTPUT_CHECKS
        + ("Track procedural posture, record citations, privilege limits, and deadline uncertainty.",),
        authorities=(
            LegalSource(
                "official_material",
                "Federal Rules of Civil Procedure",
                "https://www.uscourts.gov/rules-policies/current-rules-practice-procedure/federal-rules-civil-procedure",
                "The federal civil rules support procedural analysis for pleadings, discovery, motions, and judgments.",
                0.91,
            ),
            LegalSource(
                "official_material",
                "United States Courts forms and rules",
                "https://www.uscourts.gov/forms-rules",
                "Official court forms and rules help ground litigation workflow, filing, and procedural analysis.",
                0.88,
            ),
        ),
    ),
)


AI_COPYRIGHT_SOURCES: dict[str, tuple[LegalSource, ...]] = {
    "c001": (
        LegalSource(
            "agency_guidance",
            "U.S. Copyright Office, Copyright Registration Guidance: Works Containing Material Generated by Artificial Intelligence",
            "https://www.copyright.gov/ai/ai_policy_guidance.pdf",
            "The Copyright Office requires applicants to identify and disclaim AI-generated material when human authorship is insufficient.",
            0.95,
        ),
        LegalSource(
            "case_law",
            "Thaler v. Perlmutter, No. 23-5233 (D.C. Cir. 2025)",
            "https://media.cadc.uscourts.gov/opinions/docs/2025/03/23-5233.pdf",
            "The D.C. Circuit affirmed rejection of a registration application where the asserted author was an AI system rather than a human.",
            0.92,
        ),
    ),
    "c002": (
        LegalSource(
            "statute",
            "17 U.S.C. Section 102",
            "https://www.govinfo.gov/content/pkg/USCODE-2023-title17/html/USCODE-2023-title17-chap1-sec102.htm",
            "Section 102 protects original works of authorship fixed in a tangible medium, making authorship and expression central to the analysis.",
            0.94,
        ),
        LegalSource(
            "agency_guidance",
            "U.S. Copyright Office AI policy and guidance",
            "https://www.copyright.gov/ai/",
            "Copyright Office AI materials distinguish unprotectable AI-generated content from protectable human selection, arrangement, or modification.",
            0.93,
        ),
    ),
    "c003": (
        LegalSource(
            "case_law",
            "Thaler v. Perlmutter, No. 23-5233 (D.C. Cir. 2025)",
            "https://media.cadc.uscourts.gov/opinions/docs/2025/03/23-5233.pdf",
            "The decision treats human authorship as a boundary condition while leaving room to analyze human contributions on different records.",
            0.92,
        ),
        LegalSource(
            "agency_guidance",
            "U.S. Copyright Office AI initiative",
            "https://www.copyright.gov/ai/",
            "The agency's AI materials support careful separation between autonomous generation and human-authored expression in AI-assisted works.",
            0.93,
        ),
    ),
    "c004": (
        LegalSource(
            "agency_guidance",
            "U.S. Copyright Office AI policy and guidance",
            "https://www.copyright.gov/ai/",
            "Copyright Office AI guidance creates diligence issues for ownership, registration scope, and documentation of human contribution.",
            0.9,
        ),
        LegalSource(
            "agency_guidance",
            "FTC business guidance on artificial intelligence claims",
            "https://www.ftc.gov/business-guidance/blog/2023/02/keep-your-ai-claims-check",
            "FTC AI guidance supports risk review for overstated claims, substantiation, and deceptive AI-product representations.",
            0.84,
        ),
    ),
}


def is_legal_goal(goal: str) -> bool:
    lower = f" {goal.lower()} "
    return any(trigger in lower for trigger in LEGAL_TRIGGER_TERMS)


def match_legal_skills(goal: str) -> list[LegalSkill]:
    lower = f" {goal.lower()} "
    matches = [skill for skill in LEGAL_SKILLS if any(trigger in lower for trigger in skill.triggers)]
    if is_legal_goal(goal) and not matches:
        matches = [GENERAL_LEGAL_RESEARCH]
    return _dedupe_skills(matches)


def legal_skill_names(goal: str) -> list[str]:
    return [skill.name for skill in match_legal_skills(goal)]


def legal_subquestions_for_goal(goal: str) -> list[str]:
    questions = [
        "Which jurisdiction, governing law, authority hierarchy, and date sensitivity control the analysis?",
        "Which practice-area skill or skills should be applied to the matter?",
        "Which primary legal authorities directly support or contradict each material claim?",
        "What facts, procedural posture, contractual language, or data-processing details could change the answer?",
        "What practical risks, deadlines, approval paths, or human-review gates follow from the authority?",
    ]
    for skill in match_legal_skills(goal):
        questions.extend(skill.subquestions[:2])
    return _dedupe_strings(questions)[:9]


def legal_claims_for_goal(goal: str) -> list[str]:
    lower = goal.lower()
    if "ai-generated code" in lower and "copyright" in lower:
        return [
            "Pure AI-generated code is unlikely to be copyrightable in the United States without sufficient human authorship.",
            "AI-assisted code may still contain protectable human expression when people select, arrange, modify, or author expressive code.",
            "The hard legal boundary is the difference between autonomous generation, prompting, and human control over protectable expression.",
            "A startup relying on AI-generated software faces ownership, registration, license-compliance, infringement, diligence, and marketing-claims risk.",
        ]

    names = ", ".join(legal_skill_names(goal)) or "general_legal_research"
    topic = _compact_topic(goal)
    return [
        f"The legal answer for {topic} must be scoped by jurisdiction, governing law, authority date, and practice-area skill ({names}).",
        f"Primary legal authority is required before any material conclusion about {topic} should be treated as supported.",
        f"Competing interpretations, missing facts, and procedural posture may change the risk assessment for {topic}.",
        f"The final work product for {topic} should separate legal analysis, business risk, deadlines, escalation needs, and human review.",
    ]


def legal_contradiction_note(goal: str) -> str:
    skills = ", ".join(legal_skill_names(goal)) or "general legal research"
    return (
        f"Legal conclusions may conflict until jurisdiction, date, facts, authority level, and {skills} scope are fixed."
    )


def legal_evidence_requirements_for_goal(goal: str) -> list[str]:
    source_types = ["statute", "case_law", "regulation", "agency_guidance", "official_material"]
    for skill in match_legal_skills(goal):
        source_types.extend(skill.required_source_types)
    checks = [
        "Prefer primary legal sources over commentary.",
        "Every material legal claim must cite direct authority or be marked unsupported.",
        "Distinguish binding authority, persuasive authority, agency guidance, and operational playbook guidance.",
        "Track jurisdiction, procedural posture, authority date, and temporal validity.",
        "Surface unsettled doctrine, missing facts, deadlines, and specialist-review requirements.",
    ]
    return checks + [f"Required source types: {', '.join(_dedupe_strings(source_types))}."]


def legal_source_for_claim(claim_id: str, claim: str, objective: str, purpose: str) -> LegalSource:
    text = f"{objective} {claim}".lower()
    if "ai-generated code" in text and "copyright" in text:
        sources = AI_COPYRIGHT_SOURCES.get(claim_id, AI_COPYRIGHT_SOURCES["c001"])
        return _select_source(sources, purpose)

    matches = match_legal_skills(text)
    if not matches:
        matches = [GENERAL_LEGAL_RESEARCH]
    skill_index = _claim_index(claim_id) % len(matches)
    authorities = matches[skill_index].authorities or GENERAL_LEGAL_RESEARCH.authorities
    return _select_source(authorities, purpose)


def legal_report_sections(objective: str) -> list[str]:
    skills = match_legal_skills(objective)
    skill_names = ", ".join(skill.name for skill in skills) or "general_legal_research"
    hierarchy = "; ".join(LEGAL_AUTHORITY_HIERARCHY)
    requirements = legal_evidence_requirements_for_goal(objective)
    return [
        "## Legal Analysis Framework",
        (
            f"Jason treated this as a legal research matter and activated these legal skill paths: {skill_names}. "
            "The analysis starts with jurisdiction and authority hierarchy, then links each material claim to accepted evidence."
        ),
        "",
        "## Authority And Citation Discipline",
        f"Authority hierarchy used: {hierarchy}. Claims without accepted authority remain weak; secondary or operational sources cannot replace controlling legal authority.",
        "",
        "## Legal Evidence Requirements",
        *[f"- {item}" for item in requirements],
        "",
        "## Risk And Human Review",
        (
            "This report is decision support, not legal advice. A lawyer should review jurisdictional assumptions, currentness, "
            "deadlines, privilege issues, specialist-only questions, and any proposed filing, enforcement, termination, or external communication."
        ),
    ]


def _select_source(sources: tuple[LegalSource, ...], purpose: str) -> LegalSource:
    if len(sources) == 1:
        return sources[0]
    if purpose == "citation":
        return sources[1]
    if purpose == "implication":
        return sources[-1]
    return sources[0]


def _claim_index(claim_id: str) -> int:
    digits = "".join(character for character in claim_id if character.isdigit())
    return max(0, int(digits or "1") - 1)


def _compact_topic(goal: str) -> str:
    words = [word.strip(" ,.?;:()[]{}").lower() for word in goal.split()]
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "what", "how", "please"}
    keywords = [word for word in words if word and word not in stop]
    return " ".join(keywords[:8]) or "the legal question"


def _dedupe_skills(skills: list[LegalSkill]) -> list[LegalSkill]:
    seen: set[str] = set()
    unique: list[LegalSkill] = []
    for skill in skills:
        if skill.name not in seen:
            unique.append(skill)
            seen.add(skill.name)
    return unique


def _dedupe_strings(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique

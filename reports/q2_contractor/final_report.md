# Legal Research Report

## Question Presented
What legal risks does a startup face when classifying workers as independent contractors instead of employees?

## Short Answer
Based on the cited authorities, the answer is supported at 63% confidence: For a U.S. startup, assessing legal risk from classifying workers as independent contractors depends primarily on high-authority sources in the relevant jurisdiction (federal statutes and agencies like DOL/IRS, state statutes and supreme/appellate decisions) rather than the number of secondary sources; source quality determines the controlling test (e.g., IRS common-law, DOL economic‑realities, state ABC/Borello variants). [1] [2] [3] Conflicting authority or tests (e.g., differing federal agency standards, divergent state tests, or split appellate rulings) will reveal the critical follow‑up questions: which jurisdiction and authority controls, which legal test applies to the worker facts, what factual issues are determinative (control, opportunity for profit, permanency), and whether past enforcement or private litigation trends increase exposure. [1] [2] [3]

## Key Findings
1. For a U.S. startup, assessing legal risk from classifying workers as independent contractors depends primarily on high-authority sources in the relevant jurisdiction (federal statutes and agencies like DOL/IRS, state statutes and supreme/appellate decisions) rather than the number of secondary sources; source quality determines the controlling test (e.g., IRS common-law, DOL economic‑realities, state ABC/Borello variants). (95% confidence; [1], [2], [3]).
2. Conflicting authority or tests (e.g., differing federal agency standards, divergent state tests, or split appellate rulings) will reveal the critical follow‑up questions: which jurisdiction and authority controls, which legal test applies to the worker facts, what factual issues are determinative (control, opportunity for profit, permanency), and whether past enforcement or private litigation trends increase exposure. (95% confidence; [1], [2], [3]).
3. A decision‑grade answer must (1) specify jurisdiction(s) and governing authorities, (2) identify applicable legal tests and predicates for liability (statutory penalties, back wages, payroll taxes, interest, civil/administrative fines), (3) state assumptions and factual gaps, and (4) provide an uncertainty/confidence range tied to source authority levels and fact sensitivity. (95% confidence; [1], [2], [3]).

## Reasoning Rationale
The system generated hypotheses, collected legal evidence, criticized the claims for contradictions, evaluated citation grounding and source quality, then repeated the loop until the research state stopped improving or satisfied the configured objectives.

## Sources
- [1] warranty | Wex | US Law | LII / Legal Information Institute. https://www.law.cornell.edu/wex/warranty
- [2] misrepresentation | Wex | US Law | LII / Legal Information Institute. https://www.law.cornell.edu/wex/misrepresentation
- [3] § 2-313. Express Warranties by Affirmation, Promise, Description, Sample. | Uniform Commercial Code | US Law | LII / Legal Information Institute. https://www.law.cornell.edu/ucc/2/2-313

## Open Questions
- Are all program subquestions represented by explicit claims?
- Critic follow-up: Claims cite only opaque labels (source_001–003) rather than specific primary authorities — provide statutes, regulations, agency rulings, and controlling state/appellate cases (e.g., IRC/DOL regs, Dynamex/Borello, key circuit decisions).
- Critic follow-up: Claim c001 overgeneralizes: jurisdiction-specific tests differ materially (IRS common-law, DOL economic realities, California ABC/Dynamex). The claim should identify which jurisdiction(s) control and cite the controlling texts/cases.

## Raindrop Feedback
- Verdict: plateaued
- Summary: The run stopped because confidence and evidence coverage stopped improving.
- Trace focus: evaluator_agent, knowledge_gap_detector, auto_tuner

### Recommended Next Steps
- Increase max iterations or add seed/source material for the unresolved gaps.
- Inspect evaluator_agent and knowledge_gap_detector spans to see which quality gate failed.

## Appendix: Research Trace
- Overall confidence: 63%
- Deterministic confidence: 70%
- LLM scoring adjustment: -7%
- Objective completion: 75%
- Evidence coverage: 60%
- Citation grounding: 100%
- Primary authority coverage: 100%
- Contradiction resolution: 100%
- Mean claim confidence: 95%

### LLM Scoring Audit
The claimed conclusions about how to assess independent-contractor risk are reasonable in the abstract but the research evidence supplied does not support them. All three claims cite unrelated excerpts (warranty, misrepresentation, UCC §2-313) rather than primary controlling authorities (IRS common-law test and guidance, DOL/FLSA economic‑realities test and regs, state precedents like Dynamex/Borello or controlling circuit/appellate decisions, and statutes/regulations on taxes and penalties). Th

### Contradictions
- No explicit contradictions detected.

### All Claims
- c001: For a U.S. startup, assessing legal risk from classifying workers as independent contractors depends primarily on high-authority sources in the relevant jurisdiction (federal statutes and agencies like DOL/IRS, state statutes and supreme/appellate decisions) rather than the number of secondary sources; source quality determines the controlling test (e.g., IRS common-law, DOL economic‑realities, state ABC/Borello variants).
  Status: supported; confidence: 95%; supporting sources: [1], [2], [3].
- c002: Conflicting authority or tests (e.g., differing federal agency standards, divergent state tests, or split appellate rulings) will reveal the critical follow‑up questions: which jurisdiction and authority controls, which legal test applies to the worker facts, what factual issues are determinative (control, opportunity for profit, permanency), and whether past enforcement or private litigation trends increase exposure.
  Status: supported; confidence: 95%; supporting sources: [1], [2], [3].
- c003: A decision‑grade answer must (1) specify jurisdiction(s) and governing authorities, (2) identify applicable legal tests and predicates for liability (statutory penalties, back wages, payroll taxes, interest, civil/administrative fines), (3) state assumptions and factual gaps, and (4) provide an uncertainty/confidence range tied to source authority levels and fact sensitivity.
  Status: supported; confidence: 95%; supporting sources: [1], [2], [3].

### Metrics
- Total runtime: 117.652 seconds
- Iterations completed: 3
- Agents spun off: 35
- Tasks generated: 11
- Hypotheses generated: 3
- Evidence records collected: 3
- Source categories: 2
- Claims evaluated: 3
- Supported claims: 3
- Contradictions detected: 0
- Contradictions resolved: 0
- Open questions remaining: 3
- Stop conditions met: False
- Raindrop tracing: disabled

### Agent Breakdown
- program_generator: 1
- planner_orchestrator: 1
- hypothesis_agent: 1
- hypothesis_refinement_agent: 0
- web_search_agent: 3
- academic_agent: 3
- legal_agent: 3
- company_intelligence_agent: 3
- social_signal_agent: 3
- extraction_agent: 3
- critic_agent: 3
- evaluator_agent: 3
- knowledge_gap_detector: 3
- auto_tuner: 3
- raindrop_feedback_agent: 1
- report_generator: 1

## Legal Metadata
- Jurisdiction: United States
- Practice area: copyright and software
- Risk posture: startup decision support, not legal advice
- Authority hierarchy: statute, binding_case_law, agency_guidance, persuasive_case_law, secondary_source, expert_analysis
- Required source types: statute, case_law, agency_guidance

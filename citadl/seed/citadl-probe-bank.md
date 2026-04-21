# CITADL Probe Bank — Candidate Questions Organized by Rubric Axis

This document is a resource for Mira's Brain B, not a script for Brain A. The probes below are candidate openings and follow-ups Brain B may draw from when deciding what to ask next. They are organized by the eight rubric axes R1–R8 that define coverage for the `citadl-community-pulse` campaign. Each axis section names its purpose, the trigger conditions that suggest Brain B should deepen the axis, phrasing variants that span the respondent register (peer-scientist, peer-sysadmin, peer-ML-researcher, peer-institutional-lead), and follow-up pathways for going deeper when the respondent opens a door.

Brain B is authoritative over probe selection. Nothing below is scripted order. The bank is a library Brain B searches via `search_knowledge` during planning, selects from based on the respondent profile and current saturation state, and rephrases through Brain A's voice. The bank was built by distilling a 60-item draft survey authored by the CITADL-P planning-grant lead into conversational probes with the scripted structure removed. Some probes are direct adaptations of the draft's items. Others are new, introduced to cover axes the original draft treated thinly, especially R3 cross-phase coordination and R8 disconfirmation.

A probe is considered "fired" when the respondent's answer has engaged with the underlying question, not when the specific phrase was uttered. Brain B tracks coverage by meaning, not by string match.

---

## R1 — Lifecycle pain topology

**Purpose.** Map where friction actually concentrates in this respondent's real work, across the six phases. Surface concrete episodes rather than abstract self-assessments. Populate the requirements-traceability matrix that Task 1 of the Category I proposal will produce.

**Trigger conditions.** Brain B should fire R1 probes early in the conversation, once the respondent has identified their role and general work context. R1 is the largest axis by intended coverage for scientist-role and operator-role respondents. For ML-researcher respondents R1 is lighter weight; R3 and R5 dominate.

**Probe phrasings.**

When opening the topic broadly, any of: *Walk me through a typical end-to-end flow you ran recently, from where the data came from to where a result ended up.* / *Tell me about a recent dataset your group handled from start to finish — what happened at each stage.* / *Think of a research output you produced in the last six months. How did the data behind it travel from generation to published form?*

When funneling toward a specific pain point: *Where in that flow did you personally spend the most time?* / *At which stage did you most recently have to redo something because of a data-handling issue?* / *Which part of that workflow, if a tool or agent did it for you, would give you back the most hours a week?*

When asking for a specific recent episode: *Can you describe a moment in the last month or two where something in your data workflow actively cost you a day or more?* / *Tell me about the last time you lost data, had to regenerate data, or couldn't find data you knew you had.* / *When was the last time you found yourself doing something manual that you were sure should be automatic by now?*

For operators, reframed for the facility lens: *Describe the lifecycle of a typical dataset in your facility, from ingest to eventual archival or deletion.* / *What's the biggest operational headache across your storage and movement stack right now?*

For ML researchers, reframed for the systems lens: *Have you worked with any scientific data management system that particularly frustrated you? What was wrong with it?* / *When you've built or tested an agentic system against scientific data tasks, what was the typical failure mode?*

**Follow-up pathways.** When a respondent identifies a pain phase, Brain B should deepen with: how often does this happen, what does the workaround look like, who in your group is most burned by this, what would "no longer a problem" look like concretely. Resist moving to other phases before the current one has produced an episode with specific detail.

---

## R2 — Trust gating conditions

**Purpose.** Surface the specific conditions — technical, procedural, social — that would have to hold before this respondent would let an autonomous agent act on their workflow. Map the respondent's personal trust-zone geography: where they would accept autonomy, where they want asynchronous review, where they insist on synchronous oversight, where they refuse agent involvement entirely.

**Trigger conditions.** Fire R2 after the respondent has surfaced at least one lifecycle pain in R1 and after the word "agent" or "autonomous" or "AI" has been introduced, ideally by the respondent rather than by Mira. If Mira introduces the framing, R2's signal is partly contaminated; note this in the audit.

**Probe phrasings.**

When opening trust as a topic: *When a tool or service produces something you need to trust, what do you actually do before you let that output count toward a real result?* / *What convinces you that an automated step was done correctly?* / *When do you check behind a tool, and when do you just accept what it gave you?*

When eliciting the autonomy-acceptance line: *Imagine an agent could take one action in your workflow without asking you first. What action would that be, and what would have to be true for you to accept it?* / *Where in your workflow would you let an agent act without your approval, and where would you insist on being asked?* / *What's the first task you'd be willing to hand off to an agent, and what's the last task you'd ever hand off?*

When testing the disqualification conditions: *What would an agent have to do for you to stop trusting it permanently?* / *What kind of mistake would kill your willingness to use the system?* / *If an agent made a wrong decision on your data once, what would it take to earn your trust back?*

When mapping the zone geography directly: *Walk me through your workflow again, but this time tell me at each stage whether you'd accept full autonomy, asynchronous review, synchronous oversight, or no agent involvement at all.* / *Where does your personal line sit between "I want the agent to do it" and "I want to do it myself"?*

**Follow-up pathways.** For every trust condition a respondent names — audit trail, rollback, human-in-the-loop, domain validation, explainability — Brain B should probe what specifically that condition means in their context. "Audit trail" means very different things to a materials scientist, a facility operator, and an ML researcher. Concrete operational definitions matter more than abstract preferences.

---

## R3 — Cross-phase coordination

**Purpose.** Elicit narrative evidence for CITADL's central thesis — that the friction is at the phase boundaries, not inside the phases. Collect concrete moments where something in one phase should have informed another phase and did not.

**Trigger conditions.** Fire R3 after R1 has surfaced pain in at least one phase. R3 is the hardest axis for respondents to answer abstractly; it almost always requires anchoring in an episode they have already told Mira about.

**Probe phrasings.**

When asking for a cross-phase moment: *Can you describe a time when something that happened during data acquisition should have shaped how you stored it, or how you moved it later, but didn't?* / *Think of a moment when a decision made at one stage of your workflow came back to haunt you at a later stage. What was the disconnect?* / *Have you ever found yourself wishing the tool you were using knew about the previous step? When?*

When asking about information loss at handoffs: *At which handoff between phases do you feel the most context gets lost?* / *Between acquisition and preparation, preparation and storage, storage and movement — which handoff is the costliest for your group?*

When probing the coordination vision: *If the system could automatically use what it learned from your last project to shape how it handles your next project, what would the biggest win be?* / *What would it mean for your workflow if every phase of it shared the same provenance and context with every other phase?*

For operators: *Which hand-off in the data lifecycle breaks most often for your users?* / *When a user's job fails, how often is the root cause in a different phase than the one the failure was observed in?*

**Follow-up pathways.** When the respondent surfaces a handoff pain, Brain B should probe: did you ever work around this by wiring the phases together manually, did that work, what tradeoffs did the workaround create, would you trust an agent to do that wiring for you.

---

## R4 — Natural-language intent

**Purpose.** Collect the concrete sentences this respondent wishes they could say to a system and have executed. These sentences, aggregated across the cohort, become an evidence base for the Category I proposal's opening narrative and Table 1.

**Trigger conditions.** Fire R4 once the respondent has sufficiently described their workflow that a meaningful intent sentence is possible. Usually mid-to-late conversation. Fire it on every respondent; R4 is not optional.

**Probe phrasings.**

When opening the topic: *If you could say one sentence to a system and have it carry out the work that would otherwise take you days, what would that sentence be?* / *What's the one thing you wish you could describe to an AI and just have it done?* / *Imagine the system understood your research intent perfectly. What would you ask it for first?*

When extracting more than one intent: *Is there a second thing, maybe larger in scope, you'd want to ask for?* / *What's the ambitious version of that request — the version you'd want in three years?* / *What's the modest version — the version you'd trust today?*

When probing why the intent matters: *What's the work that sentence would save you?* / *Who else in your group would ask for something similar?* / *How often does the situation come up where you'd want to say that?*

For operators, where the intent may be operational rather than research: *What operational command would you want to hand to an agent on behalf of your users?* / *What "if only the system did this automatically" moment recurs in your facility?*

For ML researchers, where the intent may be about the system being built rather than consumed: *If you had to expose one high-level interface to a scientist who has no AI background, what would that interface be?* / *What level of intent do you think is actually learnable end-to-end with current foundation models?*

**Follow-up pathways.** Push for specificity. A sentence like "the agent should manage my data" is not R4 evidence. A sentence like "characterize phase evolution in this electrode family and compare with DFT predictions" is. When a respondent gives a generic intent, Brain B asks for the specific situation where it would apply.

---

## R5 — Adoption ceiling gradient

**Purpose.** Identify the gradient between the first task the respondent would delegate to an agent and the last task they would ever delegate. The gradient across the cohort is the adoption roadmap by domain and role.

**Trigger conditions.** Fire R5 after R2 (trust) has produced at least one signal. R5 complements R2: trust is about conditions, R5 is about the task inventory.

**Probe phrasings.**

When asking for the first-delegable task: *Of everything you do in your workflow, what's the task you'd be most willing to hand off to an agent first?* / *What's the lowest-stakes piece of your work that an agent could plausibly take over tomorrow?* / *Which part of your workflow would you happily never do again if you could?*

When asking for the never-delegable task: *Is there anything in your workflow that you believe should never be fully automated — that always requires human judgment?* / *What's the work you'd refuse to hand over even if the agent was demonstrated to do it well?* / *Where is the line between "this is data plumbing" and "this is my research"?*

When mapping the gradient: *If the agent handled the task you'd delegate first well for a year, what task would you add next?* / *What would the agent have to demonstrate to move from your first-delegable task to something one step harder?* / *What would earn it promotion to the next level of responsibility?*

For operators, reframed for stewardship: *What operational decision would you let an agent make without your review?* / *What operational decision would you never automate no matter how well the agent performed?*

**Follow-up pathways.** Ask for the reasoning behind where the line sits. Is it stakes? Is it attribution? Is it the respondent's sense of craft? Is it institutional policy? Different reasoning implies different architectural responses.

---

## R6 — Integration constraints

**Purpose.** Surface the technical, institutional, and practical constraints that a real deployment would have to honor to be accepted by this respondent's working context. Varies sharply by role.

**Trigger conditions.** Fire R6 once Brain B has enough profile to know whether the respondent is a consumer of infrastructure (scientist), a steward of infrastructure (operator), or a builder of systems that might become infrastructure (ML researcher).

**Probe phrasings.**

For scientists: *What platforms do you already trust enough that a new service attached to them would get the benefit of the doubt?* / *If CITADL shipped tomorrow, would it integrate with the environment you actually work in, or would you have to change your environment to use it?* / *What existing tool in your workflow would an AI-assisted data management system have to replace, and what would it have to preserve?*

For operators: *What API surface would your facility accept from an external agentic service?* / *Under what terms would you allow external agents to act on your systems — at what privilege level, with what sandboxing, through what authentication?* / *What federation model would work for your facility? What federation model would you refuse?* / *If an agent needs to run closer to your storage than a user's laptop but further away than your kernel, where exactly does it run?*

For ML researchers: *What foundation model capabilities do you think are actually ready to build production data-lifecycle agents on today?* / *What frameworks would you reach for first — and what would you build from scratch?* / *Which of today's architectural patterns — single-agent tool-use, multi-agent collaboration, hierarchical, reactive, planning — do you think is right for this domain?*

**Follow-up pathways.** Push on specific named systems. "ACCESS" or "NDP" or "NAIRR" or "Globus" or "HSDS" or "Lustre" or named frameworks. When a respondent mentions one, probe what their experience with it has been. Operators and ML researchers often know the realities behind the marketing better than any reference documentation.

---

## R7 — Community sovereignty

**Purpose.** Surface the respondent's view on who should own, govern, pay for, and sustain a national-scale agentic data management infrastructure. Evidence for Task 4 governance framework.

**Trigger conditions.** Fire R7 when the respondent's role gives them standing on the question. Most salient for senior researchers, PIs, facility operators, and platform leads. Lighter for early-career scientists and pure methods-ML researchers, though their view is still valuable.

**Probe phrasings.**

When opening the governance question: *If an infrastructure like this existed at national scale, who should run it?* / *Who should have authority over decisions the agents make on your data?* / *What existing governance model do you think a national agentic data platform could learn from?*

When probing accountability: *When an agent makes a consequential error in production, who should be responsible — the researcher, the developer, the operator, or some shared framework?* / *How should that responsibility be distributed?*

When probing sustainability: *What funding model do you think could keep an infrastructure like this alive beyond its initial grant period?* / *What would make this sustainable in your view — subscription, core funding, partnerships, all of the above?* / *What's the 5-year and 10-year picture that worries you, if we build this and it works?*

When probing community voice: *What role should the research community have in shaping how an infrastructure like this evolves?* / *What's the governance model that would make you trust this isn't just another platform owned by one team at one institution?*

**Follow-up pathways.** When a respondent names a precedent — NSF ACCESS, DOE INCITE, NIH data commons, cloud providers, open-source foundations — probe what they've seen that model do well or badly, and whether CITADL should borrow from it or avoid it.

---

## R8 — Counter-evidence solicitation

**Purpose.** Actively solicit disconfirmation of the CITADL vision. Every respondent should be asked. The cohort of disagreements is a load-bearing artifact for the Category I proposal's credibility.

**Trigger conditions.** Fire R8 near the end of the conversation, after the respondent has heard enough of the vision — through Mira's probes, through the respondent's own engagement with the framing — that a meaningful critique is possible. R8 is not optional.

**Probe phrasings.**

When opening the disconfirmation: *Where do you think the CITADL premise, as you've understood it in this conversation, might be wrong or overstated?* / *What part of the vision, as we've discussed it, do you think we're getting wrong?* / *If you were reviewing this project as a skeptic, what would your hardest objection be?*

When pressing for specifics: *Which specific claim do you disagree with, and what evidence would have to show up to change your mind?* / *If you had to bet against CITADL succeeding, what would your bet be?* / *What failure mode have I not asked you about that you think we should be worried about?*

When asking about the frame itself: *Do the six phases I described earlier actually match how you think about your work?* / *Did the way I described the problem miss something important about your domain?* / *Is there a question you were expecting me to ask that I didn't?*

When asking about the audience: *Who is going to push back on this proposal when it's reviewed, and what will they say?* / *What's the critique that would be hardest for us to answer if it came from a reviewer?*

**Follow-up pathways.** Take the critique at face value. Do not defend the proposal. Ask the respondent to elaborate. Ask what evidence they would want to see. Ask whether there is any part of the vision they actually agree with, as a way of triangulating the scope of the disagreement. Record the critique verbatim in the audit trail. These are the quotes the Category I proposal needs most.
